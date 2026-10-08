import { describe, expect, it, vi } from "vitest";
import type {
  RequirementPlanEvidenceContract,
  RequirementPlanEvidencePreview,
  RequirementPlanProposal,
} from "./contracts";
import { createHttpTransport } from "./httpTransport";
import {
  REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES,
  REQUIREMENT_PLAN_FILE_JSON_SCHEMA,
  REQUIREMENT_PLAN_FILE_SCHEMA_SHA256,
  REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC,
  REQUIREMENT_PLAN_REVIEW_RUBRIC,
  REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
  REQUIREMENT_PLAN_MEDIA_TYPE,
} from "./requirementPlanEvidenceContract";

const SESSION_ID = "a".repeat(64);
const RUN_ID = "b".repeat(64);
const WINDOW_ID = "c".repeat(64);
const PROPOSAL_ID = "d".repeat(64);
const DIGEST = "e".repeat(64);
const USER_PRESENCE_TOKEN = "u".repeat(48);

function json(body: unknown, privateResponse = false): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      ...(privateResponse ? { "Cache-Control": "no-store, private", Pragma: "no-cache" } : {}),
    },
  });
}

const auth = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: true,
  user_presence_confirmation_mode: "native_bridge_bound_token",
};

function contract(): RequirementPlanEvidenceContract {
  return {
    schema_version: "requirement-plan-evidence-file-v1",
    session_id: SESSION_ID,
    expected_source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    registry_version: "all-20-factor-contracts-v2",
    contract_set_fingerprint: "02eac63391eb48351f5c8c197d62897895234e2334d388a530d6e6812a18aa67",
    metric_key: "logic.decomposition_coverage",
    metric_contract_fingerprint: "7a1941086fd7c37510ee04ccba28c4e35added3f0ca7bb933c0d8d066031c6af",
    source_projection_version: "metric-contract-v2-projection-6",
    clause_algorithm: "message-clause-coordinates-en-pl-v1",
    clause_algorithm_spec: {
      ...REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC,
      operation_order: [...REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC.operation_order],
    },
    review_rubric_version: "active-requirement-plan-review-rubric-v1",
    review_rubric: { ...REQUIREMENT_PLAN_REVIEW_RUBRIC },
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
    import_confirmation: REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    file_json_schema_sha256: REQUIREMENT_PLAN_FILE_SCHEMA_SHA256,
    file_json_schema: structuredClone(REQUIREMENT_PLAN_FILE_JSON_SCHEMA),
    source_manifest: {
      session_id: SESSION_ID,
      source_run_id: RUN_ID,
      source_window_fingerprint: WINDOW_ID,
      schema_version: "requirement-plan-source-manifest-v1",
      clause_algorithm: "message-clause-coordinates-en-pl-v1",
      clause_algorithm_spec: {
        ...REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC,
        operation_order: [...REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC.operation_order],
      },
      review_rubric_version: "active-requirement-plan-review-rubric-v1",
      review_rubric: { ...REQUIREMENT_PLAN_REVIEW_RUBRIC },
      messages: [
        { message_sequence: 1, role: "user", kind: "request", clause_count: 1 },
        { message_sequence: 2, role: "agent", kind: "plan", clause_count: 1 },
      ],
      message_count: 2,
      candidate_clause_count: 2,
      manifest_fingerprint: "8".repeat(64),
      review_context_expires_at: "2040-01-01T02:00:00Z",
      contains_text: false,
      local_only: true,
      content_persisted: false,
    },
    file_constraint_contract_version: "requirement-plan-file-constraints-v1",
    file_constraint_codes: [...REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES],
  };
}

function preview(): RequirementPlanEvidencePreview {
  return {
    payload_sha256: DIGEST,
    session_id: SESSION_ID,
    expected_source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    reviewed_user_clause_count: 1,
    active_requirement_count: 1,
    excluded_user_clause_count: 0,
    plan_item_count: 1,
    linked_active_requirement_count: 1,
    not_linked_active_requirement_count: 0,
    pending_active_requirement_count: 0,
    link_count: 1,
    expires_at: "2040-01-01T01:00:00Z",
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

function proposal(confirmed = false): RequirementPlanProposal {
  return {
    proposal_id: PROPOSAL_ID,
    session_id: SESSION_ID,
    source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    expected_predecessor_confirmation_id: null,
    payload_sha256: DIGEST,
    producer_receipt: {
      kind: "local_coding_agent",
      claim_fingerprint: "9".repeat(64),
      authority: "untrusted_provenance_claim_commitment",
      raw_claim_persisted: false,
    },
    review_rubric_version: "active-requirement-plan-review-rubric-v1",
    requirements: [{
      coordinate: { message_sequence: 1, clause_index: 0 },
      disposition: "linked",
      plan_indexes: [0],
    }],
    excluded_user_clauses: [],
    plan_items: [{ message_sequence: 2, clause_index: 0 }],
    created_at: "2040-01-01T00:00:00Z",
    schema_version: "requirement-plan-evidence-v1",
    policy_version: "reviewed-requirement-plan-v1",
    status: confirmed ? "confirmed" : "proposed",
    decision_id: confirmed ? "f".repeat(64) : null,
    decision: confirmed ? "confirm" : null,
    decided_at: confirmed ? "2040-01-01T00:01:00Z" : null,
    confirmation_authority: confirmed ? "owned_native_user_presence" : null,
    local_only: true,
    content_persisted: false,
  };
}

function review() {
  return {
    proposal_id: PROPOSAL_ID,
    session_id: SESSION_ID,
    source_run_id: RUN_ID,
    source_window_fingerprint: WINDOW_ID,
    review_receipt_id: "7".repeat(64),
    payload_sha256: DIGEST,
    manifest_fingerprint: "8".repeat(64),
    reviewed_graph_fingerprint: "6".repeat(64),
    reviewed_candidate_set_fingerprint: "5".repeat(64),
    candidate_clauses: [
      {
        message_sequence: 1, clause_index: 0, role: "user", kind: "request",
        text: "Create the synthetic artifact.", candidate_kind: "user_clause",
        included_in_proposal: true, classification: "active_requirement",
        exclusion_reason: null, basis_coordinate: null, disposition: "linked",
        linked_plan_coordinates: [{ message_sequence: 2, clause_index: 0 }],
      },
      {
        message_sequence: 2, clause_index: 0, role: "agent", kind: "plan",
        text: "Create the artifact.", candidate_kind: "plan", included_in_proposal: true,
        classification: null, exclusion_reason: null, basis_coordinate: null,
        disposition: null, linked_plan_coordinates: [],
      },
    ],
    review_context_expires_at: "2040-01-01T02:00:00Z",
    review_receipt_expires_at: "2040-01-01T00:05:00Z",
    all_coordinates_structurally_valid: true,
    raw_text_persisted: false,
    local_only: true,
  };
}

describe("requirement-plan HTTP transport", () => {
  it("uses the exact private media/header boundary and validates every response", async () => {
    const bytes = new TextEncoder().encode("{}").buffer;
    const candidatePreview = preview();
    const imported = {
      payload_sha256: DIGEST,
      proposal: proposal(),
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(contract(), true))
      .mockResolvedValueOnce(json(candidatePreview, true))
      .mockResolvedValueOnce(json(imported, true))
      .mockResolvedValueOnce(json({
        session_id: SESSION_ID,
        proposals: [proposal()],
        limit: 200,
        offset: 0,
        total: 1,
        snapshot: {
          snapshot_id: "8".repeat(64),
          total: 1,
          decision_count: 0,
          high_water_created_at: "2040-01-01T00:00:00Z",
          high_water_proposal_id: PROPOSAL_ID,
        },
        next_offset: null,
        complete: true,
      }, true));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getRequirementPlanEvidenceContract!(SESSION_ID)).resolves.toEqual(contract());
    await expect(transport.previewRequirementPlanEvidence!(SESSION_ID, bytes)).resolves.toEqual(candidatePreview);
    await expect(transport.importRequirementPlanEvidence!(
      SESSION_ID,
      bytes,
      candidatePreview,
      REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
      "requirement-plan-import-example",
    )).resolves.toEqual(imported);
    await expect(transport.listRequirementPlanProposals!(SESSION_ID)).resolves.toMatchObject({
      proposals: [proposal()],
      total: 1,
      complete: true,
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/auth/session",
      `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/contract`,
      `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/preview`,
      `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/import`,
      `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/proposal-page?limit=200&offset=0`,
    ]);
    for (const index of [2, 3]) {
      expect((fetchMock.mock.calls[index][1] as RequestInit).headers).toEqual(expect.objectContaining({
        "Content-Type": REQUIREMENT_PLAN_MEDIA_TYPE,
        "X-Prompt-Enhancer-CSRF": auth.csrf_token,
      }));
      expect((fetchMock.mock.calls[index][1] as RequestInit).body).toBe(bytes);
    }
    expect((fetchMock.mock.calls[3][1] as RequestInit).headers).toEqual(expect.objectContaining({
      "X-Requirement-Plan-Payload-SHA256": DIGEST,
      "X-Requirement-Plan-Confirmation": REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
      "Idempotency-Key": "requirement-plan-import-example",
    }));
  });

  it("binds native confirmation to the exact decision path and JSON body", async () => {
    const candidateReview = review();
    const reviewRequest = {
      expected_source_run_id: RUN_ID,
      confirmation: "open_exact_local_requirement_plan_clause_review" as const,
    };
    const decision = {
      expected_source_run_id: RUN_ID,
      decision: "confirm" as const,
      confirmation: "apply_local_user_requirement_plan_evidence_decision" as const,
      review_receipt_id: candidateReview.review_receipt_id,
      manifest_fingerprint: candidateReview.manifest_fingerprint,
      reviewed_graph_fingerprint: candidateReview.reviewed_graph_fingerprint,
      reviewed_candidate_set_fingerprint: candidateReview.reviewed_candidate_set_fingerprint,
      complete_review_acknowledged: true as const,
    };
    const approve = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(candidateReview, true))
      .mockResolvedValueOnce(json({ proposal: proposal(true), applied: true }, true));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    await expect(transport.reviewRequirementPlanProposal!(
      SESSION_ID,
      proposal(),
      contract(),
      reviewRequest,
    )).resolves.toEqual(candidateReview);
    await expect(transport.decideRequirementPlanProposal!(
      SESSION_ID,
      PROPOSAL_ID,
      decision,
      "requirement-plan-decision-example",
    )).resolves.toMatchObject({ proposal: { status: "confirmed" }, applied: true });
    const reviewPath = `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/proposals/${PROPOSAL_ID}/review`;
    const path = `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/proposals/${PROPOSAL_ID}/decision`;
    expect(approve).toHaveBeenNthCalledWith(1, {
      method: "POST",
      path: reviewPath,
      bodySha256: expect.stringMatching(/^[0-9a-f]{64}$/),
    });
    expect(approve).toHaveBeenNthCalledWith(2, {
      method: "POST",
      path,
      bodySha256: expect.stringMatching(/^[0-9a-f]{64}$/),
    });
    expect((fetchMock.mock.calls[1][1] as RequestInit).body).toBe(JSON.stringify(reviewRequest));
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).toEqual(expect.objectContaining({
      "Content-Type": "application/json",
      "Idempotency-Key": "requirement-plan-decision-example",
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
    }));
    expect((fetchMock.mock.calls[2][1] as RequestInit).body).toBe(JSON.stringify(decision));
  });

  it("propagates every signed high-water snapshot field across pages and rejects drift", async () => {
    const secondProposal = { ...proposal(), proposal_id: "f".repeat(64) };
    const pageSnapshot = {
      snapshot_id: "2".repeat(64),
      total: 2,
      decision_count: 0,
      high_water_created_at: secondProposal.created_at,
      high_water_proposal_id: secondProposal.proposal_id,
    };
    const firstPage = {
      session_id: SESSION_ID,
      proposals: [proposal()],
      limit: 200,
      offset: 0,
      total: 2,
      snapshot: pageSnapshot,
      next_offset: 1,
      complete: false,
    };
    const secondPage = {
      ...firstPage,
      proposals: [secondProposal],
      offset: 1,
      next_offset: null,
      complete: true,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(firstPage, true))
      .mockResolvedValueOnce(json(secondPage, true));
    const local = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(local.listRequirementPlanProposals!(SESSION_ID)).resolves.toMatchObject({
      proposals: [proposal(), secondProposal],
      total: 2,
      complete: true,
      snapshot: pageSnapshot,
    });
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      `/v1/sessions/${SESSION_ID}/requirement-plan-evidence/proposal-page?limit=200&offset=1`
      + `&snapshot_id=${pageSnapshot.snapshot_id}`
      + "&snapshot_total=2&snapshot_decision_count=0"
      + `&snapshot_high_water_created_at=${encodeURIComponent(pageSnapshot.high_water_created_at)}`
      + `&snapshot_high_water_proposal_id=${pageSnapshot.high_water_proposal_id}`,
    );

    const driftedFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(firstPage, true))
      .mockResolvedValueOnce(json({
        ...secondPage,
        snapshot: { ...pageSnapshot, decision_count: 1 },
      }, true));
    const drifted = createHttpTransport({
      fetch: driftedFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(drifted.listRequirementPlanProposals!(SESSION_ID)).rejects.toMatchObject({
      status: 200,
    });

    for (const invalidSnapshot of [
      { ...pageSnapshot, total: 1, decision_count: 1, high_water_proposal_id: PROPOSAL_ID },
      { ...pageSnapshot, total: 1, high_water_proposal_id: "0".repeat(64) },
    ]) {
      const invalidFetch = vi.fn()
        .mockResolvedValueOnce(json(auth))
        .mockResolvedValueOnce(json({
          session_id: SESSION_ID,
          proposals: [proposal()],
          limit: 200,
          offset: 0,
          total: 1,
          snapshot: invalidSnapshot,
          next_offset: null,
          complete: true,
        }, true));
      const invalid = createHttpTransport({
        fetch: invalidFetch as unknown as typeof fetch,
        origin: "http://127.0.0.1:4173",
      });
      await expect(invalid.listRequirementPlanProposals!(SESSION_ID)).rejects.toMatchObject({
        status: 200,
      });
    }
  });

  it("orders and binds proposal snapshots at full UTC microsecond precision", async () => {
    const earlier = {
      ...proposal(),
      proposal_id: "f".repeat(64),
      created_at: "2040-01-01T00:00:00.000001Z",
    };
    const later = {
      ...proposal(),
      proposal_id: "e".repeat(64),
      created_at: "2040-01-01T00:00:00.000002Z",
    };
    const exactPage = {
      session_id: SESSION_ID,
      proposals: [earlier, later],
      limit: 200,
      offset: 0,
      total: 2,
      snapshot: {
        snapshot_id: "2".repeat(64),
        total: 2,
        decision_count: 0,
        high_water_created_at: later.created_at,
        high_water_proposal_id: later.proposal_id,
      },
      next_offset: null,
      complete: true,
    };
    const exactFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(exactPage, true));
    const exact = createHttpTransport({
      fetch: exactFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(exact.listRequirementPlanProposals!(SESSION_ID)).resolves.toMatchObject({
      proposals: [earlier, later],
      snapshot: exactPage.snapshot,
    });

    const driftedPage = {
      ...exactPage,
      snapshot: {
        ...exactPage.snapshot,
        high_water_created_at: "2040-01-01T00:00:00.000003Z",
      },
    };
    const driftedFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(driftedPage, true));
    const drifted = createHttpTransport({
      fetch: driftedFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(drifted.listRequirementPlanProposals!(SESSION_ID)).rejects.toMatchObject({
      status: 200,
    });
  });
});
