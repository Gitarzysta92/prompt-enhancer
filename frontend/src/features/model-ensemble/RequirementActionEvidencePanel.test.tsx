import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect, useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type {
  ModelRequirementActionEvidenceBinding,
  PromptEnhancerTransport,
  RequirementActionEvidenceContract,
  RequirementActionProposal,
  RequirementActionProposalReview,
} from "../../shared/api/contracts";
import { RequirementActionEvidencePanel } from "./RequirementActionEvidencePanel";
import { REQUIREMENT_ACTION_FILE_JSON_SCHEMA } from "../../shared/api/requirementActionEvidenceContract";

const SESSION = "1".repeat(64);
const RUN = "2".repeat(64);
const WINDOW = "3".repeat(64);
const PLAN_CONFIRMATION = "4".repeat(64);
const PLAN_FINGERPRINT = "5".repeat(64);
const MANIFEST = "6".repeat(64);
const PROPOSAL = "7".repeat(64);
const REQUIREMENT_A = `deadbeef${"1".repeat(56)}`;
const REQUIREMENT_B = `deadbeef${"2".repeat(56)}`;
const ACTION_A = `cafebabe${"1".repeat(56)}`;
const ACTION_B = `cafebabe${"2".repeat(56)}`;
const SOURCE_A = `facefeed${"1".repeat(56)}`;
const SOURCE_B = `facefeed${"2".repeat(56)}`;
const RECEIPT = "c".repeat(64);
const GRAPH = "d".repeat(64);
const CANDIDATE_SET = "e".repeat(64);
const DESCRIPTOR_SET = "12".repeat(32);

function reviewedPublicBinding(seed: string): ModelRequirementActionEvidenceBinding {
  return {
    evidence_source: "reviewed_requirement_action",
    source_run_id: RUN,
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST,
    confirmation_id: seed.repeat(64),
    proposal_id: PROPOSAL,
    reviewed_descriptor_set_fingerprint: DESCRIPTOR_SET,
    evidence_fingerprint: seed.repeat(64),
    evidence_schema_version: "requirement-action-evidence-v1",
    evidence_policy_version: "reviewed-requirement-action-v1",
    local_only: true,
    content_persisted: false,
  };
}

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
    candidate_index: 0, action_id: ACTION_A, source_reference_id: SOURCE_A, sequence: 1,
    event_kind: "tool_start" as const, tool_category: "file_write" as const,
    occurred_at: "2040-01-01T00:00:00.000001Z", duration_ms: null,
    family: "file_change" as const, state: "started" as const,
  },
  {
    candidate_index: 1, action_id: ACTION_B, source_reference_id: SOURCE_B, sequence: 2,
    event_kind: "tool_end" as const, tool_category: "test" as const,
    occurred_at: "2040-01-01T00:00:00.000010+00:00", duration_ms: 17,
    family: "tool" as const, state: "completed" as const,
  },
];
const requirements = [
  { requirement_index: 0, requirement_id: REQUIREMENT_A, coordinate: { message_sequence: 1, clause_index: 0 } },
  { requirement_index: 1, requirement_id: REQUIREMENT_B, coordinate: { message_sequence: 2, clause_index: 0 } },
];

function contract(run = RUN, window = WINDOW): RequirementActionEvidenceContract {
  return {
    schema_version: "requirement-action-evidence-file-v1",
    session_id: SESSION,
    expected_source_run_id: run,
    source_window_fingerprint: window,
    source_projection_version: "metric-contract-v2-projection-7",
    requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest: {
      session_id: SESSION, source_run_id: run, source_window_fingerprint: window,
      provenance, extraction_complete: true, enumeration_complete: true,
      actions: structuredClone(candidates), manifest_fingerprint: MANIFEST,
      schema_version: "requirement-action-candidate-manifest-v1", local_only: true,
      content_persisted: false,
    },
    requirements: structuredClone(requirements),
    expected_predecessor_confirmation_id: null,
    metric_key: "logic.requirement_action_traceability",
    max_requirement_count: 1000, max_candidate_count: 4000, max_link_count: 8000,
    max_file_bytes: 65536, max_json_depth: 8, max_json_items: 8000,
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

function preview() {
  return {
    payload_sha256: "0".repeat(64), session_id: SESSION, expected_source_run_id: RUN,
    source_window_fingerprint: WINDOW, requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST, expected_predecessor_confirmation_id: null,
    requirement_count: 2, candidate_count: 2, linked_requirement_count: 1,
    unlinked_requirement_count: 1, link_count: 1,
    expires_at: "2040-01-01T01:00:00Z",
    producer: {
      kind: "local_coding_agent" as const, producer_id: "example-agent", producer_version: "v1",
      model_id: "example-model", authority: "untrusted_provenance_claim" as const,
    },
    creates_unconfirmed_proposal_only: true as const,
    native_confirmation_required_for_metric_authority: true as const,
    can_set_numeric_metric_on_import: false as const,
    raw_payload_persisted: false as const,
    raw_producer_claim_persisted: false as const,
  };
}

function proposal(overrides: Partial<RequirementActionProposal> = {}): RequirementActionProposal {
  return {
    proposal_id: PROPOSAL, session_id: SESSION, source_run_id: RUN,
    source_window_fingerprint: WINDOW, requirement_plan_confirmation_id: PLAN_CONFIRMATION,
    requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST, candidate_provenance: provenance,
    candidate_extraction_complete: true, candidate_enumeration_complete: true,
    expected_predecessor_confirmation_id: null, payload_sha256: "0".repeat(64),
    producer_receipt: {
      kind: "local_coding_agent", claim_fingerprint: "1".repeat(64),
      authority: "untrusted_provenance_claim_commitment", raw_claim_persisted: false,
    },
    review_rubric_version: "requirement-action-review-rubric-v2",
    requirements: structuredClone(requirements), candidates: structuredClone(candidates),
    links: [
      { requirement_id: REQUIREMENT_A, action_ids: [ACTION_B] },
      { requirement_id: REQUIREMENT_B, action_ids: [] },
    ],
    created_at: "2040-01-01T00:01:00.123456Z",
    schema_version: "requirement-action-evidence-v1",
    policy_version: "reviewed-requirement-action-v1", status: "proposed",
    decision_id: null, decision: null, decided_at: null, confirmation_authority: null,
    local_only: true, content_persisted: false,
    ...overrides,
  };
}

function review(run = RUN, window = WINDOW): RequirementActionProposalReview {
  return {
    proposal_id: PROPOSAL, session_id: SESSION, source_run_id: run,
    source_window_fingerprint: window, review_receipt_id: RECEIPT,
    payload_sha256: "0".repeat(64), requirement_plan_evidence_fingerprint: PLAN_FINGERPRINT,
    candidate_manifest_fingerprint: MANIFEST, reviewed_graph_fingerprint: GRAPH,
    reviewed_candidate_set_fingerprint: CANDIDATE_SET,
    reviewed_descriptor_set_fingerprint: DESCRIPTOR_SET,
    review_visible_display_algorithm_version: "requirement-action-review-visible-display-v1",
    requirements: [
      { requirement_id: REQUIREMENT_A, coordinate: requirements[0].coordinate, text: "Create the synthetic artifact.", linked_action_ids: [ACTION_B] },
      { requirement_id: REQUIREMENT_B, coordinate: requirements[1].coordinate, text: "Document the synthetic artifact.", linked_action_ids: [] },
    ],
    candidates: structuredClone(candidates),
    candidate_memberships: [
      {
        candidate: structuredClone(candidates[0]),
        candidate_metadata_fingerprint_version: "requirement-action-candidate-metadata-v1",
        candidate_metadata_fingerprint: "9".repeat(64),
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
        candidate_metadata_fingerprint: "a".repeat(64),
        descriptor_algorithm_version: "provider-local-redacted-action-descriptor-v1",
        tool_name: "synthetic.test",
        invocation_preview: "{\"suite\":\"example\"}",
        result_or_effect_preview: "{\"status\":\"passed\"}",
        invocation_truncated: false,
        result_or_effect_truncated: false,
        redactor_version: "synthetic-redactor-v1",
        linked_requirement_ids: [REQUIREMENT_A],
      },
    ],
    review_context_expires_at: new Date(Date.now() + 60_000).toISOString(),
    review_receipt_expires_at: new Date(Date.now() + 60_000).toISOString(),
    all_requirements_and_candidates_displayed: true,
    raw_text_persisted: false,
    local_only: true,
  };
}

function rejected(value: RequirementActionProposal): RequirementActionProposal {
  return {
    ...value,
    status: "rejected",
    decision_id: "9".repeat(64),
    decision: "reject",
    decided_at: new Date().toISOString(),
    confirmation_authority: "owned_native_user_presence",
  };
}

function confirmed(value: RequirementActionProposal): RequirementActionProposal {
  return {
    ...value,
    status: "confirmed",
    decision_id: "8".repeat(64),
    decision: "confirm",
    decided_at: "2040-01-01T00:02:00Z",
    confirmation_authority: "owned_native_user_presence",
  };
}

function transport(initial: RequirementActionProposal[] = [proposal()]): PromptEnhancerTransport {
  return {
    getRequirementActionEvidenceContract: vi.fn().mockResolvedValue(contract()),
    listRequirementActionProposals: vi.fn().mockResolvedValue({
      session_id: SESSION, proposals: initial, total: initial.length, complete: true,
      snapshot: {
        snapshot_id: "3".repeat(64), total: initial.length, decision_count: 0,
        high_water_created_at: initial.at(-1)?.created_at ?? null,
        high_water_proposal_id: initial.at(-1)?.proposal_id ?? null,
      },
    }),
    getUserPresenceCapability: vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    }),
    previewRequirementActionEvidence: vi.fn(),
    importRequirementActionEvidence: vi.fn(),
    reviewRequirementActionProposal: vi.fn().mockResolvedValue(review()),
    decideRequirementActionProposal: vi.fn().mockImplementation(async (
      _session: string,
      _proposalId: string,
      request: { decision: "confirm" | "reject" },
    ) => ({
      proposal: request.decision === "confirm" ? {
        ...proposal(), status: "confirmed", decision_id: "2".repeat(64), decision: "confirm",
        decided_at: new Date().toISOString(), confirmation_authority: "owned_native_user_presence",
      } : rejected(initial.find((item) => item.proposal_id === _proposalId) ?? proposal()),
      applied: true,
    })),
  } as unknown as PromptEnhancerTransport;
}

describe("RequirementActionEvidencePanel", () => {
  it("blocks an already-rendered A import during a same-binding transport B layout commit", async () => {
    const transportA = transport([]);
    transportA.previewRequirementActionEvidence = vi.fn().mockResolvedValue(preview());
    const transportB = transport([]);
    transportB.importRequirementActionEvidence = vi.fn().mockResolvedValue({
      payload_sha256: "0".repeat(64), proposal: proposal(), applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
      raw_producer_claim_persisted: false,
    });

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
            <RequirementActionEvidencePanel
              compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
              sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
              transport={useB ? transportB : transportA}
            />
          </div>
        </>
      );
    }

    render(<Harness />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("{}").buffer,
    });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("button", { name: "Import as unconfirmed" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Switch transport" }));

    expect(transportB.importRequirementActionEvidence).not.toHaveBeenCalled();
    expect(transportA.importRequirementActionEvidence).not.toHaveBeenCalled();
  });

  it("blocks an already-rendered A native decision during a public binding B layout commit", async () => {
    const local = transport([proposal()]);
    const bindingA = reviewedPublicBinding("a");
    const bindingB = reviewedPublicBinding("b");

    function Harness() {
      const [useB, setUseB] = useState(false);
      const host = useRef<HTMLDivElement>(null);
      useLayoutEffect(() => {
        if (!useB) return;
        const staleApply = [...(host.current?.querySelectorAll("button") ?? [])]
          .find((button) => button.textContent === "Apply exact confirmation");
        staleApply?.click();
      }, [useB]);
      return (
        <>
          <button onClick={() => setUseB(true)} type="button">Switch public binding</button>
          <div ref={host}>
            <RequirementActionEvidencePanel
              compact={false} publicEvidenceBinding={useB ? bindingB : bindingA}
              publicEvidenceSource="reviewed_requirement_action" sessionId={SESSION}
              sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
              transport={local}
            />
          </div>
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    await screen.findByText("Create the synthetic artifact.");
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    fireEvent.click(screen.getByRole("button", { name: "Confirm exact reviewed graph" }));
    expect(await screen.findByRole("button", {
      name: "Apply exact confirmation",
    })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Switch public binding" }));

    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("keeps confirmed and rejected records truthful, complete, and read-only in full and compact modes", async () => {
    const confirmedProposal = confirmed(proposal());
    const rejectedProposal = rejected(proposal({ proposal_id: "a".repeat(64) }));
    const local = transport([confirmedProposal, rejectedProposal]);
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="reviewed_requirement_action" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);

    expect(await screen.findByText("Confirmed")).toBeVisible();
    expect(screen.getByText("Rejected")).toBeVisible();
    expect(screen.getByText(confirmedProposal.proposal_id, { exact: true })).toBeVisible();
    expect(screen.getByText(rejectedProposal.proposal_id, { exact: true })).toBeVisible();
    expect(screen.getByText(confirmedProposal.decision_id!, { exact: true })).toBeVisible();
    expect(screen.getByText(rejectedProposal.decision_id!, { exact: true })).toBeVisible();
    expect(screen.queryByRole("button", { name: /inspect|confirm|reject/i })).not.toBeInTheDocument();

    view.rerender(<RequirementActionEvidencePanel
      compact publicEvidenceSource="reviewed_requirement_action" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);
    expect(screen.getByText("0 proposals awaiting native decision · 1 confirmed · 1 rejected")).toBeVisible();
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /inspect|confirm|reject/i })).not.toBeInTheDocument();
  });

  it.each([
    ["unavailable", /reviewed requirement-to-action evidence is unavailable/i],
    ["awaiting_review", /awaiting an owned native review/i],
    ["candidate_manifest_overflow", /candidate manifest overflowed/i],
    ["candidate_source_incomplete", /candidate extraction is incomplete/i],
    ["binding_invalid", /prior binding invalid/i],
    ["reviewed_requirement_action", /confirmed reviewed requirement-to-action binding/i],
  ] as const)("renders the %s public projection state without inventing a metric value", async (source, label) => {
    render(<RequirementActionEvidencePanel
      compact publicEvidenceSource={source} sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={transport([])}
    />);
    expect(await screen.findByText(label)).toBeVisible();
    expect(screen.queryByText(/0%|100%|metric value 0/i)).not.toBeInTheDocument();
  });

  it("keeps compact mode read-only and does not expose ephemeral requirement text", async () => {
    const local = transport();
    render(<RequirementActionEvidencePanel
      compact publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    expect(await screen.findByText("1 proposal awaiting native decision")).toBeVisible();
    expect(screen.getByRole("region", { name: "Reviewed requirement-to-action evidence" })).toBeVisible();
    expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
    expect(screen.queryByText("synthetic.write")).not.toBeInTheDocument();
    expect(screen.queryByText(/redacted synthetic target/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /inspect|confirm|reject/i })).not.toBeInTheDocument();
  });

  it("labels an invalid prior binding as recovery, never as an awaiting marker, in compact mode", async () => {
    const oldProposal = proposal({
      proposal_id: "0".repeat(64),
      source_run_id: "d".repeat(64),
      source_window_fingerprint: "e".repeat(64),
    });
    render(<RequirementActionEvidencePanel
      compact publicEvidenceSource="binding_invalid" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={transport([oldProposal, proposal()])}
    />);
    expect(await screen.findByText("1 current recovery proposal · prior binding invalid")).toBeVisible();
    expect(screen.queryByText(/awaiting native decision/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /inspect|confirm|reject/i })).not.toBeInTheDocument();
  });

  it("shows every requirement, candidate, membership, empty link, and exact receipt before confirmation", async () => {
    const local = transport([]);
    local.previewRequirementActionEvidence = vi.fn().mockResolvedValue(preview());
    local.importRequirementActionEvidence = vi.fn().mockResolvedValue({
      payload_sha256: "0".repeat(64), proposal: proposal(), applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
      raw_producer_claim_persisted: false,
    });
    const changed = vi.fn();
    render(<RequirementActionEvidencePanel
      compact={false} onEvidenceChanged={changed} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={local}
    />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("{}").buffer,
    });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });
    expect(await screen.findByText(/Producer example-agent \/ example-model is an ephemeral/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Import as unconfirmed" }));
    const inspect = await screen.findByRole("button", { name: "Inspect every item" });
    fireEvent.click(screen.getByText("Complete durable proposal metadata"));
    expect(screen.getByText(/synthetic synthetic-v1 · adapter adapter-v1 · decoder safe-event-evidence safe-event-v1/i)).toBeVisible();
    expect(screen.getByText(/candidate extraction complete · candidate enumeration complete/i)).toBeVisible();
    fireEvent.click(inspect);
    expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
    expect(screen.getByText(/Document the synthetic artifact\./)).toBeVisible();
    expect(screen.getByText(/Explicit empty link: reviewed negative only/i)).toBeVisible();
    expect(screen.getByText(/duration unknown/i)).toBeVisible();
    expect(screen.getByText(/17 ms/i)).toBeVisible();
    expect(screen.getByText(/no proposed requirement membership/i)).toBeVisible();
    expect(screen.getByText(SOURCE_A)).toBeVisible();
    expect(screen.getByText(SOURCE_B)).toBeVisible();
    expect(screen.getByText("Candidate #0")).toBeVisible();
    expect(screen.getByText("Candidate #1")).toBeVisible();
    expect(screen.getByText(/Requirement #0 · message 1, clause 0/i)).toBeVisible();
    expect(screen.getByText(/Requirement #1 · message 2, clause 0/i)).toBeVisible();
    expect(screen.getAllByText(ACTION_B, { exact: true })).toHaveLength(2);
    expect(screen.getAllByText(REQUIREMENT_A, { exact: true })).toHaveLength(2);
    expect(ACTION_A.slice(0, 8)).toBe(ACTION_B.slice(0, 8));
    expect(REQUIREMENT_A.slice(0, 8)).toBe(REQUIREMENT_B.slice(0, 8));
    expect(screen.getByText(/not proof of semantic relevance or task success/i)).toBeVisible();
    expect(screen.getByText("synthetic.write")).toBeVisible();
    expect(screen.getByText("synthetic.test")).toBeVisible();
    expect(screen.getByText('{"target":"[redacted synthetic target]"}')).toBeVisible();
    expect(screen.getByText('{"suite":"example"}')).toBeVisible();
    expect(screen.getByText('{"status":"passed"}')).toBeVisible();
    expect(screen.getByText(/No result\/effect preview: this is a started action/i)).toBeVisible();
    expect(screen.getByText(/exact one-pass, injective visible form/i)).toBeVisible();
    expect(screen.getAllByText(/requirement-action-candidate-metadata-v1/i)).toHaveLength(2);
    expect(screen.getByLabelText(`Full candidate metadata fingerprint ${"9".repeat(64)}`))
      .toHaveAttribute("title", "9".repeat(64));
    expect(screen.getAllByText(/provider-local-redacted-action-descriptor-v1/i)).toHaveLength(2);
    expect(screen.getByText(RECEIPT, { exact: true })).toBeVisible();
    expect(screen.getByText(DESCRIPTOR_SET, { exact: true })).toBeVisible();
    const confirm = screen.getByRole("button", { name: "Confirm exact reviewed graph" });
    expect(confirm).toBeDisabled();
    await act(async () => {});
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    fireEvent.click(screen.getByRole("button", { name: "Apply exact confirmation" }));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(local.decideRequirementActionProposal).toHaveBeenCalledWith(
      SESSION,
      PROPOSAL,
      {
        expected_source_run_id: RUN,
        decision: "confirm",
        confirmation: "decide_exact_reviewed_requirement_action_proposal",
        review_receipt_id: RECEIPT,
        reviewed_graph_fingerprint: GRAPH,
        candidate_manifest_fingerprint: MANIFEST,
        reviewed_candidate_set_fingerprint: CANDIDATE_SET,
        reviewed_descriptor_set_fingerprint: DESCRIPTOR_SET,
        complete_review_acknowledged: true,
        all_requirements_and_candidates_acknowledged: true,
        all_linked_action_semantics_reviewed: true,
      },
      expect.any(String),
      expect.anything(),
    );
  });

  it("recovers an invalid prior binding through a current replacement while old proposals stay reject-only", async () => {
    const oldProposal = proposal({
      proposal_id: "0".repeat(64),
      source_run_id: "d".repeat(64),
      source_window_fingerprint: "e".repeat(64),
    });
    const local = transport([oldProposal, proposal()]);
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="binding_invalid" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={local}
    />);

    expect(await screen.findByText(/prior sealed r7 requirement-action binding is invalid/i)).toBeVisible();
    expect(screen.getByText(/does not match the fresh recovery contract/i)).toBeVisible();
    const inspect = screen.getByRole("button", { name: "Inspect every item" });
    expect(inspect).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(2);
    fireEvent.click(inspect);
    expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
    await act(async () => {});
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    const confirm = screen.getByRole("button", { name: "Confirm exact reviewed graph" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    fireEvent.click(await screen.findByRole("button", { name: "Apply exact confirmation" }));
    await waitFor(() => expect(local.decideRequirementActionProposal).toHaveBeenCalledWith(
      SESSION,
      PROPOSAL,
      expect.objectContaining({ decision: "confirm", expected_source_run_id: RUN }),
      expect.any(String),
      expect.anything(),
    ));
  });

  it("renders one-pass escaped controls and literal backslashes exactly without decoding", async () => {
    const local = transport();
    const encodedReview = review();
    const requirementText = "Control \\u202e; single space; double  space; literal \\\\u202e; newline \\n; slash A\\\\B.";
    const toolText = "tool single double  space \\n\\u202e\\\\u202e";
    const invocationText = "invoke single double  space \\t\\u2028\\\\path";
    const effectText = "effect single double  space \\r\\u2029\\\\literal";
    encodedReview.requirements[0].text = requirementText;
    encodedReview.candidate_memberships[0].tool_name = toolText;
    encodedReview.candidate_memberships[0].invocation_preview = invocationText;
    encodedReview.candidate_memberships[1].result_or_effect_preview = effectText;
    local.reviewRequirementActionProposal = vi.fn().mockResolvedValue(encodedReview);
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    const requirementLine = await screen.findByText((_, element) => (
      element?.tagName === "P"
      && element.textContent === `Requirement #0 · message 1, clause 0 · ${REQUIREMENT_A} — ${requirementText}`
    ));
    const tool = screen.getByText((_, element) => (
      element?.tagName === "SPAN" && element.textContent === toolText
    ));
    const invocation = screen.getByText((_, element) => (
      element?.tagName === "BLOCKQUOTE" && element.textContent === invocationText
    ));
    const effect = screen.getByText((_, element) => (
      element?.tagName === "BLOCKQUOTE" && element.textContent === effectText
    ));
    expect(requirementLine.textContent)
      .toBe(`Requirement #0 · message 1, clause 0 · ${REQUIREMENT_A} — ${requirementText}`);
    expect(tool.textContent).toBe(toolText);
    expect(invocation.textContent).toBe(invocationText);
    expect(effect.textContent).toBe(effectText);
    const exactRequirementText = requirementLine.querySelector(".metric-evidence-file__exact-review-text");
    expect(exactRequirementText).not.toBeNull();
    for (const element of [exactRequirementText, tool, invocation, effect]) {
      expect(element!).toHaveClass("metric-evidence-file__exact-review-text");
      expect(element!.textContent).toContain("double  space");
    }
    for (const element of [requirementLine, tool, invocation, effect]) {
      expect(element.textContent).not.toContain("\u202e");
      expect(element.textContent).not.toContain("\n");
    }
  });

  it("fails closed before display when candidate metadata receipt version drifts", async () => {
    const local = transport();
    const drifted = review() as unknown as Record<string, any>;
    drifted.candidate_memberships[0].candidate_metadata_fingerprint_version = "future-metadata-v2";
    local.reviewRequirementActionProposal = vi.fn().mockResolvedValue(drifted);
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    expect(await screen.findByText(/review is stale or expired/i)).toBeVisible();
    expect(screen.queryByText(/Create the synthetic artifact\./)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
  });

  it("offers a copyable, content-free local-agent workflow and keeps import non-authoritative", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={transport([])}
    />);
    const prompt = await screen.findByLabelText("Requirement-action local-agent metaprompt");
    const promptValue = (prompt as HTMLTextAreaElement).value;
    expect(promptValue).toContain(`/v1/sessions/${SESSION}/requirement-action-evidence/contract`);
    expect(promptValue).toContain("choose only action_candidate_indexes");
    expect(promptValue).toContain("Do not include action state claims");
    expect(promptValue).toContain("The proposal is inert");
    fireEvent.click(screen.getByRole("button", { name: "Copy local-agent workflow" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith((prompt as HTMLTextAreaElement).value));
    expect(screen.getByRole("status")).toHaveTextContent(/never metric authority/i);
  });

  it("rejects preview counts that drift from the exact contract before import", async () => {
    const local = transport([]);
    local.previewRequirementActionEvidence = vi.fn().mockResolvedValue({
      ...preview(), requirement_count: 1, linked_requirement_count: 1,
      unlinked_requirement_count: 0,
    });
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={local}
    />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("{}").buffer,
    });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/bound to another sealed source, plan, candidate set, or predecessor/i);
    expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
    expect(local.importRequirementActionEvidence).not.toHaveBeenCalled();
  });

  it("discards preview bytes and import authority at exact preview expiry", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const local = transport([]);
      local.previewRequirementActionEvidence = vi.fn().mockResolvedValue({
        ...preview(), expires_at: new Date(Date.now() + 60_000).toISOString(),
      });
      render(<RequirementActionEvidencePanel
        compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
        sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
        transport={local}
      />);
      await screen.findByText(/Bound to sealed run/i);
      const file = new File(["{}"], "example.json", { type: "application/json" });
      Object.defineProperty(file, "arrayBuffer", {
        value: async () => new TextEncoder().encode("{}").buffer,
      });
      fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
        target: { files: [file] },
      });
      expect(await screen.findByRole("button", { name: "Import as unconfirmed" })).toBeVisible();

      await act(async () => { await vi.advanceTimersByTimeAsync(60_001); });

      expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/file preview expired/i);
      expect(local.importRequirementActionEvidence).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("fails closed when native presence is unavailable and describes unknown without a zero", async () => {
    const local = transport();
    local.getUserPresenceCapability = vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: false,
      mode: "unavailable",
    });
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    expect(await screen.findByText(/Unknown is never rendered as zero/i)).toBeVisible();
    expect(screen.getByText(/does not imply Codex support or shipped metric operability/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByText(/review and decisions are disabled/i)).toBeVisible();
    expect(local.reviewRequirementActionProposal).not.toHaveBeenCalled();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("fails closed when native presence capability is unknown", async () => {
    const local = transport();
    delete (local as Partial<PromptEnhancerTransport>).getUserPresenceCapability;
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    expect(await screen.findByText(/Bound to sealed run/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByText(/Owned native user presence is unavailable/i)).toBeVisible();
    expect(local.reviewRequirementActionProposal).not.toHaveBeenCalled();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("never opens native review for proposal provenance, completeness, requirement, or candidate drift", async () => {
    for (const mutate of [
      (value: any) => { value.candidate_provenance.decoder_version = "drifted-decoder-v2"; },
      (value: any) => { value.candidate_extraction_complete = false; },
      (value: any) => { value.candidate_enumeration_complete = false; },
      (value: any) => { value.requirements[0].coordinate.clause_index = 7; },
      (value: any) => { value.candidates[0].source_reference_id = "d".repeat(64); },
    ]) {
      const drifted = structuredClone(proposal()) as unknown as Record<string, any>;
      mutate(drifted);
      const local = transport([drifted as unknown as RequirementActionProposal]);
      const view = render(<RequirementActionEvidencePanel
        compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
        sourceRunId={RUN} transport={local}
      />);
      expect(await screen.findByText(/Stale proposal: it cannot be confirmed/i)).toBeVisible();
      expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
      expect(local.reviewRequirementActionProposal).not.toHaveBeenCalled();
      view.unmount();
    }
  });

  it("resets a displayed review when the contract manifest or predecessor changes", async () => {
    const first = transport([proposal()]);
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={first}
    />);
    const inspect = await screen.findByRole("button", { name: "Inspect every item" });
    // Finish the asynchronous receipt and its acknowledgement-reset effect
    // before simulating the person's review acknowledgement.
    await act(async () => { fireEvent.click(inspect); });
    expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeEnabled();

    const changed = contract();
    changed.candidate_manifest.manifest_fingerprint = "13".repeat(32);
    changed.expected_predecessor_confirmation_id = "14".repeat(32);
    const replacement = transport([proposal()]);
    replacement.getRequirementActionEvidenceContract = vi.fn().mockResolvedValue(changed);
    view.rerender(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={replacement}
    />);

    await waitFor(() => expect(screen.queryByText(/Create the synthetic artifact\./)).not.toBeInTheDocument());
    expect(await screen.findByText(/Stale proposal: it cannot be confirmed/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
    expect(replacement.reviewRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("resets review and acknowledgement when the public authority marker changes", async () => {
    const local = transport([proposal()]);
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={local}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
    await act(async () => {});
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeEnabled();

    view.rerender(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="binding_invalid" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={local}
    />);

    expect(await screen.findByText(/prior sealed r7 requirement-action binding is invalid/i)).toBeVisible();
    expect(screen.queryByText(/Create the synthetic artifact\./)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeEnabled();
  });

  it("resets review and acknowledgement when reviewed public authority A changes to B", async () => {
    const local = transport([proposal()]);
    const bindingA = reviewedPublicBinding("a");
    const bindingB = reviewedPublicBinding("b");
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceBinding={bindingA} publicEvidenceSource="reviewed_requirement_action"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
    await act(async () => {});
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeEnabled();

    view.rerender(<RequirementActionEvidencePanel
      compact={false} publicEvidenceBinding={bindingB} publicEvidenceSource="reviewed_requirement_action"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);

    await waitFor(() => expect(screen.queryByText(/Create the synthetic artifact\./)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Inspect every item" })).toBeEnabled();
    expect(local.getRequirementActionEvidenceContract).toHaveBeenCalledTimes(2);
  });

  it("discards the complete review, acknowledgement, and confirm action at receipt expiry", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const local = transport();
      local.reviewRequirementActionProposal = vi.fn().mockResolvedValue({
        ...review(),
        review_context_expires_at: new Date(Date.now() + 60_000).toISOString(),
        review_receipt_expires_at: new Date(Date.now() + 60_000).toISOString(),
      });
      render(<RequirementActionEvidencePanel
        compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
        sourceRunId={RUN} transport={local}
      />);
      fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
      expect(await screen.findByText(/Create the synthetic artifact\./)).toBeVisible();
      await act(async () => {});
      fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
      expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeEnabled();

      await act(async () => { await vi.advanceTimersByTimeAsync(60_001); });

      expect(screen.queryByText(/Create the synthetic artifact\./)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/review receipt expired/i);
      expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects a stale proposal without opening review and discards a late A review after switching to B", async () => {
    const staleRun = "d".repeat(64);
    const stale = proposal({ source_run_id: staleRun, source_window_fingerprint: "e".repeat(64) });
    const local = transport([stale]);
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    expect(await screen.findByText(/Stale proposal: it cannot be confirmed/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply rejection" }));
    await waitFor(() => expect(local.decideRequirementActionProposal).toHaveBeenCalledWith(
      SESSION,
      PROPOSAL,
      {
        expected_source_run_id: staleRun,
        decision: "reject",
        confirmation: "decide_exact_reviewed_requirement_action_proposal",
      },
      expect.any(String),
      expect.anything(),
    ));
    expect(local.reviewRequirementActionProposal).not.toHaveBeenCalled();

    let resolveReview!: (value: RequirementActionProposalReview) => void;
    const delayed = new Promise<RequirementActionProposalReview>((resolve) => { resolveReview = resolve; });
    const current = transport([proposal()]);
    current.reviewRequirementActionProposal = vi.fn().mockImplementationOnce(() => delayed);
    const runB = "e".repeat(64);
    const windowB = "f".repeat(64);
    current.getRequirementActionEvidenceContract = vi.fn()
      .mockResolvedValueOnce(contract())
      .mockResolvedValueOnce(contract(runB, windowB));
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={current}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    view.rerender(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={runB} transport={current}
    />);
    resolveReview(review());
    await waitFor(() => expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument());
  });

  it("fails closed on public source/binding disagreement and contract receipt disagreement", async () => {
    const sourceMismatch = transport([]);
    const sourceView = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceBinding={reviewedPublicBinding("a")} publicEvidenceSource="awaiting_review"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={sourceMismatch}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/source marker and binding do not describe this exact selected run/i);
    expect(sourceMismatch.getRequirementActionEvidenceContract).not.toHaveBeenCalled();
    sourceView.unmount();

    const binding = reviewedPublicBinding("a");
    binding.requirement_plan_evidence_fingerprint = "f".repeat(64);
    const contractMismatch = transport([]);
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceBinding={binding} publicEvidenceSource="reviewed_requirement_action"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={contractMismatch}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not bound to this exact sealed r7 run/i);
    expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();
    view.unmount();
  });

  it("rejects every incomplete descriptor, candidate, membership, and review receipt shape before display", async () => {
    const mutations: Array<(value: Record<string, any>) => void> = [
      (value) => { value.candidate_memberships[0].descriptor_algorithm_version = "future-descriptor-v2"; },
      (value) => { value.candidate_memberships[0].invocation_truncated = true; },
      (value) => { value.candidate_memberships[1].result_or_effect_preview = null; },
      (value) => { value.candidate_memberships[1].linked_requirement_ids = []; },
      (value) => { value.candidate_memberships[0].candidate.candidate_index = 1; },
      (value) => { value.requirements[0].linked_action_ids = []; },
      (value) => { value.candidates.reverse(); },
      (value) => { value.raw_text_persisted = true; },
    ];
    for (const mutate of mutations) {
      const local = transport();
      const drifted = structuredClone(review()) as unknown as Record<string, any>;
      mutate(drifted);
      local.reviewRequirementActionProposal = vi.fn().mockResolvedValue(drifted);
      const view = render(<RequirementActionEvidencePanel
        compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
        sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
      />);
      fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/review is stale or expired/i);
      expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("rejects a mismatched native decision receipt and never publishes an evidence change", async () => {
    const local = transport();
    local.decideRequirementActionProposal = vi.fn().mockResolvedValue({
      proposal: confirmed(proposal({ source_window_fingerprint: "f".repeat(64) })),
      applied: true,
    });
    const changed = vi.fn();
    render(<RequirementActionEvidencePanel
      compact={false} onEvidenceChanged={changed} publicEvidenceSource="awaiting_review"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={local}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    await screen.findByText("Create the synthetic artifact.");
    await act(async () => {});
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    fireEvent.click(screen.getByRole("button", { name: "Confirm exact reviewed graph" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply exact confirmation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/decision receipt did not preserve the exact proposal/i);
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText("Confirmed")).not.toBeInTheDocument();
  });

  it("moves focus into native review and decision, and Escape closes each layer with focus restoration", async () => {
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={transport()}
    />);
    const inspect = await screen.findByRole("button", { name: "Inspect every item" });
    fireEvent.click(inspect);
    const reviewRegion = await screen.findByRole("region", { name: `Complete review for proposal ${PROPOSAL}` });
    await waitFor(() => expect(reviewRegion).toHaveFocus());
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    const confirm = screen.getByRole("button", { name: "Confirm exact reviewed graph" });
    fireEvent.click(confirm);
    const apply = screen.getByRole("button", { name: "Apply exact confirmation" });
    await waitFor(() => expect(apply).toHaveFocus());

    fireEvent.keyDown(apply, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Apply exact confirmation" })).not.toBeInTheDocument());
    await waitFor(() => expect(confirm).toHaveFocus());

    fireEvent.keyDown(reviewRegion, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument());
    await waitFor(() => expect(inspect).toHaveFocus());
  });

  it("closes the complete review from its header and restores focus without any native decision", async () => {
    const local = transport();
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);
    const inspect = await screen.findByRole("button", { name: "Inspect every item" });
    fireEvent.click(inspect);
    const reviewRegion = await screen.findByRole("region", { name: `Complete review for proposal ${PROPOSAL}` });
    await waitFor(() => expect(reviewRegion).toHaveFocus());
    fireEvent.click(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i));
    expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Close review" }));

    await waitFor(() => expect(screen.queryByText("Create the synthetic artifact.")).not.toBeInTheDocument());
    await waitFor(() => expect(inspect).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Confirm exact reviewed graph" })).not.toBeInTheDocument();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
    expect(local.importRequirementActionEvidence).not.toHaveBeenCalled();

    fireEvent.click(inspect);
    expect(await screen.findByText("Create the synthetic artifact.")).toBeVisible();
    expect(screen.getByLabelText(/I cross-checked and reviewed every displayed requirement/i)).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Confirm exact reviewed graph" })).toBeDisabled();
  });

  it("clears the native file input before reading so the same file can be reselected after a failed preview", async () => {
    const local = transport([]);
    local.previewRequirementActionEvidence = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic transient preview failure"))
      .mockResolvedValueOnce(preview());
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode("{}").buffer });
    const input = screen.getByLabelText("Choose canonical requirement-action evidence file") as HTMLInputElement;
    let selected: File[] = [];
    Object.defineProperty(input, "files", { configurable: true, get: () => selected });
    Object.defineProperty(input, "value", {
      configurable: true,
      get: () => (selected.length === 0 ? "" : `C:\\fakepath\\${selected[0].name}`),
      set: (next: string) => {
        if (next !== "") throw new Error("a native file input value can only be cleared");
        selected = [];
      },
    });
    // Native semantics: clearing the value empties the selection, so a same-file reselect emits a fresh change.
    const selectSameFile = () => {
      expect(input.value).toBe("");
      selected = [file];
      fireEvent.change(input);
    };

    selectSameFile();

    expect(await screen.findByRole("alert")).toHaveTextContent(/failed strict local validation/i);
    expect(input.value).toBe("");

    selectSameFile();

    expect(await screen.findByRole("button", { name: "Import as unconfirmed" })).toBeVisible();
    expect(local.previewRequirementActionEvidence).toHaveBeenCalledTimes(2);
    expect(local.importRequirementActionEvidence).not.toHaveBeenCalled();
    expect(screen.queryByText("example.json")).not.toBeInTheDocument();
  });

  it("recovers a transient requirement-action load failure only through an explicit retry", async () => {
    const local = transport([proposal()]);
    local.getRequirementActionEvidenceContract = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic transient load failure"))
      .mockResolvedValueOnce(contract());
    const recovered = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
    expect(local.getRequirementActionEvidenceContract).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry exact source contract" }));

    expect(await screen.findByText(/Bound to sealed run/i)).toBeVisible();
    expect(local.getRequirementActionEvidenceContract).toHaveBeenCalledTimes(2);
    expect(local.listRequirementActionProposals).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry exact source contract" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeEnabled();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
    expect(local.importRequirementActionEvidence).not.toHaveBeenCalled();
    recovered.unmount();

    const failClosed = transport([]);
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceBinding={reviewedPublicBinding("a")} publicEvidenceSource="awaiting_review"
      sessionId={SESSION} sourceProjectionVersion="metric-contract-v2-projection-7"
      sourceRunId={RUN} transport={failClosed}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not describe this exact selected run/i);
    expect(screen.queryByRole("button", { name: "Retry exact source contract" })).not.toBeInTheDocument();
    expect(failClosed.getRequirementActionEvidenceContract).not.toHaveBeenCalled();
  });

  it("keeps the inert file workflow and disabled decisions when the presence probe rejects", async () => {
    const local = transport([proposal()]);
    local.getUserPresenceCapability = vi.fn().mockRejectedValue(new Error("synthetic presence probe failure"));
    local.previewRequirementActionEvidence = vi.fn().mockResolvedValue(preview());
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);

    expect(await screen.findByText(/Bound to sealed run/i)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByText(/review and decisions are disabled/i)).toBeVisible();

    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode("{}").buffer });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("button", { name: "Import as unconfirmed" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeDisabled();
    expect(local.reviewRequirementActionProposal).not.toHaveBeenCalled();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("marks a resolved wrong verification binding retryable and recovers, while unknown capability never enables approvals", async () => {
    const local = transport([proposal()]);
    local.getRequirementActionEvidenceContract = vi.fn()
      .mockResolvedValueOnce(contract("f".repeat(64), "e".repeat(64)))
      .mockResolvedValueOnce(contract());
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/not bound to this exact sealed r7 run/i);
    expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry exact source contract" }));

    expect(await screen.findByText(/Bound to sealed run/i)).toBeVisible();
    expect(local.getRequirementActionEvidenceContract).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry exact source contract" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect every item" })).toBeEnabled();
    expect(local.decideRequirementActionProposal).not.toHaveBeenCalled();
    view.unmount();

    const malformedCapability = transport([proposal()]);
    malformedCapability.getUserPresenceCapability = vi.fn().mockResolvedValue({
      contract_version: "native-user-presence-capability-v2",
      confirmation_available: true,
      mode: "native_bridge_bound_token",
    });
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN}
      transport={malformedCapability}
    />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/not bound to this exact sealed r7 run/i);
    expect(screen.getByRole("button", { name: "Retry exact source contract" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Inspect every item" })).not.toBeInTheDocument();
    expect(malformedCapability.reviewRequirementActionProposal).not.toHaveBeenCalled();
    expect(malformedCapability.decideRequirementActionProposal).not.toHaveBeenCalled();
  });

  it("discards a delayed A import completion after a same-binding transport B replacement", async () => {
    let resolveImport!: (value: any) => void;
    const delayedImport = new Promise<any>((resolve) => { resolveImport = resolve; });
    const transportA = transport([]);
    transportA.previewRequirementActionEvidence = vi.fn().mockResolvedValue(preview());
    transportA.importRequirementActionEvidence = vi.fn().mockReturnValue(delayedImport);
    const transportB = transport([]);
    const view = render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={transportA}
    />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["{}"], "example.json", { type: "application/json" });
    Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode("{}").buffer });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Import as unconfirmed" }));

    view.rerender(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={transportB}
    />);
    resolveImport({
      payload_sha256: "0".repeat(64), proposal: proposal(), applied: true,
      creates_unconfirmed_proposal_only: true,
      native_confirmation_required_for_metric_authority: true,
      raw_payload_persisted: false,
      raw_producer_claim_persisted: false,
    });

    expect(await screen.findByText(/No requirement-action proposals are recorded/i)).toBeVisible();
    expect(screen.queryByText(PROPOSAL, { exact: true })).not.toBeInTheDocument();
  });

  it("renders dense nested memberships, long escaped descriptors, and large coordinates without shortening opaque IDs", async () => {
    const exactContract = contract();
    exactContract.requirements[0].coordinate = { message_sequence: 987_654_321, clause_index: 123_456_789 };
    exactContract.requirements[1].coordinate = { message_sequence: 987_654_322, clause_index: 123_456_790 };
    exactContract.candidate_manifest.actions[0].sequence = 2_000_000_001;
    exactContract.candidate_manifest.actions[1].sequence = 2_000_000_002;
    const exactProposal = proposal({
      requirements: structuredClone(exactContract.requirements),
      candidates: structuredClone(exactContract.candidate_manifest.actions),
      links: [
        { requirement_id: REQUIREMENT_A, action_ids: [ACTION_A, ACTION_B] },
        { requirement_id: REQUIREMENT_B, action_ids: [ACTION_B] },
      ],
    });
    const exactReview = review();
    const longRequirement = `literal \\u202e ${"double  space ".repeat(120)}end`;
    const longInvocation = `{"escaped":"\\\\u2028","value":"${"x".repeat(3_600)}"}`;
    exactReview.requirements = [
      {
        requirement_id: REQUIREMENT_A,
        coordinate: structuredClone(exactContract.requirements[0].coordinate),
        text: longRequirement,
        linked_action_ids: [ACTION_A, ACTION_B],
      },
      {
        requirement_id: REQUIREMENT_B,
        coordinate: structuredClone(exactContract.requirements[1].coordinate),
        text: "Second exact synthetic requirement.",
        linked_action_ids: [ACTION_B],
      },
    ];
    exactReview.candidates = structuredClone(exactContract.candidate_manifest.actions);
    exactReview.candidate_memberships[0].candidate = structuredClone(exactReview.candidates[0]);
    exactReview.candidate_memberships[0].linked_requirement_ids = [REQUIREMENT_A];
    exactReview.candidate_memberships[0].tool_name = `synthetic.${"t".repeat(100)}`;
    exactReview.candidate_memberships[0].invocation_preview = longInvocation;
    exactReview.candidate_memberships[1].candidate = structuredClone(exactReview.candidates[1]);
    exactReview.candidate_memberships[1].linked_requirement_ids = [REQUIREMENT_A, REQUIREMENT_B];
    const local = transport([exactProposal]);
    local.getRequirementActionEvidenceContract = vi.fn().mockResolvedValue(exactContract);
    local.reviewRequirementActionProposal = vi.fn().mockResolvedValue(exactReview);

    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Inspect every item" }));
    expect(await screen.findByText((_, element) => (
      element?.tagName === "SPAN" && element.textContent === longRequirement
    ))).toBeVisible();
    expect(screen.getByText(longInvocation, { exact: true })).toBeVisible();
    expect(screen.getByText(/message 987654321, clause 123456789/i)).toBeVisible();
    expect(screen.getByText(/sequence 2000000002/i)).toBeVisible();
    expect(screen.getAllByText(ACTION_B, { exact: true })).toHaveLength(3);
    expect(screen.getAllByText(REQUIREMENT_A, { exact: true })).toHaveLength(3);
    expect(screen.getByText(RECEIPT, { exact: true })).toBeVisible();
    expect(screen.getByRole("region", { name: "Review requirement-to-action evidence" }))
      .toHaveClass("requirement-action-evidence");
  });

  it("rejects unsupported file media before reading and never renders the synthetic file name", async () => {
    const local = transport([]);
    const read = vi.fn();
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="awaiting_review" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-7" sourceRunId={RUN} transport={local}
    />);
    await screen.findByText(/Bound to sealed run/i);
    const file = new File(["example"], "not-shown-example.txt", { type: "text/plain" });
    Object.defineProperty(file, "arrayBuffer", { value: read });
    fireEvent.change(screen.getByLabelText("Choose canonical requirement-action evidence file"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/supported local media type/i);
    expect(read).not.toHaveBeenCalled();
    expect(local.previewRequirementActionEvidence).not.toHaveBeenCalled();
    expect(screen.queryByText("not-shown-example.txt")).not.toBeInTheDocument();
  });

  it("labels the inherited requirement-action boundary with the selected r8 projection", () => {
    render(<RequirementActionEvidencePanel
      compact={false} publicEvidenceSource="unavailable" sessionId={SESSION}
      sourceProjectionVersion="metric-contract-v2-projection-8" sourceRunId={RUN} transport={{}}
    />);

    expect(screen.getByRole("status")).toHaveTextContent(/complete r8 requirement-action boundary/i);
    expect(screen.getByRole("status")).not.toHaveTextContent(/complete r7 requirement-action boundary/i);
  });
});
