import { describe, expect, it } from "vitest";
import type {
  RequirementActionEvidenceContract,
  RequirementActionEvidencePreview,
  RequirementActionProposal,
} from "./contracts";
import {
  RequirementActionEvidencePayloadError,
  REQUIREMENT_ACTION_FILE_JSON_SCHEMA,
  REQUIREMENT_ACTION_FILE_SCHEMA_SHA256,
  parseRequirementActionEvidenceContract,
  parseRequirementActionEvidencePreview,
  parseRequirementActionImport,
  parseRequirementActionProposal,
  parseRequirementActionProposalPage,
  parseRequirementActionProposalReview,
  requirementActionProposalMatchesContract,
  requirementActionUtcMicrosecondKey,
} from "./requirementActionEvidenceContract";

const SESSION = "1".repeat(64);
const RUN = "a".repeat(64);
const WINDOW = "b".repeat(64);
const PLAN_CONFIRMATION = "c".repeat(64);
const PLAN_FINGERPRINT = "d".repeat(64);
const MANIFEST = "e".repeat(64);
const PREDECESSOR = "f".repeat(64);
const PAYLOAD = "0".repeat(64);
const PROPOSAL = "6".repeat(64);
const RECEIPT = "7".repeat(64);
const GRAPH = "8".repeat(64);
const CANDIDATE_SET = "9".repeat(64);
const DESCRIPTOR_SET = "12".repeat(32);

const provenance = {
  provider: "synthetic" as const,
  provider_version: "synthetic-v1",
  adapter_version: "adapter-v1",
  decoder_key: "safe-event-evidence",
  decoder_version: "safe-event-v1",
  source_schema_version: "synthetic-schema-v1",
  evidence_schema_version: 2 as const,
  extraction_complete: true,
};

const candidates = [
  {
    candidate_index: 0,
    action_id: "4".repeat(64),
    source_reference_id: "a".repeat(64),
    sequence: 11,
    event_kind: "tool_start" as const,
    tool_category: "file_write" as const,
    occurred_at: "2030-01-02T03:04:05.000001+00:00",
    duration_ms: null,
    family: "file_change" as const,
    state: "started" as const,
  },
  {
    candidate_index: 1,
    action_id: "5".repeat(64),
    source_reference_id: "b".repeat(64),
    sequence: 12,
    event_kind: "tool_end" as const,
    tool_category: "test" as const,
    occurred_at: "2030-01-02T03:04:05.000010Z",
    duration_ms: 17,
    family: "tool" as const,
    state: "completed" as const,
  },
];

const requirements = [
  { requirement_index: 0, requirement_id: "2".repeat(64), coordinate: { message_sequence: 3, clause_index: 0 } },
  { requirement_index: 1, requirement_id: "3".repeat(64), coordinate: { message_sequence: 4, clause_index: 1 } },
];

function contractFixture(): RequirementActionEvidenceContract {
  return {
    schema_version: "requirement-action-evidence-file-v1",
    session_id: SESSION,
    expected_source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    source_projection_version: "metric-contract-v2-projection-7",
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest: {
      session_id: SESSION,
      source_run_id: RUN,
      source_window_fingerprint: WINDOW,
      provenance,
      extraction_complete: true,
      enumeration_complete: true,
      actions: structuredClone(candidates),
      manifest_fingerprint: MANIFEST,
      schema_version: "requirement-action-candidate-manifest-v1",
      local_only: true,
      content_persisted: false,
    },
    requirements: structuredClone(requirements),
    expected_predecessor_confirmation_id: PREDECESSOR,
    metric_key: "logic.requirement_action_traceability",
    max_requirement_count: 1000,
    max_candidate_count: 4000,
    max_link_count: 8000,
    max_file_bytes: 65536,
    max_json_depth: 8,
    max_json_items: 8000,
    max_lifetime_seconds: 86400,
    canonicalization: "json-sort-keys-compact-ensure-ascii-v1",
    import_creates_unconfirmed_proposal_only: true,
    native_confirmation_required_for_metric_authority: true,
    action_descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1",
    action_descriptor_content_persisted: false,
    candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1",
    all_linked_action_semantics_acknowledgement_required: true,
    native_review_displays_every_redacted_invocation_and_effect: true,
    review_rubric_version: "requirement-action-review-rubric-v2",
    review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1",
    review_visible_display_is_injective_one_pass: true,
    review_visible_display_never_truncates: true,
    every_requirement_requires_one_link_classification: true,
    empty_action_links_are_explicit_reviewed_negative_links: true,
    action_states_are_application_issued: true,
    action_state_claims_allowed_in_file: false,
    objective_proof_claims_allowed_in_file: false,
    metric_values_allowed_in_file: false,
    raw_payload_persisted: false,
    raw_producer_claim_persisted: false,
    durable_producer_claim_shape: "installation_keyed_opaque_commitment_only",
    import_confirmation: "import_requirement_action_proposal_without_metric_authority",
    file_json_schema_sha256: "e25e6c1902cc2c7c1f0bdf138c4ac383c0b858e5516cceb05d9be89b6e46c500",
    file_json_schema: structuredClone(REQUIREMENT_ACTION_FILE_JSON_SCHEMA),
  };
}

function previewFixture(): RequirementActionEvidencePreview {
  return {
    payload_sha256: PAYLOAD,
    session_id: SESSION,
    expected_source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    expected_predecessor_confirmation_id: PREDECESSOR,
    requirement_count: 2,
    candidate_count: 2,
    linked_requirement_count: 1,
    unlinked_requirement_count: 1,
    link_count: 1,
    expires_at: "2030-01-02T04:04:05.123456+00:00",
    producer: {
      kind: "local_coding_agent",
      producer_id: "example-agent",
      producer_version: "v1",
      model_id: "example-model",
      authority: "untrusted_provenance_claim",
    },
    creates_unconfirmed_proposal_only: true,
    native_confirmation_required_for_metric_authority: true,
    can_set_numeric_metric_on_import: false,
    raw_payload_persisted: false,
    raw_producer_claim_persisted: false,
  };
}

function proposalFixture(): RequirementActionProposal {
  return {
    proposal_id: PROPOSAL,
    session_id: SESSION,
    source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    candidate_provenance: provenance,
    candidate_extraction_complete: true,
    candidate_enumeration_complete: true,
    expected_predecessor_confirmation_id: PREDECESSOR,
    payload_sha256: PAYLOAD,
    producer_receipt: {
      kind: "local_coding_agent",
      claim_fingerprint: "1".repeat(64),
      authority: "untrusted_provenance_claim_commitment",
      raw_claim_persisted: false,
    },
    review_rubric_version: "requirement-action-review-rubric-v2",
    requirements: structuredClone(requirements),
    candidates: structuredClone(candidates),
    links: [
      { requirement_id: requirements[0].requirement_id, action_ids: [candidates[1].action_id] },
      { requirement_id: requirements[1].requirement_id, action_ids: [] },
    ],
    created_at: "2030-01-02T03:04:05.123456+00:00",
    schema_version: "requirement-action-evidence-v1",
    policy_version: "reviewed-requirement-action-v1",
    status: "proposed",
    decision_id: null,
    decision: null,
    decided_at: null,
    confirmation_authority: null,
    local_only: true,
    content_persisted: false,
  };
}

function reviewFixture() {
  const proposal = proposalFixture();
  return {
    proposal_id: PROPOSAL,
    session_id: SESSION,
    source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    review_receipt_id: RECEIPT,
    payload_sha256: PAYLOAD,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    reviewed_graph_fingerprint: GRAPH,
    reviewed_candidate_set_fingerprint: CANDIDATE_SET,
    reviewed_descriptor_set_fingerprint: DESCRIPTOR_SET,
    review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1",
    requirements: [
      { ...requirements[0], requirement_index: undefined, text: "Create the synthetic artifact.", linked_action_ids: [candidates[1].action_id] },
      { ...requirements[1], requirement_index: undefined, text: "Document the synthetic result.", linked_action_ids: [] },
    ].map(({ requirement_index: _discard, ...item }) => item),
    candidates: structuredClone(candidates),
    candidate_memberships: [
      {
        candidate: structuredClone(candidates[0]),
        candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1",
        candidate_metadata_fingerprint: "7".repeat(64),
        descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1",
        tool_name: "synthetic.write",
        invocation_preview: "{\"target\":\"[redacted synthetic target]\"}",
        result_or_effect_preview: null,
        invocation_truncated: false,
        result_or_effect_truncated: false,
        redactor_version: "synthetic-redactor-v1",
        linked_requirement_ids: [],
      },
      {
        candidate: structuredClone(candidates[1]),
        candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1",
        candidate_metadata_fingerprint: "8".repeat(64),
        descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1",
        tool_name: "synthetic.test",
        invocation_preview: "{\"suite\":\"example\"}",
        result_or_effect_preview: "{\"status\":\"passed\"}",
        invocation_truncated: false,
        result_or_effect_truncated: false,
        redactor_version: "synthetic-redactor-v1",
        linked_requirement_ids: [requirements[0].requirement_id],
      },
    ],
    review_context_expires_at: "2030-01-02T04:00:00.000001+00:00",
    review_receipt_expires_at: "2030-01-02T03:30:00.999999Z",
    all_requirements_and_candidates_displayed: true,
    raw_text_persisted: false,
    local_only: true,
    _proposal: proposal,
  };
}

describe("requirement-action evidence contract", () => {
  it("accepts the exact contract, preview, proposal, import, page, and complete review", () => {
    const contract = parseRequirementActionEvidenceContract(contractFixture(), SESSION);
    const preview = parseRequirementActionEvidencePreview(previewFixture(), { sessionId: SESSION, contract });
    const proposal = parseRequirementActionProposal(proposalFixture());
    expect(parseRequirementActionImport({
      payload_sha256: PAYLOAD,
      proposal,
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
      raw_producer_claim_persisted: false,
    }, preview).proposal).toEqual(proposal);
    const snapshot = {
      snapshot_id: "a".repeat(64),
      total: 1,
      decision_count: 0,
      high_water_created_at: proposal.created_at,
      high_water_proposal_id: proposal.proposal_id,
    };
    expect(parseRequirementActionProposalPage({
      session_id: SESSION,
      proposals: [proposal],
      limit: 200,
      offset: 0,
      total: 1,
      snapshot,
      next_offset: null,
      complete: true,
    }, { sessionId: SESSION, limit: 200, offset: 0, snapshot: null }).snapshot).toEqual(snapshot);
    const rawReview = reviewFixture();
    const { _proposal: ignored, ...review } = rawReview;
    expect(ignored).toEqual(proposal);
    expect(parseRequirementActionProposalReview(review, { sessionId: SESSION, proposal, contract }))
      .toMatchObject({ review_receipt_id: RECEIPT, all_requirements_and_candidates_displayed: true });
  });

  it("requires the exact fixed file JSON Schema while accepting object-key reordering", async () => {
    const canonical = (value: unknown): string => {
      if (value === null || typeof value !== "object") return JSON.stringify(value);
      if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
      const row = value as Record<string, unknown>;
      return `{${Object.keys(row).sort().map((key) => (
        `${JSON.stringify(key)}:${canonical(row[key])}`
      )).join(",")}}`;
    };
    const schemaDigest = [...new Uint8Array(await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical(REQUIREMENT_ACTION_FILE_JSON_SCHEMA)),
    ))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    expect(schemaDigest).toBe(REQUIREMENT_ACTION_FILE_SCHEMA_SHA256);

    const reverseKeys = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(reverseKeys);
      if (typeof value !== "object" || value === null) return value;
      return Object.fromEntries(
        Object.entries(value as Record<string, unknown>).reverse()
          .map(([key, child]) => [key, reverseKeys(child)]),
      );
    };
    const reordered = contractFixture();
    reordered.file_json_schema = reverseKeys(reordered.file_json_schema) as Record<string, unknown>;
    expect(parseRequirementActionEvidenceContract(reordered, SESSION).file_json_schema)
      .toEqual(reordered.file_json_schema);

    for (const mutate of [
      (value: any) => { value.file_json_schema = {}; },
      (value: any) => { value.file_json_schema.$defs.RequirementActionLinkEntry
        .properties.action_candidate_indexes.maxItems = 3_999; },
      (value: any) => { value.file_json_schema.properties.contains_paths.const = true; },
      (value: any) => { value.file_json_schema.unadvertised = false; },
      (value: any) => { value.file_json_schema_sha256 = "0".repeat(64); },
    ]) {
      const drifted = contractFixture() as unknown as Record<string, any>;
      mutate(drifted);
      expect(() => parseRequirementActionEvidenceContract(drifted, SESSION))
        .toThrow(RequirementActionEvidencePayloadError);
    }
  });

  it("rejects unknown fields, drifted bindings, incoherent counts, and unsafe candidates", () => {
    const extra = { ...contractFixture(), surprise: false };
    expect(() => parseRequirementActionEvidenceContract(extra, SESSION)).toThrow(RequirementActionEvidencePayloadError);

    const drifted = previewFixture();
    drifted.candidate_manifest_fingerprint = "0".repeat(64);
    expect(() => parseRequirementActionEvidencePreview(drifted, {
      sessionId: SESSION, contract: contractFixture(),
    })).toThrow(RequirementActionEvidencePayloadError);

    const counts = previewFixture();
    counts.unlinked_requirement_count = 0;
    expect(() => parseRequirementActionEvidencePreview(counts, { sessionId: SESSION }))
      .toThrow(RequirementActionEvidencePayloadError);

    const unsafe = contractFixture() as unknown as Record<string, any>;
    unsafe.candidate_manifest.actions[0].event_kind = "response";
    expect(() => parseRequirementActionEvidenceContract(unsafe, SESSION))
      .toThrow(RequirementActionEvidencePayloadError);
  });

  it("keeps ephemeral semantic descriptor text out of durable proposal candidates", () => {
    const leaked = proposalFixture() as unknown as Record<string, any>;
    leaked.candidates[0].invocation_preview = "synthetic review-only invocation";
    expect(() => parseRequirementActionProposal(leaked))
      .toThrow(RequirementActionEvidencePayloadError);

    const leakedMemberships = proposalFixture() as unknown as Record<string, any>;
    leakedMemberships.candidate_memberships = [];
    expect(() => parseRequirementActionProposal(leakedMemberships))
      .toThrow(RequirementActionEvidencePayloadError);

    const leakedMetadataReceipt = proposalFixture() as unknown as Record<string, any>;
    leakedMetadataReceipt.candidates[0].candidate_metadata_fingerprint = "7".repeat(64);
    expect(() => parseRequirementActionProposal(leakedMetadataReceipt))
      .toThrow(RequirementActionEvidencePayloadError);
    expect(() => parseRequirementActionProposalPage({
      session_id: SESSION,
      proposals: [leakedMetadataReceipt],
      limit: 200,
      offset: 0,
      total: 1,
      snapshot: {
        snapshot_id: "a".repeat(64),
        total: 1,
        decision_count: 0,
        high_water_created_at: leakedMetadataReceipt.created_at,
        high_water_proposal_id: leakedMetadataReceipt.proposal_id,
      },
      next_offset: null,
      complete: true,
    }, { sessionId: SESSION, limit: 200, offset: 0, snapshot: null }))
      .toThrow(RequirementActionEvidencePayloadError);
  });

  it("accepts explicit empty links but rejects incomplete, reordered, or foreign graphs", () => {
    expect(parseRequirementActionProposal(proposalFixture()).links[1].action_ids).toEqual([]);

    const reordered = proposalFixture();
    reordered.requirements.reverse();
    expect(() => parseRequirementActionProposal(reordered)).toThrow(RequirementActionEvidencePayloadError);

    const foreign = proposalFixture();
    foreign.links[0].action_ids = ["f".repeat(64)];
    expect(() => parseRequirementActionProposal(foreign)).toThrow(RequirementActionEvidencePayloadError);

    const incomplete = contractFixture();
    incomplete.candidate_manifest.extraction_complete = false;
    expect(() => parseRequirementActionEvidenceContract(incomplete, SESSION))
      .toThrow(RequirementActionEvidencePayloadError);

    const consistentlyIncomplete = contractFixture();
    consistentlyIncomplete.candidate_manifest.extraction_complete = false;
    consistentlyIncomplete.candidate_manifest.enumeration_complete = false;
    consistentlyIncomplete.candidate_manifest.provenance.extraction_complete = false;
    expect(() => parseRequirementActionEvidenceContract(consistentlyIncomplete, SESSION))
      .toThrow(RequirementActionEvidencePayloadError);
  });

  it("rejects a review that hides a requirement, candidate, or membership", () => {
    const contract = contractFixture();
    const proposal = proposalFixture();
    for (const mutate of [
      (value: any) => value.requirements.pop(),
      (value: any) => value.candidates.pop(),
      (value: any) => value.candidate_memberships[1].linked_requirement_ids = [],
    ]) {
      const raw = reviewFixture();
      const { _proposal: _ignored, ...review } = raw;
      mutate(review);
      expect(() => parseRequirementActionProposalReview(review, {
        sessionId: SESSION, proposal, contract,
      })).toThrow(RequirementActionEvidencePayloadError);
    }
  });

  it("rejects incomplete, malformed, or semantically incoherent redacted descriptors", () => {
    const contract = contractFixture();
    const proposal = proposalFixture();
    for (const mutate of [
      (value: any) => { delete value.reviewed_descriptor_set_fingerprint; },
      (value: any) => { value.reviewed_descriptor_set_fingerprint = "not-a-fingerprint"; },
      (value: any) => { value.review_visible_display_algorithm_version = "future-visible-display-v2"; },
      (value: any) => { delete value.candidate_memberships[0].candidate_metadata_fingerprint; },
      (value: any) => { value.candidate_memberships[0].candidate_metadata_fingerprint = "not-a-fingerprint"; },
      (value: any) => { value.candidate_memberships[0].candidate_metadata_fingerprint_version = "future-metadata-v2"; },
      (value: any) => { value.candidate_memberships[0].descriptor_algorithm_version = "future-v2"; },
      (value: any) => { value.candidate_memberships[0].tool_name = "synthetic\0write"; },
      (value: any) => { value.candidate_memberships[0].invocation_truncated = true; },
      (value: any) => { value.candidate_memberships[1].result_or_effect_preview = null; },
      (value: any) => { value.candidate_memberships[1].unexpected_descriptor_claim = "success"; },
    ]) {
      const raw = reviewFixture();
      const { _proposal: _ignored, ...review } = raw;
      mutate(review);
      expect(() => parseRequirementActionProposalReview(review, {
        sessionId: SESSION, proposal, contract,
      })).toThrow(RequirementActionEvidencePayloadError);
    }
  });

  it("pins one-pass visible display and rejects raw controls without decoding literal escapes", () => {
    const contract = contractFixture();
    const proposal = proposalFixture();
    const raw = reviewFixture();
    const { _proposal: _ignored, ...review } = raw;
    review.requirements[0].text = "Control \\u202e; literal \\\\u202e; line \\n; slash A\\\\B.";
    review.candidate_memberships[0].tool_name = "tool\\n\\u202e\\\\u202e";
    review.candidate_memberships[0].invocation_preview = "invoke\\t\\u2028\\\\path";
    const parsed = parseRequirementActionProposalReview(review, {
      sessionId: SESSION, proposal, contract,
    });
    expect(parsed.requirements[0].text).toBe(review.requirements[0].text);
    expect(parsed.candidate_memberships[0].invocation_preview)
      .toBe("invoke\\t\\u2028\\\\path");

    for (const mutate of [
      (value: any) => { value.requirements[0].text = "raw\nnewline"; },
      (value: any) => { value.requirements[0].text = "raw\u202eoverride"; },
      (value: any) => { value.candidate_memberships[0].tool_name = "raw\nnewline"; },
      (value: any) => { value.candidate_memberships[0].invocation_preview = "raw\u202eoverride"; },
      (value: any) => { value.candidate_memberships[1].result_or_effect_preview = "raw\u2028layout"; },
    ]) {
      const candidate = reviewFixture();
      const { _proposal: _discard, ...candidateReview } = candidate;
      mutate(candidateReview);
      expect(() => parseRequirementActionProposalReview(candidateReview, {
        sessionId: SESSION, proposal, contract,
      })).toThrow(RequirementActionEvidencePayloadError);
    }

    for (const mutate of [
      (value: any) => { value.review_visible_display_algorithm_version = "future-visible-display-v2"; },
      (value: any) => { value.review_visible_display_is_injective_one_pass = false; },
      (value: any) => { value.review_visible_display_never_truncates = false; },
      (value: any) => { value.candidate_metadata_fingerprint_version = "future-metadata-v2"; },
    ]) {
      const driftedContract = contractFixture() as unknown as Record<string, any>;
      mutate(driftedContract);
      expect(() => parseRequirementActionEvidenceContract(driftedContract, SESSION))
        .toThrow(RequirementActionEvidencePayloadError);
    }
  });

  it("cross-binds proposal provenance, completeness, requirements, and candidates to the contract", () => {
    expect(requirementActionProposalMatchesContract(proposalFixture(), contractFixture())).toBe(true);
    for (const mutate of [
      (proposal: any) => { proposal.candidate_provenance.adapter_version = "drifted-adapter-v2"; },
      (proposal: any) => { proposal.candidate_extraction_complete = false; },
      (proposal: any) => { proposal.candidate_enumeration_complete = false; },
      (proposal: any) => { proposal.requirements[0].coordinate.clause_index = 7; },
      (proposal: any) => { proposal.candidates[0].state = "unknown"; },
    ]) {
      const proposal = structuredClone(proposalFixture()) as unknown as Record<string, any>;
      mutate(proposal);
      expect(requirementActionProposalMatchesContract(
        proposal as unknown as RequirementActionProposal,
        contractFixture(),
      )).toBe(false);
      const raw = reviewFixture();
      const { _proposal: _ignored, ...review } = raw;
      expect(() => parseRequirementActionProposalReview(review, {
        sessionId: SESSION,
        proposal: proposal as unknown as RequirementActionProposal,
        contract: contractFixture(),
      })).toThrow(RequirementActionEvidencePayloadError);
    }
  });

  it("cross-binds every displayed review requirement to contract identity, coordinate, and order", () => {
    const proposal = proposalFixture();
    const contract = contractFixture();
    for (const mutate of [
      (value: any) => { value.requirements[0].requirement_id = requirements[1].requirement_id; },
      (value: any) => { value.requirements[0].coordinate.clause_index = 1; },
      (value: any) => { value.requirements.reverse(); },
      (value: any) => { value.candidate_memberships.reverse(); },
    ]) {
      const raw = reviewFixture();
      const { _proposal: _ignored, ...review } = raw;
      mutate(review);
      expect(() => parseRequirementActionProposalReview(review, {
        sessionId: SESSION, proposal, contract,
      })).toThrow(RequirementActionEvidencePayloadError);
    }

    const driftedContract = contractFixture();
    driftedContract.requirements[0].coordinate.clause_index = 1;
    const raw = reviewFixture();
    const { _proposal: _ignored, ...review } = raw;
    expect(() => parseRequirementActionProposalReview(review, {
      sessionId: SESSION, proposal, contract: driftedContract,
    })).toThrow(RequirementActionEvidencePayloadError);
  });

  it("preserves full UTC microsecond ordering without Date millisecond truncation", () => {
    expect(
      requirementActionUtcMicrosecondKey("2030-01-02T03:04:05.000001Z")
      < requirementActionUtcMicrosecondKey("2030-01-02T03:04:05.000010+00:00"),
    ).toBe(true);
    expect(() => requirementActionUtcMicrosecondKey("2030-02-30T03:04:05Z"))
      .toThrow(RequirementActionEvidencePayloadError);
  });
});
