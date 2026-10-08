import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect, useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  PromptEnhancerTransport,
  RequirementPlanEvidenceContract,
  RequirementPlanEvidencePreview,
  RequirementPlanProposal,
  RequirementPlanProposalReview,
} from "../../shared/api/contracts";
import {
  REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC,
  REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES,
  REQUIREMENT_PLAN_FILE_JSON_SCHEMA,
  REQUIREMENT_PLAN_FILE_SCHEMA_SHA256,
  REQUIREMENT_PLAN_REVIEW_RUBRIC,
} from "../../shared/api/requirementPlanEvidenceContract";
import { RequirementPlanEvidencePanel } from "./RequirementPlanEvidencePanel";

const SESSION_ID = "a".repeat(64);
const RUN_ID = "b".repeat(64);
const WINDOW_ID = "c".repeat(64);
const PROPOSAL_ID = "d".repeat(64);
const PAYLOAD_ID = "e".repeat(64);
const REVIEW_RECEIPT_ID = "f".repeat(64);
const MANIFEST_ID = "8".repeat(64);
const GRAPH_ID = "7".repeat(64);
const CANDIDATE_SET_ID = "6".repeat(64);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function clauseAlgorithmSpec(): RequirementPlanEvidenceContract["clause_algorithm_spec"] {
  return structuredClone(REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC) as RequirementPlanEvidenceContract["clause_algorithm_spec"];
}

function contract(
  runId = RUN_ID,
  projection: RequirementPlanEvidenceContract["source_projection_version"] = "metric-contract-v2-projection-6",
  windowId = WINDOW_ID,
): RequirementPlanEvidenceContract {
  return {
    schema_version: "requirement-plan-evidence-file-v1",
    session_id: SESSION_ID,
    expected_source_run_id: runId,
    source_window_fingerprint: windowId,
    expected_predecessor_confirmation_id: null,
    registry_version: "all-20-factor-contracts-v2",
    contract_set_fingerprint: "02eac63391eb48351f5c8c197d62897895234e2334d388a530d6e6812a18aa67",
    metric_key: "logic.decomposition_coverage",
    metric_contract_fingerprint: "7a1941086fd7c37510ee04ccba28c4e35added3f0ca7bb933c0d8d066031c6af",
    source_projection_version: projection,
    clause_algorithm: "message-clause-coordinates-en-pl-v1",
    clause_algorithm_spec: clauseAlgorithmSpec(),
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
      source_run_id: runId,
      source_window_fingerprint: windowId,
      schema_version: "requirement-plan-source-manifest-v1",
      clause_algorithm: "message-clause-coordinates-en-pl-v1",
      clause_algorithm_spec: clauseAlgorithmSpec(),
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
      manifest_fingerprint: MANIFEST_ID,
      review_context_expires_at: "2042-01-01T01:00:00Z",
      contains_text: false,
      local_only: true,
      content_persisted: false,
    },
    file_constraint_contract_version: "requirement-plan-file-constraints-v1",
    file_constraint_codes: [...REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES],
  };
}

function preview(runId = RUN_ID, windowId = WINDOW_ID): RequirementPlanEvidencePreview {
  return {
    payload_sha256: PAYLOAD_ID,
    session_id: SESSION_ID,
    expected_source_run_id: runId,
    source_window_fingerprint: windowId,
    expected_predecessor_confirmation_id: null,
    reviewed_user_clause_count: 3,
    active_requirement_count: 2,
    excluded_user_clause_count: 1,
    plan_item_count: 1,
    linked_active_requirement_count: 1,
    not_linked_active_requirement_count: 0,
    pending_active_requirement_count: 1,
    link_count: 1,
    expires_at: "2042-01-01T00:45:00Z",
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

function proposal(
  runId = RUN_ID,
  status: RequirementPlanProposal["status"] = "proposed",
  proposalId = PROPOSAL_ID,
  windowId = WINDOW_ID,
): RequirementPlanProposal {
  const decided = status !== "proposed";
  return {
    proposal_id: proposalId,
    session_id: SESSION_ID,
    source_run_id: runId,
    source_window_fingerprint: windowId,
    expected_predecessor_confirmation_id: null,
    payload_sha256: PAYLOAD_ID,
    producer_receipt: {
      kind: "local_coding_agent",
      claim_fingerprint: "5".repeat(64),
      authority: "untrusted_provenance_claim_commitment",
      raw_claim_persisted: false,
    },
    review_rubric_version: "active-requirement-plan-review-rubric-v1",
    requirements: [
      { coordinate: { message_sequence: 1, clause_index: 0 }, disposition: "linked", plan_indexes: [0] },
      { coordinate: { message_sequence: 3, clause_index: 0 }, disposition: "pending", plan_indexes: [] },
    ],
    excluded_user_clauses: [{
      coordinate: { message_sequence: 1, clause_index: 1 },
      reason: "duplicate",
      basis_coordinate: { message_sequence: 1, clause_index: 0 },
    }],
    plan_items: [{ message_sequence: 2, clause_index: 0 }],
    created_at: "2042-01-01T00:00:00Z",
    schema_version: "requirement-plan-evidence-v1",
    policy_version: "reviewed-requirement-plan-v1",
    status,
    decision_id: decided ? "4".repeat(64) : null,
    decision: status === "confirmed" ? "confirm" : status === "rejected" ? "reject" : null,
    decided_at: decided ? "2042-01-01T00:30:00Z" : null,
    confirmation_authority: decided ? "owned_native_user_presence" : null,
    local_only: true,
    content_persisted: false,
  };
}

function review(
  runId = RUN_ID,
  proposalId = PROPOSAL_ID,
  windowId = WINDOW_ID,
  receiptExpiresAt = "2042-01-01T00:05:00Z",
): RequirementPlanProposalReview {
  return {
    proposal_id: proposalId,
    session_id: SESSION_ID,
    source_run_id: runId,
    source_window_fingerprint: windowId,
    review_receipt_id: REVIEW_RECEIPT_ID,
    payload_sha256: PAYLOAD_ID,
    manifest_fingerprint: MANIFEST_ID,
    reviewed_graph_fingerprint: GRAPH_ID,
    reviewed_candidate_set_fingerprint: CANDIDATE_SET_ID,
    candidate_clauses: [
      {
        message_sequence: 1, clause_index: 0, role: "user", kind: "request",
        text: "Create the synthetic artifact.", candidate_kind: "user_clause",
        included_in_proposal: true, classification: "active_requirement",
        exclusion_reason: null, basis_coordinate: null, disposition: "linked",
        linked_plan_coordinates: [{ message_sequence: 2, clause_index: 0 }],
      },
      {
        message_sequence: 1, clause_index: 1, role: "user", kind: "request",
        text: "Create the synthetic artifact a second time.", candidate_kind: "user_clause",
        included_in_proposal: true,
        classification: "excluded_from_active_requirement_denominator",
        exclusion_reason: "duplicate",
        basis_coordinate: { message_sequence: 1, clause_index: 0 },
        disposition: null, linked_plan_coordinates: [],
      },
      {
        message_sequence: 2, clause_index: 0, role: "agent", kind: "plan",
        text: "Create the artifact in one step.", candidate_kind: "plan",
        included_in_proposal: true, classification: null, exclusion_reason: null,
        basis_coordinate: null, disposition: null, linked_plan_coordinates: [],
      },
      {
        message_sequence: 3, clause_index: 0, role: "user", kind: "feedback",
        text: "Keep verification pending.", candidate_kind: "user_clause",
        included_in_proposal: true, classification: "active_requirement",
        exclusion_reason: null, basis_coordinate: null, disposition: "pending",
        linked_plan_coordinates: [],
      },
      {
        message_sequence: 4, clause_index: 0, role: "agent", kind: "plan",
        text: "Run an optional follow-up verification.", candidate_kind: "plan",
        included_in_proposal: false, classification: null, exclusion_reason: null,
        basis_coordinate: null, disposition: null, linked_plan_coordinates: [],
      },
    ],
    review_context_expires_at: "2042-01-01T01:00:00Z",
    review_receipt_expires_at: receiptExpiresAt,
    all_coordinates_structurally_valid: true,
    raw_text_persisted: false,
    local_only: true,
  };
}

function snapshot(initial: RequirementPlanProposal[]) {
  return {
    snapshot_id: "3".repeat(64),
    total: initial.length,
    decision_count: initial.filter((item) => item.status !== "proposed").length,
    high_water_created_at: initial.at(-1)?.created_at ?? null,
    high_water_proposal_id: initial.at(-1)?.proposal_id ?? null,
  };
}

function transport(initial: RequirementPlanProposal[] = []): PromptEnhancerTransport {
  return {
    getRequirementPlanEvidenceContract: vi.fn().mockResolvedValue(contract()),
    listRequirementPlanProposals: vi.fn().mockResolvedValue({
      session_id: SESSION_ID,
      proposals: initial,
      total: initial.length,
      complete: true,
      snapshot: snapshot(initial),
    }),
    previewRequirementPlanEvidence: vi.fn().mockResolvedValue(preview()),
    importRequirementPlanEvidence: vi.fn().mockResolvedValue({
      payload_sha256: PAYLOAD_ID,
      proposal: proposal(),
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
    }),
    reviewRequirementPlanProposal: vi.fn().mockResolvedValue(review()),
    decideRequirementPlanProposal: vi.fn().mockImplementation(async (_session, _proposal, request) => ({
      proposal: proposal(RUN_ID, request.decision === "confirm" ? "confirmed" : "rejected"),
      applied: true,
    })),
    getUserPresenceCapability: vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    }),
  } as unknown as PromptEnhancerTransport;
}

function chooseSyntheticFile(): void {
  chooseFile("{}", "example.json", "application/json");
}

function chooseFile(contents: string, name: string, type: string): void {
  const file = new File([contents], name, { type });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(contents).buffer,
  });
  fireEvent.change(screen.getByLabelText("Choose canonical requirement-plan evidence file"), {
    target: { files: [file] },
  });
}

function captureReactClick(button: HTMLElement): () => void {
  const propsKey = Object.keys(button).find((key) => key.startsWith("__reactProps$"));
  if (propsKey === undefined) throw new Error("Synthetic test could not capture the React click handler");
  const props = (button as unknown as Record<string, { onClick?: (event: unknown) => void }>)[propsKey];
  if (props?.onClick === undefined) throw new Error("Synthetic test button has no React click handler");
  const onClick = props.onClick;
  return () => onClick({ currentTarget: button });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("RequirementPlanEvidencePanel", () => {
  it("blocks an already-rendered A import during a same-binding transport B layout commit", async () => {
    const transportA = transport();
    const transportB = transport();

    function Harness() {
      const [useB, setUseB] = useState(false);
      const host = useRef<HTMLDivElement>(null);
      useLayoutEffect(() => {
        if (!useB) return;
        const staleImport = [...(host.current?.querySelectorAll("button") ?? [])]
          .find((button) => button.textContent === "Import as unconfirmed");
        staleImport?.click();
      }, [useB]);
      return (
        <>
          <button onClick={() => setUseB(true)} type="button">Switch transport</button>
          <div ref={host}>
            <RequirementPlanEvidencePanel
              compact={false}
              sessionId={SESSION_ID}
              sourceProjectionVersion="metric-contract-v2-projection-6"
              sourceRunId={RUN_ID}
              transport={useB ? transportB : transportA}
            />
          </div>
        </>
      );
    }

    render(<Harness />);
    await screen.findByText(/bound to sealed run/i);
    chooseSyntheticFile();
    expect(await screen.findByRole("button", { name: "Import as unconfirmed" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Switch transport" }));

    expect(transportB.importRequirementPlanEvidence).not.toHaveBeenCalled();
    expect(transportA.importRequirementPlanEvidence).not.toHaveBeenCalled();
  });

  it("keeps the compact surface read-only and never exposes ephemeral clause text", async () => {
    const local = transport([proposal()]);
    render(
      <RequirementPlanEvidencePanel compact sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    expect(await screen.findByText("1 proposal awaiting review")).toBeVisible();
    expect(screen.getByRole("region", { name: "Reviewed requirement-to-plan evidence" })).toBeVisible();
    expect(screen.getByText(/open the full dashboard/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /review|confirm|reject/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
    expect(local.reviewRequirementPlanProposal).not.toHaveBeenCalled();
  });

  it("reviews every active, excluded, included, and omitted clause before receipt-bound confirmation", async () => {
    const local = transport();
    const changed = vi.fn();
    render(
      <RequirementPlanEvidencePanel
        compact={false}
        onEvidenceChanged={changed}
        sessionId={SESSION_ID}
        sourceProjectionVersion="metric-contract-v2-projection-6"
        sourceRunId={RUN_ID}
        transport={local}
      />,
    );
    expect(await screen.findByText(/bound to sealed run/i)).toBeVisible();
    chooseSyntheticFile();
    expect(await screen.findByText(/producer metadata is an ephemeral untrusted preview claim/i)).toBeVisible();
    expect(screen.queryByText(/example-agent|example-model/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Import as unconfirmed" }));
    const open = await screen.findByRole("button", { name: "Open exact local clause review" });
    expect(screen.getByText(/opaque commitment 55555555/i)).toBeVisible();
    expect(screen.queryByText(/example-agent|example-model/i)).not.toBeInTheDocument();
    fireEvent.click(open);

    expect(await screen.findByText("Create the synthetic artifact.")).toBeVisible();
    expect(screen.getByText("Create the synthetic artifact a second time.")).toBeVisible();
    expect(screen.getByText("Run an optional follow-up verification.")).toBeVisible();
    expect(screen.getByText(/excluded from active-requirement denominator/i)).toBeVisible();
    expect(screen.getByText("duplicate")).toBeVisible();
    expect(screen.getByText(/message 1, clause 0 — “Create the synthetic artifact.”/i)).toBeVisible();
    expect(screen.getByText(/omitted plan clause/i)).toBeVisible();
    expect(screen.getAllByText(/active requirement — included in the denominator/i)).toHaveLength(2);
    expect(screen.getAllByText(/plan links/i)[0]?.parentElement).toHaveTextContent("message 2, clause 0");

    expect(screen.getByRole("button", { name: "Confirm evidence" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I reviewed every displayed user and PLAN clause/i));
    expect(screen.getByRole("button", { name: "Confirm evidence" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm evidence" }));
    expect(screen.getByRole("group", { name: "Confirm requirement-plan proposal" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply native confirmation" }));

    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(local.reviewRequirementPlanProposal).toHaveBeenCalledWith(
      SESSION_ID,
      expect.objectContaining({ proposal_id: PROPOSAL_ID, source_run_id: RUN_ID }),
      expect.objectContaining({ expected_source_run_id: RUN_ID, source_window_fingerprint: WINDOW_ID }),
      {
        expected_source_run_id: RUN_ID,
        confirmation: "open_exact_local_requirement_plan_clause_review",
      },
      expect.anything(),
    );
    expect(local.decideRequirementPlanProposal).toHaveBeenCalledWith(
      SESSION_ID,
      PROPOSAL_ID,
      {
        expected_source_run_id: RUN_ID,
        decision: "confirm",
        confirmation: "apply_local_user_requirement_plan_evidence_decision",
        review_receipt_id: REVIEW_RECEIPT_ID,
        manifest_fingerprint: MANIFEST_ID,
        reviewed_graph_fingerprint: GRAPH_ID,
        reviewed_candidate_set_fingerprint: CANDIDATE_SET_ID,
        complete_review_acknowledged: true,
      },
      expect.any(String),
      expect.anything(),
    );
  });

  it("fails closed when native user presence is unavailable", async () => {
    const local = transport([proposal()]);
    local.getUserPresenceCapability = vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: false,
      mode: "unavailable",
    });
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    expect(await screen.findByText(/proposals remain unconfirmed/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open exact local clause review" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(local.reviewRequirementPlanProposal).not.toHaveBeenCalled();
    expect(local.decideRequirementPlanProposal).not.toHaveBeenCalled();
  });

  it("rejects independently without manufacturing a review receipt", async () => {
    const local = transport([proposal()]);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    const reject = await screen.findByRole("button", { name: "Reject" });
    fireEvent.click(reject);
    fireEvent.click(screen.getByRole("button", { name: "Apply native rejection" }));
    await waitFor(() => expect(local.decideRequirementPlanProposal).toHaveBeenCalledWith(
      SESSION_ID,
      PROPOSAL_ID,
      {
        expected_source_run_id: RUN_ID,
        decision: "reject",
        confirmation: "apply_local_user_requirement_plan_evidence_decision",
      },
      expect.any(String),
      expect.anything(),
    ));
    expect(local.reviewRequirementPlanProposal).not.toHaveBeenCalled();
  });

  it("accepts the deliberate r5 bootstrap contract for first r6 evidence", async () => {
    const local = transport();
    local.getRequirementPlanEvidenceContract = vi.fn().mockResolvedValue(
      contract(RUN_ID, "metric-contract-v2-projection-5"),
    );
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-5" sourceRunId={RUN_ID} transport={local} />,
    );
    expect(await screen.findByText(/bound to sealed run/i)).toBeVisible();
    expect(screen.queryByText(/not bound to this exact sealed r5\/r6\/r7 run/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Choose canonical requirement-plan evidence file")).toBeEnabled();
  });

  it("accepts a fresh exact r7 source contract without weakening the native workflow", async () => {
    const local = transport();
    local.getRequirementPlanEvidenceContract = vi.fn().mockResolvedValue(
      contract(RUN_ID, "metric-contract-v2-projection-7"),
    );
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN_ID} transport={local} />,
    );
    expect(await screen.findByText(/bound to sealed run/i)).toBeVisible();
    expect(screen.getByLabelText("Choose canonical requirement-plan evidence file")).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();
  });

  it("fails closed when the selected publication projection and source contract differ", async () => {
    const local = transport();
    local.getRequirementPlanEvidenceContract = vi.fn().mockResolvedValue(
      contract(RUN_ID, "metric-contract-v2-projection-5"),
    );
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/not bound to a current exact sealed/i);
    expect(screen.queryByLabelText("Choose canonical requirement-plan evidence file"))
      .not.toBeInTheDocument();
  });

  it("blocks stale-predecessor review and confirmation while preserving native rejection", async () => {
    const stale = proposal();
    stale.expected_predecessor_confirmation_id = "9".repeat(64);
    const local = transport([stale]);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    const open = await screen.findByRole("button", { name: "Open exact local clause review" });
    expect(open).toBeDisabled();
    expect(screen.getByText(/targets an older confirmation head/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply native rejection" }));
    await waitFor(() => expect(local.decideRequirementPlanProposal).toHaveBeenCalledWith(
      SESSION_ID,
      PROPOSAL_ID,
      expect.objectContaining({ decision: "reject" }),
      expect.any(String),
      expect.anything(),
    ));
    expect(local.reviewRequirementPlanProposal).not.toHaveBeenCalled();
  });

  it("never exposes a delayed run A contract after selection changes to run B", async () => {
    const runB = "9".repeat(64);
    const windowB = "2".repeat(64);
    const proposalB = "1".repeat(64);
    let resolveContractA!: (value: RequirementPlanEvidenceContract) => void;
    const delayedContractA = new Promise<RequirementPlanEvidenceContract>((resolve) => { resolveContractA = resolve; });
    const local = transport([proposal()]);
    local.getRequirementPlanEvidenceContract = vi.fn()
      .mockImplementationOnce(() => delayedContractA)
      .mockResolvedValueOnce(contract(runB, "metric-contract-v2-projection-6", windowB));
    local.listRequirementPlanProposals = vi.fn()
      .mockResolvedValueOnce({ session_id: SESSION_ID, proposals: [proposal()], total: 1, complete: true, snapshot: snapshot([proposal()]) })
      .mockResolvedValueOnce({
        session_id: SESSION_ID,
        proposals: [proposal(runB, "proposed", proposalB, windowB)],
        total: 1,
        complete: true,
        snapshot: snapshot([proposal(runB, "proposed", proposalB, windowB)]),
      });
    const view = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    view.rerender(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={runB} transport={local} />,
    );
    expect(await screen.findByText((_text, element) => (
      element?.tagName === "P" && element.textContent?.includes(`Bound to sealed run ${runB.slice(0, 8)}`) === true
    ))).toBeVisible();
    resolveContractA(contract());
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByText((_text, element) => (
      element?.tagName === "P" && element.textContent?.includes(`Bound to sealed run ${RUN_ID.slice(0, 8)}`) === true
    ))).not.toBeInTheDocument();
    expect(screen.getByText(/Content-free proposal 11111111/i)).toBeVisible();
  });

  it("suppresses a delayed proposal-A review and resets acknowledgement on run A to B", async () => {
    const runB = "9".repeat(64);
    const windowB = "2".repeat(64);
    const proposalB = "1".repeat(64);
    let resolveReviewA!: (value: RequirementPlanProposalReview) => void;
    const delayedReviewA = new Promise<RequirementPlanProposalReview>((resolve) => { resolveReviewA = resolve; });
    const local = transport([proposal()]);
    local.reviewRequirementPlanProposal = vi.fn().mockImplementationOnce(() => delayedReviewA);
    local.getRequirementPlanEvidenceContract = vi.fn()
      .mockResolvedValueOnce(contract())
      .mockResolvedValueOnce(contract(runB, "metric-contract-v2-projection-6", windowB));
    local.listRequirementPlanProposals = vi.fn()
      .mockResolvedValueOnce({ session_id: SESSION_ID, proposals: [proposal()], total: 1, complete: true, snapshot: snapshot([proposal()]) })
      .mockResolvedValueOnce({
        session_id: SESSION_ID,
        proposals: [proposal(runB, "proposed", proposalB, windowB)],
        total: 1,
        complete: true,
        snapshot: snapshot([proposal(runB, "proposed", proposalB, windowB)]),
      });
    const view = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open exact local clause review" }));
    view.rerender(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={runB} transport={local} />,
    );
    expect(await screen.findByText(/Content-free proposal 11111111/i)).toBeVisible();
    resolveReviewA(review());
    await act(async () => { await Promise.resolve(); });
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/I reviewed every displayed user and PLAN clause/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confirm requirement-plan proposal" })).not.toBeInTheDocument();
  });

  it("fails closed before file selection when the exact source review context expired", async () => {
    vi.useFakeTimers({ now: new Date("2042-01-01T02:00:00Z") });
    render(
      <RequirementPlanEvidencePanel
        compact={false}
        sessionId={SESSION_ID}
        sourceProjectionVersion="metric-contract-v2-projection-6"
        sourceRunId={RUN_ID}
        transport={transport([proposal()])}
      />,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole("alert")).toHaveTextContent(/not bound to a current exact sealed/i);
    expect(screen.queryByLabelText("Choose canonical requirement-plan evidence file"))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /review|confirm/i })).not.toBeInTheDocument();
  });

  it("clears ephemeral clauses and acknowledgement when a review refresh fails", async () => {
    const local = transport([proposal()]);
    local.reviewRequirementPlanProposal = vi.fn()
      .mockResolvedValueOnce(review())
      .mockRejectedValueOnce(new Error("synthetic review failure"));
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    const open = await screen.findByRole("button", { name: "Open exact local clause review" });
    fireEvent.click(open);
    expect(await screen.findByText("Create the synthetic artifact.")).toBeVisible();
    fireEvent.click(screen.getByLabelText(/I reviewed every displayed user and PLAN clause/i));
    fireEvent.click(open);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be opened/i);
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/I reviewed every displayed user and PLAN clause/i))
      .not.toBeInTheDocument();
  });

  it("expires an opened review and clears its acknowledgement", async () => {
    vi.useFakeTimers({ now: new Date("2042-01-01T00:00:00Z") });
    const local = transport([proposal()]);
    local.reviewRequirementPlanProposal = vi.fn().mockResolvedValue(
      review(RUN_ID, PROPOSAL_ID, WINDOW_ID, "2042-01-01T00:00:01Z"),
    );
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "Open exact local clause review" }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    fireEvent.click(screen.getByLabelText(/I reviewed every displayed user and PLAN clause/i));
    expect(screen.getByRole("button", { name: "Confirm evidence" })).toBeEnabled();
    await act(async () => { vi.advanceTimersByTime(1_001); });
    expect(screen.getByRole("alert")).toHaveTextContent(/receipt expired/i);
    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/I reviewed every displayed user and PLAN clause/i)).not.toBeInTheDocument();
  });

  it("renders explicit unavailable, loading, empty, confirmed, and rejected card states", async () => {
    const unavailable = render(
      <RequirementPlanEvidencePanel
        compact={false}
        sessionId={SESSION_ID}
        sourceProjectionVersion="metric-contract-v2-projection-6"
        sourceRunId={RUN_ID}
        transport={{} as PromptEnhancerTransport}
      />,
    );
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "unavailable");
    expect(screen.queryByLabelText(/choose canonical requirement-plan/i)).not.toBeInTheDocument();
    unavailable.unmount();

    const pendingContract = deferred<RequirementPlanEvidenceContract>();
    const loadingTransport = transport();
    loadingTransport.getRequirementPlanEvidenceContract = vi.fn().mockReturnValue(pendingContract.promise);
    const loading = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={loadingTransport} />,
    );
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "loading");
    expect(screen.getByText(/loading the fresh exact r6 contract/i)).toBeVisible();
    loading.unmount();

    const empty = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={transport()} />,
    );
    expect(await screen.findByText(/No unconfirmed requirement-plan proposal/i)).toBeVisible();
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "empty");
    empty.unmount();

    const decisions = render(
      <RequirementPlanEvidencePanel
        compact={false}
        sessionId={SESSION_ID}
        sourceProjectionVersion="metric-contract-v2-projection-6"
        sourceRunId={RUN_ID}
        transport={transport([proposal(RUN_ID, "confirmed"), proposal(RUN_ID, "rejected", "1".repeat(64))])}
      />,
    );
    expect(await screen.findByText("Confirmed evidence")).toBeVisible();
    expect(screen.getByText("Rejected proposal")).toBeVisible();
    expect(screen.getByText("1 confirmed · 1 rejected")).toBeVisible();
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "confirmed");
    decisions.unmount();

    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={transport([proposal(RUN_ID, "rejected")])} />,
    );
    expect(await screen.findByText("Rejected proposal")).toBeVisible();
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "rejected");
  });

  it("rejects empty, oversized, wrong-media, and schema-invalid files without rendering file names or raw errors", async () => {
    const local = transport();
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    await screen.findByLabelText("Choose canonical requirement-plan evidence file");

    chooseFile("", "private-name.json", "application/json");
    expect(screen.getByRole("alert")).toHaveTextContent(/non-empty/i);
    expect(screen.queryByText("private-name.json")).not.toBeInTheDocument();

    chooseFile("{}", "private-name.txt", "text/plain");
    expect(screen.getByRole("alert")).toHaveTextContent(/\.json file/i);
    expect(screen.queryByText("private-name.txt")).not.toBeInTheDocument();

    chooseFile("x".repeat(65_537), "oversized.json", "application/json");
    expect(screen.getByRole("alert")).toHaveTextContent(/64 KiB/i);
    expect(local.previewRequirementPlanEvidence).not.toHaveBeenCalled();

    local.previewRequirementPlanEvidence = vi.fn().mockRejectedValue(
      new Error("synthetic raw parser detail must stay hidden"),
    );
    chooseSyntheticFile();
    expect(await screen.findByRole("alert")).toHaveTextContent(/failed strict local schema validation/i);
    expect(screen.queryByText(/synthetic raw parser detail/i)).not.toBeInTheDocument();
  });

  it("rejects a mismatched preview and an imported proposal that loses exact authority", async () => {
    const previewMismatch = transport();
    previewMismatch.previewRequirementPlanEvidence = vi.fn().mockResolvedValue(
      preview("9".repeat(64)),
    );
    const first = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={previewMismatch} />,
    );
    await screen.findByText(/bound to sealed run/i);
    chooseSyntheticFile();
    expect(await screen.findByRole("alert")).toHaveTextContent(/another exact session, sealed run/i);
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "stale");
    expect(previewMismatch.importRequirementPlanEvidence).not.toHaveBeenCalled();
    first.unmount();

    const importMismatch = transport();
    importMismatch.importRequirementPlanEvidence = vi.fn().mockResolvedValue({
      payload_sha256: PAYLOAD_ID,
      proposal: proposal("9".repeat(64)),
      applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
    });
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={importMismatch} />,
    );
    await screen.findByText(/bound to sealed run/i);
    chooseSyntheticFile();
    fireEvent.click(await screen.findByRole("button", { name: "Import as unconfirmed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not preserve the exact preview/i);
    expect(screen.queryByRole("button", { name: "Open exact local clause review" })).not.toBeInTheDocument();
  });

  it("expires a strict preview before import and clears its retained payload", async () => {
    vi.useFakeTimers({ now: new Date("2042-01-01T00:00:00Z") });
    const local = transport();
    local.previewRequirementPlanEvidence = vi.fn().mockResolvedValue({
      ...preview(), expires_at: "2042-01-01T00:00:01Z",
    });
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    chooseSyntheticFile();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole("button", { name: "Import as unconfirmed" })).toBeVisible();
    await act(async () => { vi.advanceTimersByTime(1_001); });
    expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/file preview expired/i);
    expect(local.importRequirementPlanEvidence).not.toHaveBeenCalled();
  });

  it("rejects a mismatched decision response and never announces evidence authority", async () => {
    const local = transport([proposal()]);
    local.decideRequirementPlanProposal = vi.fn().mockResolvedValue({
      proposal: proposal(RUN_ID, "confirmed", "1".repeat(64)),
      applied: true,
    });
    const changed = vi.fn();
    render(
      <RequirementPlanEvidencePanel compact={false} onEvidenceChanged={changed} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply native rejection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not preserve the exact proposal/i);
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText("Confirmed evidence")).not.toBeInTheDocument();
  });

  it("makes a captured run-A decision inert immediately after the first run-B render", async () => {
    const runB = "9".repeat(64);
    const windowB = "2".repeat(64);
    const proposalB = "1".repeat(64);
    const local = transport([proposal()]);
    local.getRequirementPlanEvidenceContract = vi.fn()
      .mockResolvedValueOnce(contract())
      .mockResolvedValueOnce(contract(runB, "metric-contract-v2-projection-6", windowB));
    local.listRequirementPlanProposals = vi.fn()
      .mockResolvedValueOnce({ session_id: SESSION_ID, proposals: [proposal()], total: 1, complete: true, snapshot: snapshot([proposal()]) })
      .mockResolvedValueOnce({
        session_id: SESSION_ID,
        proposals: [proposal(runB, "proposed", proposalB, windowB)],
        total: 1,
        complete: true,
        snapshot: snapshot([proposal(runB, "proposed", proposalB, windowB)]),
      });
    const view = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const staleApply = screen.getByRole("button", { name: "Apply native rejection" });

    view.rerender(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={runB} transport={local} />,
    );

    expect(screen.queryByRole("button", { name: "Apply native rejection" })).not.toBeInTheDocument();
    fireEvent.click(staleApply);
    expect(local.decideRequirementPlanProposal).not.toHaveBeenCalled();
    expect(await screen.findByText(new RegExp(`Content-free proposal ${proposalB.slice(0, 12)}`))).toBeVisible();
  });

  it("drops a delayed run-A confirmation completion after switching to run B", async () => {
    const runB = "9".repeat(64);
    const windowB = "2".repeat(64);
    const decision = deferred<{ proposal: RequirementPlanProposal; applied: boolean }>();
    const local = transport([proposal()]);
    local.decideRequirementPlanProposal = vi.fn().mockReturnValue(decision.promise);
    local.getRequirementPlanEvidenceContract = vi.fn()
      .mockResolvedValueOnce(contract())
      .mockResolvedValueOnce(contract(runB, "metric-contract-v2-projection-6", windowB));
    local.listRequirementPlanProposals = vi.fn()
      .mockResolvedValueOnce({ session_id: SESSION_ID, proposals: [proposal()], total: 1, complete: true, snapshot: snapshot([proposal()]) })
      .mockResolvedValueOnce({ session_id: SESSION_ID, proposals: [], total: 0, complete: true, snapshot: snapshot([]) });
    const changed = vi.fn();
    const view = render(
      <RequirementPlanEvidencePanel compact={false} onEvidenceChanged={changed} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open exact local clause review" }));
    await screen.findByText("Create the synthetic artifact.");
    fireEvent.click(screen.getByLabelText(/I reviewed every displayed user and PLAN clause/i));
    fireEvent.click(screen.getByRole("button", { name: "Confirm evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply native confirmation" }));

    view.rerender(
      <RequirementPlanEvidencePanel compact={false} onEvidenceChanged={changed} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={runB} transport={local} />,
    );
    await screen.findByText(/No unconfirmed requirement-plan proposal/i);
    decision.resolve({ proposal: proposal(RUN_ID, "confirmed"), applied: true });
    await act(async () => { await Promise.resolve(); });

    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText("Confirmed evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
  });

  it("renders long safe coordinates, opaque IDs, and escaped synthetic clause text exactly", async () => {
    const sequences = new Map([[1, 999_999_990], [2, 999_999_991], [3, 999_999_992], [4, 999_999_993]]);
    const exactText = `<synthetic.example>&"\\n${"Z".repeat(512)}`;
    const exactContract = contract();
    exactContract.source_manifest.messages = exactContract.source_manifest.messages.map((message) => ({
      ...message,
      message_sequence: sequences.get(message.message_sequence)!,
    }));
    const exactProposal = proposal();
    exactProposal.requirements = exactProposal.requirements.map((item) => ({
      ...item,
      coordinate: { ...item.coordinate, message_sequence: sequences.get(item.coordinate.message_sequence)! },
    }));
    exactProposal.excluded_user_clauses = exactProposal.excluded_user_clauses.map((item) => ({
      ...item,
      coordinate: { ...item.coordinate, message_sequence: sequences.get(item.coordinate.message_sequence)! },
      basis_coordinate: item.basis_coordinate === null ? null : {
        ...item.basis_coordinate,
        message_sequence: sequences.get(item.basis_coordinate.message_sequence)!,
      },
    }));
    exactProposal.plan_items = exactProposal.plan_items.map((item) => ({
      ...item, message_sequence: sequences.get(item.message_sequence)!,
    }));
    const exactReview = review();
    exactReview.candidate_clauses = exactReview.candidate_clauses.map((clause, index) => ({
      ...clause,
      text: index === 0 ? exactText : clause.text,
      message_sequence: sequences.get(clause.message_sequence)!,
      basis_coordinate: clause.basis_coordinate === null ? null : {
        ...clause.basis_coordinate,
        message_sequence: sequences.get(clause.basis_coordinate.message_sequence)!,
      },
      linked_plan_coordinates: clause.linked_plan_coordinates.map((coordinate) => ({
        ...coordinate,
        message_sequence: sequences.get(coordinate.message_sequence)!,
      })),
    }));
    const local = transport([exactProposal]);
    local.getRequirementPlanEvidenceContract = vi.fn().mockResolvedValue(exactContract);
    local.reviewRequirementPlanProposal = vi.fn().mockResolvedValue(exactReview);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open exact local clause review" }));

    expect(await screen.findByText(exactText)).toBeVisible();
    expect(screen.getAllByText(/message 999999990, clause 0/i).length).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(PROPOSAL_ID))).toBeVisible();
    expect(screen.getByText(REVIEW_RECEIPT_ID)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("focuses one-shot review and decision controls and closes each with Escape", async () => {
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={transport([proposal()])} />,
    );
    const open = await screen.findByRole("button", { name: "Open exact local clause review" });
    fireEvent.click(open);
    const reviewRegion = await screen.findByRole("region", { name: new RegExp(`Exact clause review for proposal ${PROPOSAL_ID}`) });
    await waitFor(() => expect(reviewRegion).toHaveFocus());
    fireEvent.keyDown(reviewRegion, { key: "Escape" });
    expect(screen.queryByRole("region", { name: /Exact clause review for proposal/i })).not.toBeInTheDocument();
    await waitFor(() => expect(open).toHaveFocus());

    const reject = screen.getByRole("button", { name: "Reject" });
    fireEvent.click(reject);
    const apply = screen.getByRole("button", { name: "Apply native rejection" });
    await waitFor(() => expect(apply).toHaveFocus());
    const decisionGroup = screen.getByRole("group", { name: "Reject requirement-plan proposal" });
    fireEvent.keyDown(decisionGroup, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Reject requirement-plan proposal" })).not.toBeInTheDocument();
    await waitFor(() => expect(reject).toHaveFocus());
  });

  it("fails closed on incomplete review and on load errors without exposing caught details", async () => {
    const incomplete = transport([proposal()]);
    incomplete.reviewRequirementPlanProposal = vi.fn().mockResolvedValue({
      ...review(), candidate_clauses: review().candidate_clauses.slice(0, -1),
    });
    const first = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={incomplete} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open exact local clause review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/incomplete, stale, mismatched, or expired/i);
    expect(screen.queryByLabelText(/I reviewed every displayed/i)).not.toBeInTheDocument();
    first.unmount();

    const failed = transport();
    failed.getRequirementPlanEvidenceContract = vi.fn().mockRejectedValue(
      new Error("synthetic internal transport detail must stay hidden"),
    );
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={failed} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
    expect(screen.queryByText(/synthetic internal transport detail/i)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" }))
      .toHaveAttribute("data-state", "error");
  });

  it("makes a captured preview-A import inert after same-owner preview B replaces its bytes", async () => {
    const local = transport();
    local.previewRequirementPlanEvidence = vi.fn()
      .mockResolvedValueOnce(preview())
      .mockResolvedValueOnce({
        ...preview(),
        payload_sha256: "0".repeat(64),
        active_requirement_count: 1,
        linked_active_requirement_count: 1,
        pending_active_requirement_count: 0,
        reviewed_user_clause_count: 2,
      });
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    await screen.findByText(/bound to sealed run/i);
    chooseSyntheticFile();
    const importA = await screen.findByRole("button", { name: "Import as unconfirmed" });
    const retainedImportA = captureReactClick(importA);

    chooseFile('{"synthetic":"b"}', "replacement.json", "application/json");
    expect(await screen.findByText(/1 proposed active requirements/i)).toBeVisible();
    act(() => retainedImportA());

    expect(local.importRequirementPlanEvidence).not.toHaveBeenCalled();
  });

  it("requires a currently live pending decision after Cancel and consumes it after one Apply", async () => {
    const local = transport([proposal()]);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const apply = screen.getByRole("button", { name: "Apply native rejection" });
    const retainedApply = captureReactClick(apply);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    act(() => retainedApply());
    expect(local.decideRequirementPlanProposal).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const liveApply = screen.getByRole("button", { name: "Apply native rejection" });
    const retainedAfterApply = captureReactClick(liveApply);
    fireEvent.click(liveApply);
    await waitFor(() => expect(local.decideRequirementPlanProposal).toHaveBeenCalledTimes(1));
    act(() => retainedAfterApply());
    expect(local.decideRequirementPlanProposal).toHaveBeenCalledTimes(1);
  });

  it("makes retained review and confirmation controls inert after live proposal, review, or acknowledgement changes", async () => {
    const local = transport([proposal()]);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={local} />,
    );
    const open = await screen.findByRole("button", { name: "Open exact local clause review" });
    const retainedOpen = captureReactClick(open);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply native rejection" }));
    await waitFor(() => expect(local.decideRequirementPlanProposal).toHaveBeenCalledTimes(1));
    act(() => retainedOpen());
    expect(local.reviewRequirementPlanProposal).not.toHaveBeenCalled();

    const localReview = transport([proposal()]);
    const second = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={localReview} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open exact local clause review" }));
    await screen.findByText("Create the synthetic artifact.");
    const acknowledgement = screen.getByLabelText(/I reviewed every displayed user and PLAN clause/i);
    fireEvent.click(acknowledgement);
    const confirm = screen.getByRole("button", { name: "Confirm evidence" });
    const retainedConfirm = captureReactClick(confirm);
    fireEvent.click(acknowledgement);
    act(() => retainedConfirm());
    expect(screen.queryByRole("group", { name: "Confirm requirement-plan proposal" })).not.toBeInTheDocument();

    fireEvent.click(acknowledgement);
    fireEvent.click(screen.getByRole("button", { name: "Confirm evidence" }));
    const applyConfirmation = screen.getByRole("button", { name: "Apply native confirmation" });
    const retainedConfirmation = captureReactClick(applyConfirmation);
    fireEvent.click(screen.getByRole("button", { name: "Close review" }));
    act(() => retainedConfirmation());
    expect(localReview.decideRequirementPlanProposal).not.toHaveBeenCalled();
    second.unmount();
  });

  it("treats native presence as a coherent fail-closed tuple", async () => {
    const inconsistentMode = transport([proposal()]);
    inconsistentMode.getUserPresenceCapability = vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "unavailable",
    });
    const first = render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={inconsistentMode} />,
    );
    expect(await screen.findByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open exact local clause review" })).toBeDisabled();
    first.unmount();

    const wrongContract = transport([proposal()]);
    wrongContract.getUserPresenceCapability = vi.fn().mockResolvedValue({
      contract_version: "synthetic-wrong-contract",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    } as never);
    render(
      <RequirementPlanEvidencePanel compact={false} sessionId={SESSION_ID} sourceProjectionVersion="metric-contract-v2-projection-6" sourceRunId={RUN_ID} transport={wrongContract} />,
    );
    expect(await screen.findByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open exact local clause review" })).toBeDisabled();
  });

  it("labels the inherited requirement-plan boundary with the selected r8 projection", () => {
    const pending = vi.fn(() => new Promise<never>(() => undefined));
    render(
      <RequirementPlanEvidencePanel
        compact={false}
        sessionId={SESSION_ID}
        sourceProjectionVersion="metric-contract-v2-projection-8"
        sourceRunId={RUN_ID}
        transport={{
          getRequirementPlanEvidenceContract: pending,
          previewRequirementPlanEvidence: vi.fn(),
          importRequirementPlanEvidence: vi.fn(),
          listRequirementPlanProposals: pending,
          reviewRequirementPlanProposal: vi.fn(),
          decideRequirementPlanProposal: vi.fn(),
        } as never}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/fresh exact r8 contract/i);
    expect(screen.getByRole("status")).not.toHaveTextContent(/r5\/r6\/r7/i);
  });
});
