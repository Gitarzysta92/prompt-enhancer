import { describe, expect, it } from "vitest";
import {
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_V2_CONTRACT_IDENTITIES,
} from "./metricPublicationV2Contract";
import {
  REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES,
  REQUIREMENT_PLAN_FILE_JSON_SCHEMA,
  REQUIREMENT_PLAN_FILE_SCHEMA_SHA256,
  REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC,
  REQUIREMENT_PLAN_REVIEW_RUBRIC,
  RequirementPlanEvidencePayloadError,
  parseRequirementPlanEvidenceContract,
  parseRequirementPlanEvidencePreview,
  parseRequirementPlanImport,
  parseRequirementPlanProposal,
  parseRequirementPlanProposalOutcome,
  parseRequirementPlanProposalPage,
  parseRequirementPlanProposalReview,
} from "./requirementPlanEvidenceContract";

const SESSION_ID = "a".repeat(64);
const RUN_ID = "b".repeat(64);
const WINDOW_ID = "c".repeat(64);
const PAYLOAD_ID = "d".repeat(64);
const PROPOSAL_ID = "e".repeat(64);

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    );
  }
  return value;
}

function contractFixture() {
  return {
    schema_version: "requirement-plan-evidence-file-v1",
    session_id: SESSION_ID,
    expected_source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    registry_version: "all-20-factor-contracts-v2",
    contract_set_fingerprint: METRIC_CONTRACT_V2_SET_FINGERPRINT,
    metric_key: "logic.decomposition_coverage",
    metric_contract_fingerprint: METRIC_V2_CONTRACT_IDENTITIES["logic.decomposition_coverage"].fingerprint,
    source_projection_version: "metric-contract-v2-projection-6",
    clause_algorithm: "message-clause-coordinates-en-pl-v1",
    clause_algorithm_spec: structuredClone(REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC),
    review_rubric_version: "active-requirement-plan-review-rubric-v1",
    review_rubric: structuredClone(REQUIREMENT_PLAN_REVIEW_RUBRIC),
    allowed_dispositions: ["linked", "not_linked", "pending"],
    allowed_user_clause_classifications: [
      "active_requirement", "excluded_from_active_requirement_denominator",
    ],
    allowed_exclusion_reasons: [
      "not_requirement", "superseded", "withdrawn", "duplicate", "out_of_scope",
      "already_satisfied_or_closed",
    ],
    max_reviewed_user_clause_count: 1000,
    max_active_requirement_count: 1000,
    max_excluded_user_clause_count: 1000,
    max_plan_item_count: 1000,
    max_link_count: 4000,
    max_file_bytes: 65536,
    max_json_depth: 8,
    max_json_items: 6000,
    max_clauses_per_message: 128,
    max_lifetime_seconds: 86400,
    canonical_json_required: true,
    canonicalization: "json-sort-keys-compact-ensure-ascii-v1",
    payload_digest: "sha256",
    utf8_without_bom_required: true,
    duplicate_keys_allowed: false,
    floating_point_values_allowed: false,
    candidate_unit: "reviewable_user_request_or_feedback_clause",
    opportunity_unit: "reviewed_active_requirement_clause",
    complete_user_clause_classification_required: true,
    compound_clause_coarsening_disclosed: true,
    one_active_requirement_coordinate_is_one_opportunity: true,
    excluded_user_clauses_are_excluded_from_metric: true,
    uncertain_classification_policy: "reject_or_leave_proposal_unconfirmed",
    import_creates_unconfirmed_proposal_only: true,
    native_confirmation_required_for_metric_authority: true,
    raw_payload_persisted: false,
    prose_allowed: false,
    scores_allowed: false,
    untrusted_structured_classification_proposals_allowed: true,
    authoritative_model_judgment_claims_allowed: false,
    raw_producer_claim_persisted: false,
    durable_producer_claim_shape: "installation_keyed_opaque_commitment_only",
    objective_receipt_claims_allowed: false,
    import_confirmation: "import_requirement_plan_evidence_as_unconfirmed_proposal",
    file_json_schema_sha256: REQUIREMENT_PLAN_FILE_SCHEMA_SHA256,
    file_json_schema: structuredClone(REQUIREMENT_PLAN_FILE_JSON_SCHEMA),
    source_manifest: {
      session_id: SESSION_ID,
      source_run_id: RUN_ID,
      source_window_fingerprint: WINDOW_ID,
      schema_version: "requirement-plan-source-manifest-v1",
      clause_algorithm: "message-clause-coordinates-en-pl-v1",
      clause_algorithm_spec: structuredClone(REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC),
      review_rubric_version: "active-requirement-plan-review-rubric-v1",
      review_rubric: structuredClone(REQUIREMENT_PLAN_REVIEW_RUBRIC),
      messages: [
        { message_sequence: 1, role: "user", kind: "request", clause_count: 2 },
        { message_sequence: 2, role: "agent", kind: "plan", clause_count: 1 },
        { message_sequence: 3, role: "user", kind: "feedback", clause_count: 1 },
        { message_sequence: 4, role: "agent", kind: "plan", clause_count: 1 },
      ],
      message_count: 4,
      candidate_clause_count: 5,
      manifest_fingerprint: "8".repeat(64),
      review_context_expires_at: "2040-01-02T11:00:00Z",
      contains_text: false,
      local_only: true,
      content_persisted: false,
    },
    file_constraint_contract_version: "requirement-plan-file-constraints-v1",
    file_constraint_codes: [...REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES],
  };
}

function previewFixture() {
  return {
    payload_sha256: PAYLOAD_ID,
    session_id: SESSION_ID,
    expected_source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    reviewed_user_clause_count: 3,
    active_requirement_count: 2,
    excluded_user_clause_count: 1,
    plan_item_count: 2,
    linked_active_requirement_count: 1,
    not_linked_active_requirement_count: 0,
    pending_active_requirement_count: 1,
    link_count: 2,
    expires_at: "2040-01-02T10:00:00Z",
    producer: {
      kind: "local_coding_agent",
      producer_id: "example-agent",
      producer_version: "example-v1",
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

function proposalFixture(status: "proposed" | "confirmed" | "rejected" = "proposed") {
  const decided = status !== "proposed";
  return {
    proposal_id: PROPOSAL_ID,
    session_id: SESSION_ID,
    source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    payload_sha256: PAYLOAD_ID,
    producer_receipt: {
      kind: "local_coding_agent",
      claim_fingerprint: "7".repeat(64),
      authority: "untrusted_provenance_claim_commitment",
      raw_claim_persisted: false,
    },
    review_rubric_version: "active-requirement-plan-review-rubric-v1",
    requirements: [
      { coordinate: { message_sequence: 1, clause_index: 0 }, disposition: "linked", plan_indexes: [0, 1] },
      { coordinate: { message_sequence: 3, clause_index: 0 }, disposition: "pending", plan_indexes: [] },
    ],
    excluded_user_clauses: [{
      coordinate: { message_sequence: 1, clause_index: 1 },
      reason: "duplicate",
      basis_coordinate: { message_sequence: 1, clause_index: 0 },
    }],
    plan_items: [
      { message_sequence: 2, clause_index: 0 },
      { message_sequence: 4, clause_index: 0 },
    ],
    created_at: "2040-01-02T09:00:00Z",
    schema_version: "requirement-plan-evidence-v1",
    policy_version: "reviewed-requirement-plan-v1",
    status,
    decision_id: decided ? "f".repeat(64) : null,
    decision: status === "confirmed" ? "confirm" : status === "rejected" ? "reject" : null,
    decided_at: decided ? "2040-01-02T10:00:00Z" : null,
    confirmation_authority: decided ? "owned_native_user_presence" : null,
    local_only: true,
    content_persisted: false,
  };
}

describe("requirement-plan evidence wire contract", () => {
  it("pins the exact agent-file JSON Schema to the backend SHA-256 identity", async () => {
    const payload = new TextEncoder().encode(JSON.stringify(canonical(
      REQUIREMENT_PLAN_FILE_JSON_SCHEMA,
    )));
    const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", payload))]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    expect(digest).toBe(REQUIREMENT_PLAN_FILE_SCHEMA_SHA256);
  });

  it("accepts only the exact content-free contract and preview identities", () => {
    const contract = contractFixture();
    expect(parseRequirementPlanEvidenceContract(structuredClone(contract), SESSION_ID)).toEqual(contract);
    const r7Contract = structuredClone(contract);
    r7Contract.source_projection_version = "metric-contract-v2-projection-7";
    expect(parseRequirementPlanEvidenceContract(r7Contract, SESSION_ID)).toEqual(r7Contract);
    const preview = previewFixture();
    expect(parseRequirementPlanEvidencePreview(structuredClone(preview), SESSION_ID)).toEqual(preview);

    for (const mutate of [
      (value: any) => { value.private_text = "forbidden"; },
      (value: any) => { value.prose_allowed = true; },
      (value: any) => { value.expected_source_run_id = "short"; },
      (value: any) => { value.source_projection_version = "metric-contract-v2-projection-4"; },
      (value: any) => { value.allowed_dispositions.reverse(); },
      (value: any) => { value.metric_contract_fingerprint = "0".repeat(64); },
      (value: any) => { value.file_constraint_contract_version = "requirement-plan-file-constraints-v2"; },
      (value: any) => { value.file_constraint_codes.reverse(); },
      (value: any) => { value.file_json_schema_sha256 = "0".repeat(64); },
      (value: any) => {
        value.file_json_schema.$defs.RequirementEvidenceEntry.properties
          .plan_indexes.uniqueItems = false;
      },
      (value: any) => {
        value.file_json_schema.$defs.RequirementEvidenceEntry.properties
          .plan_indexes.items.minimum = -1;
      },
      (value: any) => {
        value.file_json_schema.properties.session_id.pattern = "^.+$";
      },
      (value: any) => {
        value.file_json_schema["x-prompt-enhancer-constraints"][0].required = false;
      },
    ]) {
      const invalid = structuredClone(contract);
      mutate(invalid);
      expect(() => parseRequirementPlanEvidenceContract(invalid, SESSION_ID)).toThrow(
        RequirementPlanEvidencePayloadError,
      );
    }
    const badCounts = structuredClone(preview);
    badCounts.pending_active_requirement_count = 0;
    expect(() => parseRequirementPlanEvidencePreview(badCounts, SESSION_ID)).toThrow(
      RequirementPlanEvidencePayloadError,
    );
  });

  it("validates sorted coordinates, closed dispositions, link indexes, and native decision state", () => {
    const proposed = proposalFixture();
    expect(parseRequirementPlanProposal(structuredClone(proposed))).toEqual(proposed);
    expect(parseRequirementPlanProposal(proposalFixture("confirmed")).status).toBe("confirmed");
    expect(parseRequirementPlanProposal(proposalFixture("rejected")).status).toBe("rejected");

    for (const mutate of [
      (value: any) => { value.requirements.reverse(); },
      (value: any) => { value.plan_items.reverse(); },
      (value: any) => { value.requirements[0].plan_indexes = []; },
      (value: any) => { value.requirements[1].plan_indexes = [0]; },
      (value: any) => { value.requirements[0].plan_indexes = [2]; },
      (value: any) => { value.plan_items[0].message_sequence = 0; },
      (value: any) => { value.excluded_user_clauses[0].basis_coordinate = null; },
      (value: any) => { value.excluded_user_clauses[0].coordinate = value.requirements[0].coordinate; },
      (value: any) => { value.producer_receipt.raw_claim_persisted = true; },
      (value: any) => { value.confirmation_authority = "authenticated_local_user"; },
      (value: any) => { value.raw_text = "forbidden"; },
    ]) {
      const invalid = structuredClone(proposed);
      mutate(invalid);
      expect(() => parseRequirementPlanProposal(invalid)).toThrow(
        RequirementPlanEvidencePayloadError,
      );
    }
  });

  it("cross-binds import, paged proposals, and native outcomes to one session/run/window", () => {
    const preview = parseRequirementPlanEvidencePreview(previewFixture(), SESSION_ID);
    const proposal = proposalFixture();
    const imported = {
      payload_sha256: PAYLOAD_ID,
      proposal,
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
    };
    expect(parseRequirementPlanImport(structuredClone(imported), preview)).toEqual(imported);
    const wrongWindow = structuredClone(imported);
    wrongWindow.proposal.source_window_fingerprint = "9".repeat(64);
    expect(() => parseRequirementPlanImport(wrongWindow, preview)).toThrow(
      RequirementPlanEvidencePayloadError,
    );

    const page = {
      session_id: SESSION_ID,
      proposals: [proposal],
      limit: 200,
      offset: 0,
      total: 1,
      snapshot: {
        snapshot_id: "4".repeat(64),
        total: 1,
        decision_count: 0,
        high_water_created_at: proposal.created_at,
        high_water_proposal_id: proposal.proposal_id,
      },
      next_offset: null,
      complete: true,
    };
    expect(parseRequirementPlanProposalPage(structuredClone(page), SESSION_ID, 200, 0)).toEqual(page);
    const incomplete = structuredClone(page);
    incomplete.complete = false;
    expect(() => parseRequirementPlanProposalPage(incomplete, SESSION_ID, 200, 0)).toThrow(
      RequirementPlanEvidencePayloadError,
    );

    const confirmed = proposalFixture("confirmed");
    const outcome = { proposal: confirmed, applied: true };
    expect(parseRequirementPlanProposalOutcome(structuredClone(outcome), {
      sessionId: SESSION_ID,
      proposalId: PROPOSAL_ID,
      sourceRunId: RUN_ID,
      decision: "confirm",
    })).toEqual(outcome);
    expect(() => parseRequirementPlanProposalOutcome(outcome, {
      sessionId: SESSION_ID,
      proposalId: PROPOSAL_ID,
      sourceRunId: RUN_ID,
      decision: "reject",
    })).toThrow(RequirementPlanEvidencePayloadError);
  });

  it("binds every active, excluded, and plan clause in an ephemeral native review", () => {
    const proposal = parseRequirementPlanProposal(proposalFixture());
    const contract = parseRequirementPlanEvidenceContract(contractFixture(), SESSION_ID);
    const review = {
      proposal_id: PROPOSAL_ID,
      session_id: SESSION_ID,
      source_run_id: RUN_ID,
      source_window_fingerprint: WINDOW_ID,
      review_receipt_id: "6".repeat(64),
      payload_sha256: PAYLOAD_ID,
      manifest_fingerprint: "8".repeat(64),
      reviewed_graph_fingerprint: "5".repeat(64),
      reviewed_candidate_set_fingerprint: "4".repeat(64),
      candidate_clauses: [
        {
          message_sequence: 1, clause_index: 0, role: "user", kind: "request",
          text: "Create the synthetic artifact.", candidate_kind: "user_clause",
          included_in_proposal: true, classification: "active_requirement",
          exclusion_reason: null, basis_coordinate: null, disposition: "linked",
          linked_plan_coordinates: [
            { message_sequence: 2, clause_index: 0 },
            { message_sequence: 4, clause_index: 0 },
          ],
        },
        {
          message_sequence: 1, clause_index: 1, role: "user", kind: "request",
          text: "Create the same artifact again.", candidate_kind: "user_clause",
          included_in_proposal: true,
          classification: "excluded_from_active_requirement_denominator",
          exclusion_reason: "duplicate",
          basis_coordinate: { message_sequence: 1, clause_index: 0 },
          disposition: null, linked_plan_coordinates: [],
        },
        {
          message_sequence: 2, clause_index: 0, role: "agent", kind: "plan",
          text: "Create the artifact.", candidate_kind: "plan", included_in_proposal: true,
          classification: null, exclusion_reason: null, basis_coordinate: null,
          disposition: null, linked_plan_coordinates: [],
        },
        {
          message_sequence: 3, clause_index: 0, role: "user", kind: "feedback",
          text: "Keep the verification pending.", candidate_kind: "user_clause",
          included_in_proposal: true, classification: "active_requirement",
          exclusion_reason: null, basis_coordinate: null, disposition: "pending",
          linked_plan_coordinates: [],
        },
        {
          message_sequence: 4, clause_index: 0, role: "agent", kind: "plan",
          text: "Verify the artifact.", candidate_kind: "plan", included_in_proposal: true,
          classification: null, exclusion_reason: null, basis_coordinate: null,
          disposition: null, linked_plan_coordinates: [],
        },
      ],
      review_context_expires_at: "2040-01-02T11:00:00Z",
      review_receipt_expires_at: "2040-01-02T10:05:00Z",
      all_coordinates_structurally_valid: true,
      raw_text_persisted: false,
      local_only: true,
    };
    expect(parseRequirementPlanProposalReview(structuredClone(review), {
      sessionId: SESSION_ID, proposal, contract,
    })).toEqual(review);
    for (const mutate of [
      (value: any) => { value.candidate_clauses.pop(); },
      (value: any) => { value.candidate_clauses.reverse(); },
      (value: any) => { value.candidate_clauses[0].classification = "excluded_from_active_requirement_denominator"; },
      (value: any) => { value.candidate_clauses[1].basis_coordinate = null; },
      (value: any) => { value.candidate_clauses[2].included_in_proposal = false; },
      (value: any) => { value.candidate_clauses[2].text = "Create\n  the artifact."; },
      (value: any) => { value.manifest_fingerprint = "0".repeat(64); },
      (value: any) => { value.review_receipt_expires_at = "2040-01-02T12:00:00Z"; },
      (value: any) => { value.private_path = "forbidden"; },
    ]) {
      const invalid = structuredClone(review);
      mutate(invalid);
      expect(() => parseRequirementPlanProposalReview(invalid, {
        sessionId: SESSION_ID, proposal, contract,
      })).toThrow(RequirementPlanEvidencePayloadError);
    }

    const extraActive = proposalFixture();
    extraActive.requirements.push({
      coordinate: { message_sequence: 5, clause_index: 0 },
      disposition: "pending",
      plan_indexes: [],
    });
    expect(() => parseRequirementPlanProposalReview(structuredClone(review), {
      sessionId: SESSION_ID,
      proposal: parseRequirementPlanProposal(extraActive),
      contract,
    })).toThrow(RequirementPlanEvidencePayloadError);

    const extraPlan = proposalFixture();
    extraPlan.plan_items.push({ message_sequence: 6, clause_index: 0 });
    expect(() => parseRequirementPlanProposalReview(structuredClone(review), {
      sessionId: SESSION_ID,
      proposal: parseRequirementPlanProposal(extraPlan),
      contract,
    })).toThrow(RequirementPlanEvidencePayloadError);

    const outsideBasisProposal = proposalFixture();
    outsideBasisProposal.excluded_user_clauses[0].reason = "superseded";
    outsideBasisProposal.excluded_user_clauses[0].basis_coordinate = {
      message_sequence: 5, clause_index: 0,
    };
    const outsideBasisReview = structuredClone(review);
    outsideBasisReview.candidate_clauses[1].exclusion_reason = "superseded";
    outsideBasisReview.candidate_clauses[1].basis_coordinate = {
      message_sequence: 5, clause_index: 0,
    };
    expect(() => parseRequirementPlanProposalReview(outsideBasisReview, {
      sessionId: SESSION_ID,
      proposal: parseRequirementPlanProposal(outsideBasisProposal),
      contract,
    })).toThrow(RequirementPlanEvidencePayloadError);

    const stalePredecessorProposal: any = proposalFixture();
    stalePredecessorProposal.expected_predecessor_confirmation_id = "9".repeat(64);
    expect(() => parseRequirementPlanProposalReview(structuredClone(review), {
      sessionId: SESSION_ID,
      proposal: parseRequirementPlanProposal(stalePredecessorProposal),
      contract,
    })).toThrow(RequirementPlanEvidencePayloadError);
  });
});
