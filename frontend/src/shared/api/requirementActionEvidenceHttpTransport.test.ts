import { describe, expect, it, vi } from "vitest";
import type {
  RequirementActionEvidenceContract,
  RequirementActionEvidencePreview,
  RequirementActionProposal,
} from "./contracts";
import { createHttpTransport } from "./httpTransport";
import {
  REQUIREMENT_ACTION_DECISION_CONFIRMATION,
  REQUIREMENT_ACTION_FILE_JSON_SCHEMA,
  REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
  REQUIREMENT_ACTION_MEDIA_TYPE,
  REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
} from "./requirementActionEvidenceContract";

const SESSION = "1".repeat(64);
const RUN = "2".repeat(64);
const WINDOW = "3".repeat(64);
const PLAN_CONFIRMATION = "4".repeat(64);
const PLAN_FINGERPRINT = "5".repeat(64);
const MANIFEST = "6".repeat(64);
const PROPOSAL = "7".repeat(64);
const REQUIREMENT = "8".repeat(64);
const ACTION = "9".repeat(64);
const DIGEST = "a".repeat(64);
const USER_PRESENCE_TOKEN = "u".repeat(48);

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
const candidate = {
  candidate_index: 0,
  action_id: ACTION,
  source_reference_id: "b".repeat(64),
  sequence: 1,
  event_kind: "tool_end" as const,
  tool_category: "test" as const,
  occurred_at: "2040-01-01T00:00:00.000001Z",
  duration_ms: 11,
  family: "tool" as const,
  state: "completed" as const,
};
const requirement = {
  requirement_index: 0,
  requirement_id: REQUIREMENT,
  coordinate: { message_sequence: 1, clause_index: 0 },
};

function contract(): RequirementActionEvidenceContract {
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
      actions: [candidate],
      manifest_fingerprint: MANIFEST,
      schema_version: "requirement-action-candidate-manifest-v1",
      local_only: true,
      content_persisted: false,
    },
    requirements: [requirement],
    expected_predecessor_confirmation_id: null,
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
    import_confirmation: REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
    file_json_schema_sha256: "e25e6c1902cc2c7c1f0bdf138c4ac383c0b858e5516cceb05d9be89b6e46c500",
    file_json_schema: structuredClone(REQUIREMENT_ACTION_FILE_JSON_SCHEMA),
  };
}

function preview(): RequirementActionEvidencePreview {
  return {
    payload_sha256: DIGEST,
    session_id: SESSION,
    expected_source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    expected_predecessor_confirmation_id: null,
    requirement_count: 1,
    candidate_count: 1,
    linked_requirement_count: 1,
    unlinked_requirement_count: 0,
    link_count: 1,
    expires_at: "2040-01-01T01:00:00.000001Z",
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

function proposal(id = PROPOSAL, createdAt = "2040-01-01T00:00:00.000001Z", confirmed = false): RequirementActionProposal {
  return {
    proposal_id: id,
    session_id: SESSION,
    source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    candidate_provenance: provenance,
    candidate_extraction_complete: true,
    candidate_enumeration_complete: true,
    expected_predecessor_confirmation_id: null,
    payload_sha256: DIGEST,
    producer_receipt: {
      kind: "local_coding_agent",
      claim_fingerprint: "c".repeat(64),
      authority: "untrusted_provenance_claim_commitment",
      raw_claim_persisted: false,
    },
    review_rubric_version: "requirement-action-review-rubric-v2",
    requirements: [requirement],
    candidates: [candidate],
    links: [{ requirement_id: REQUIREMENT, action_ids: [ACTION] }],
    created_at: createdAt,
    schema_version: "requirement-action-evidence-v1",
    policy_version: "reviewed-requirement-action-v1",
    status: confirmed ? "confirmed" : "proposed",
    decision_id: confirmed ? "d".repeat(64) : null,
    decision: confirmed ? "confirm" : null,
    decided_at: confirmed ? "2040-01-01T00:01:00Z" : null,
    confirmation_authority: confirmed ? "owned_native_user_presence" : null,
    local_only: true,
    content_persisted: false,
  };
}

function review() {
  return {
    proposal_id: PROPOSAL,
    session_id: SESSION,
    source_run_id: RUN,
    source_window_fingerprint: WINDOW,
    review_receipt_id: "e".repeat(64),
    payload_sha256: DIGEST,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    reviewed_graph_fingerprint: "f".repeat(64),
    reviewed_candidate_set_fingerprint: "0".repeat(64),
    reviewed_descriptor_set_fingerprint: "12".repeat(32),
    review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1",
    requirements: [{
      requirement_id: REQUIREMENT,
      coordinate: requirement.coordinate,
      text: "Verify the synthetic artifact.",
      linked_action_ids: [ACTION],
    }],
    candidates: [candidate],
    candidate_memberships: [{
      candidate,
      candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1",
      candidate_metadata_fingerprint: "13".repeat(32),
      descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1",
      tool_name: "synthetic.test",
      invocation_preview: "{\"suite\":\"example\"}",
      result_or_effect_preview: "{\"status\":\"passed\"}",
      invocation_truncated: false,
      result_or_effect_truncated: false,
      redactor_version: "synthetic-redactor-v1",
      linked_requirement_ids: [REQUIREMENT],
    }],
    review_context_expires_at: "2040-01-01T02:00:00Z",
    review_receipt_expires_at: "2040-01-01T00:05:00Z",
    all_requirements_and_candidates_displayed: true,
    raw_text_persisted: false,
    local_only: true,
  };
}

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

describe("requirement-action HTTP transport", () => {
  it("uses exact private vendor preview/import boundaries and validates their bindings", async () => {
    const bytes = new TextEncoder().encode("{}").buffer;
    const imported = {
      payload_sha256: DIGEST,
      proposal: proposal(),
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
      raw_producer_claim_persisted: false,
    };
    const page = {
      session_id: SESSION,
      proposals: [proposal()],
      limit: 200,
      offset: 0,
      total: 1,
      snapshot: {
        snapshot_id: "f".repeat(64), total: 1, decision_count: 0,
        high_water_created_at: proposal().created_at, high_water_proposal_id: PROPOSAL,
      },
      next_offset: null,
      complete: true,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(contract(), true))
      .mockResolvedValueOnce(json(preview(), true))
      .mockResolvedValueOnce(json(imported, true))
      .mockResolvedValueOnce(json(page, true));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getRequirementActionEvidenceContract!(SESSION)).resolves.toEqual(contract());
    await expect(transport.previewRequirementActionEvidence!(SESSION, bytes)).resolves.toEqual(preview());
    await expect(transport.importRequirementActionEvidence!(
      SESSION, bytes, preview(), REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
      "requirement-action-import-example",
    )).resolves.toEqual(imported);
    await expect(transport.listRequirementActionProposals!(SESSION)).resolves.toMatchObject({
      proposals: [proposal()], total: 1, complete: true,
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/auth/session",
      `/v1/sessions/${SESSION}/requirement-action-evidence/contract`,
      `/v1/sessions/${SESSION}/requirement-action-evidence/preview`,
      `/v1/sessions/${SESSION}/requirement-action-evidence/import`,
      `/v1/sessions/${SESSION}/requirement-action-evidence/proposal-page?limit=200&offset=0`,
    ]);
    expect((fetchMock.mock.calls[3][1] as RequestInit).headers).toEqual(expect.objectContaining({
      "Content-Type": REQUIREMENT_ACTION_MEDIA_TYPE,
      "X-Requirement-Action-Payload-SHA256": DIGEST,
      "X-Requirement-Action-Confirmation": REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
      "Idempotency-Key": "requirement-action-import-example",
    }));
    expect((fetchMock.mock.calls[3][1] as RequestInit).body).toBe(bytes);
  });

  it("rejects drifted advertised schema and proposal-to-contract provenance at the HTTP boundary", async () => {
    const invalidContract = contract();
    invalidContract.file_json_schema = {};
    const contractFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(invalidContract, true));
    const contractTransport = createHttpTransport({
      fetch: contractFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(contractTransport.getRequirementActionEvidenceContract!(SESSION))
      .rejects.toMatchObject({ status: 200 });

    const driftedProposal = structuredClone(proposal());
    driftedProposal.candidate_provenance.adapter_version = "drifted-adapter-v2";
    const approve = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const reviewFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(review(), true));
    const reviewTransport = createHttpTransport({
      fetch: reviewFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    await expect(reviewTransport.reviewRequirementActionProposal!(
      SESSION,
      driftedProposal,
      contract(),
      {
        expected_source_run_id: RUN,
        confirmation: REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
      },
    )).rejects.toMatchObject({ status: 200 });
    expect(approve).toHaveBeenCalledTimes(1);
  });

  it("requires native user presence for both full review and decision and echoes exact receipt fields", async () => {
    const candidateReview = review();
    const reviewRequest = {
      expected_source_run_id: RUN,
      confirmation: REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
    } as const;
    const decision = {
      expected_source_run_id: RUN,
      decision: "confirm",
      confirmation: REQUIREMENT_ACTION_DECISION_CONFIRMATION,
      review_receipt_id: candidateReview.review_receipt_id,
      reviewed_graph_fingerprint: candidateReview.reviewed_graph_fingerprint,
      candidate_manifest_fingerprint: candidateReview.candidate_manifest_fingerprint,
      reviewed_candidate_set_fingerprint: candidateReview.reviewed_candidate_set_fingerprint,
      reviewed_descriptor_set_fingerprint: candidateReview.reviewed_descriptor_set_fingerprint,
      complete_review_acknowledged: true,
      all_requirements_and_candidates_acknowledged: true,
      all_linked_action_semantics_reviewed: true,
    } as const;
    const approve = vi.fn().mockResolvedValue(USER_PRESENCE_TOKEN);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(candidateReview, true))
      .mockResolvedValueOnce(json({ proposal: proposal(PROPOSAL, proposal().created_at, true), applied: true }, true));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
      userPresenceApproval: approve,
    });
    await expect(transport.reviewRequirementActionProposal!(
      SESSION, proposal(), contract(), reviewRequest,
    )).resolves.toEqual(candidateReview);
    await expect(transport.decideRequirementActionProposal!(
      SESSION, PROPOSAL, decision, "requirement-action-decision-example",
    )).resolves.toMatchObject({ proposal: { status: "confirmed" }, applied: true });
    const reviewPath = `/v1/sessions/${SESSION}/requirement-action-evidence/proposals/${PROPOSAL}/review`;
    const decisionPath = `/v1/sessions/${SESSION}/requirement-action-evidence/proposals/${PROPOSAL}/decision`;
    expect(approve).toHaveBeenNthCalledWith(1, { method: "POST", path: reviewPath, bodySha256: expect.stringMatching(/^[0-9a-f]{64}$/) });
    expect(approve).toHaveBeenNthCalledWith(2, { method: "POST", path: decisionPath, bodySha256: expect.stringMatching(/^[0-9a-f]{64}$/) });
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).toEqual(expect.objectContaining({
      "X-Prompt-Enhancer-User-Presence": USER_PRESENCE_TOKEN,
      "Idempotency-Key": "requirement-action-decision-example",
    }));
    expect((fetchMock.mock.calls[2][1] as RequestInit).body).toBe(JSON.stringify(decision));
  });

  it("fails closed before review when the advertised native bridge is unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(json(auth));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.reviewRequirementActionProposal!(
      SESSION,
      proposal(),
      contract(),
      {
        expected_source_run_id: RUN,
        confirmation: REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
      },
    )).rejects.toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("carries the exact signed high-water snapshot with full UTC microseconds and rejects drift", async () => {
    const second = proposal("f".repeat(64), "2040-01-01T00:00:00.000010+00:00");
    const stable = {
      snapshot_id: "0".repeat(64), total: 2, decision_count: 0,
      high_water_created_at: second.created_at, high_water_proposal_id: second.proposal_id,
    };
    const firstPage = {
      session_id: SESSION, proposals: [proposal()], limit: 200, offset: 0, total: 2,
      snapshot: stable, next_offset: 1, complete: false,
    };
    const secondPage = { ...firstPage, proposals: [second], offset: 1, next_offset: null, complete: true };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(firstPage, true))
      .mockResolvedValueOnce(json(secondPage, true));
    const transport = createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(transport.listRequirementActionProposals!(SESSION)).resolves.toMatchObject({ total: 2, complete: true });
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/sessions/${SESSION}/requirement-action-evidence/proposal-page?limit=200&offset=1`
      + `&snapshot_id=${stable.snapshot_id}&snapshot_total=2&snapshot_decision_count=0`
      + `&snapshot_high_water_created_at=${encodeURIComponent(stable.high_water_created_at)}`
      + `&snapshot_high_water_proposal_id=${stable.high_water_proposal_id}`,
    );

    const drifted = { ...secondPage, snapshot: { ...stable, decision_count: 1 } };
    const badFetch = vi.fn()
      .mockResolvedValueOnce(json(auth))
      .mockResolvedValueOnce(json(firstPage, true))
      .mockResolvedValueOnce(json(drifted, true));
    const bad = createHttpTransport({ fetch: badFetch as unknown as typeof fetch, origin: "http://127.0.0.1:4173" });
    await expect(bad.listRequirementActionProposals!(SESSION)).rejects.toMatchObject({ status: 200 });
  });
});
