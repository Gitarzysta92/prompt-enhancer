import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AgentMetricEvidencePreview,
  MetricLifecycleProposal,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { MetricEvidenceFilePanel } from "./MetricEvidenceFilePanel";

const sessionId = "2".repeat(64);
const runId = "3".repeat(64);
const nextRunId = "8".repeat(64);

function makeProposal(overrides: Partial<MetricLifecycleProposal> = {}): MetricLifecycleProposal {
  return {
    proposal_id: "1".repeat(64),
    session_id: sessionId,
    source_run_id: runId,
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
    ...overrides,
  };
}

const proposal = makeProposal();
const preview: AgentMetricEvidencePreview = {
  schema_version: "agent-metric-evidence-file-v2",
  payload_sha256: "5".repeat(64),
  session_id: sessionId,
  expected_source_run_id: runId,
  source_window_fingerprint: "6".repeat(64),
  metric_key: "collaboration.ambiguity_resolution",
  proposal_kind: "opportunity",
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
};

type LocalTransport = Pick<PromptEnhancerTransport,
  "previewAgentMetricEvidence" | "importAgentMetricEvidence" | "listMetricLifecycleProposals" | "decideMetricLifecycleProposal">
  & Partial<Pick<PromptEnhancerTransport, "getUserPresenceCapability">>;

function transport(initial: MetricLifecycleProposal[] = []): LocalTransport {
  return {
    getUserPresenceCapability: vi.fn(async () => ({
      contract_version: "native-user-presence-capability-v1" as const,
      confirmation_available: true,
      mode: "native_bridge_bound_token" as const,
    })),
    listMetricLifecycleProposals: vi.fn().mockResolvedValue({
      session_id: sessionId, proposals: initial, total: initial.length, complete: true,
    }),
    previewAgentMetricEvidence: vi.fn().mockResolvedValue(preview),
    importAgentMetricEvidence: vi.fn().mockResolvedValue({
      payload_sha256: preview.payload_sha256,
      proposal,
      applied: true,
      producer_claim_persisted: false,
      raw_payload_persisted: false,
      requires_authenticated_local_user_confirmation: true,
    }),
    decideMetricLifecycleProposal: vi.fn().mockImplementation(async (_session, _proposal, request) => ({
      proposal: makeProposal({
        status: request.decision === "confirm" ? "confirmed" : "rejected",
        decision_id: "7".repeat(64),
        decision: request.decision,
        decided_at: "2042-01-01T00:01:00+00:00",
      }),
      applied: true,
    })),
  };
}

function canonicalFile(
  content = "{}",
  name = "synthetic-evidence.json",
  type = "application/json",
): File {
  const file = new File([content], name, { type });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(content).buffer,
  });
  return file;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

async function flushEffects(cycles = 5): Promise<void> {
  for (let cycle = 0; cycle < cycles; cycle += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

describe("MetricEvidenceFilePanel", () => {
  it.each([
    { session_id: sessionId, proposals: [], total: 1, complete: false },
    { session_id: sessionId, proposals: [], total: 1, complete: true },
    { session_id: nextRunId, proposals: [], total: 0, complete: true },
  ])("does not misreport an incomplete or wrong-session proposal page as no evidence", async (page) => {
    const local = transport();
    vi.mocked(local.listMetricLifecycleProposals!).mockResolvedValue(page);
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/proposal list is incomplete or could not be verified/);
    expect(screen.queryByText(/No unconfirmed proposals are bound/)).not.toBeInTheDocument();
    expect(local.decideMetricLifecycleProposal).not.toHaveBeenCalled();
  });

  it("keeps confirmation disabled when the native capability's mode contradicts its flag", async () => {
    const local = transport([proposal]);
    vi.mocked(local.getUserPresenceCapability!).mockResolvedValue({ contract_version: "native-user-presence-capability-v1", confirmation_available: true, mode: "unavailable" });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    expect(await screen.findByRole("button", { name: "Confirm evidence" })).toBeDisabled();
    expect(local.decideMetricLifecycleProposal).not.toHaveBeenCalled();
  });

  it("reports compact loading, filters proposals to the exact run, and stays read-only", async () => {
    const page = deferred<Awaited<ReturnType<NonNullable<LocalTransport["listMetricLifecycleProposals"]>>>>();
    const local = transport();
    vi.mocked(local.listMetricLifecycleProposals!).mockReturnValueOnce(page.promise);
    render(<MetricEvidenceFilePanel compact sessionId={sessionId} sourceRunId={runId} transport={local} />);

    expect(screen.getByText("Loading exact-run evidence review…")).toBeInTheDocument();
    await act(async () => page.resolve({
      session_id: sessionId,
      proposals: [proposal, makeProposal({ proposal_id: "9".repeat(64), source_run_id: nextRunId })],
      total: 2,
      complete: true,
    }));

    expect(await screen.findByText("1 proposal awaiting review")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Confirmed metric evidence" })).toHaveAttribute("data-state", "ready");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/compact view never auto-approves evidence/i)).toBeInTheDocument();
  });

  it("shows a fail-closed unavailable state when the transport boundary is absent", () => {
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={{}} />);

    const panel = screen.getByRole("region", { name: "Import agent metric evidence" });
    expect(panel).toHaveAttribute("data-state", "unavailable");
    expect(screen.getByText(/does not expose the reviewed evidence-file boundary/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose canonical evidence file")).not.toBeInTheDocument();
  });

  it("distinguishes loading and empty states with an accessible hierarchy", async () => {
    const page = deferred<Awaited<ReturnType<NonNullable<LocalTransport["listMetricLifecycleProposals"]>>>>();
    const local = transport();
    vi.mocked(local.listMetricLifecycleProposals!).mockReturnValueOnce(page.promise);
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);

    expect(screen.getByRole("heading", { level: 3, name: "Import agent metric evidence" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/Loading proposals bound to this exact sealed run/i);
    await act(async () => page.resolve({ session_id: sessionId, proposals: [], total: 0, complete: true }));

    expect(await screen.findByRole("heading", { level: 4, name: "Proposals awaiting local decision" })).toBeInTheDocument();
    expect(screen.getByText(/No unconfirmed proposals are bound to this exact sealed run/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "empty");
  });

  it("recovers from a bounded proposal-load error without exposing the thrown detail", async () => {
    const local = transport();
    vi.mocked(local.listMetricLifecycleProposals!)
      .mockRejectedValueOnce(new Error("private-provider-detail"))
      .mockResolvedValueOnce({ session_id: sessionId, proposals: [], total: 0, complete: true });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
    expect(screen.queryByText(/private-provider-detail/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry exact-run review" }));
    expect(await screen.findByLabelText("Choose canonical evidence file")).toBeEnabled();
    expect(local.listMetricLifecycleProposals).toHaveBeenCalledTimes(2);
  });

  it("previews, imports, and requires a separate focused native confirmation", async () => {
    const local = transport();
    const changed = vi.fn();
    render(<MetricEvidenceFilePanel compact={false} onEvidenceChanged={changed} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    const picker = await screen.findByLabelText("Choose canonical evidence file");
    fireEvent.change(picker, { target: { files: [canonicalFile()] } });

    const previewRegion = await screen.findByRole("region", { name: "Strict local preview" });
    expect(previewRegion).toHaveFocus();
    expect(within(previewRegion).getByText(/Producer claim: example-agent/i)).toBeInTheDocument();
    expect(within(previewRegion).getByText(/untrusted provenance, not evidence authority/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import as unconfirmed" }));

    expect(await screen.findByRole("button", { name: "Confirm evidence" })).toBeInTheDocument();
    expect(screen.getByText(/Review it separately before making a native decision/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm evidence" }));
    const apply = screen.getByRole("button", { name: "Apply confirmation" });
    expect(apply).toHaveFocus();
    expect(local.decideMetricLifecycleProposal).not.toHaveBeenCalled();
    fireEvent.click(apply);

    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect(screen.getByText(/Evidence confirmed for this sealed run/i)).toHaveFocus();
    });
    expect(screen.getByText(/1 confirmed · 0 rejected decision recorded/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "confirmed");
    expect(local.previewAgentMetricEvidence).toHaveBeenCalledWith(sessionId, expect.anything(), expect.anything());
    expect(local.importAgentMetricEvidence).toHaveBeenCalledWith(
      sessionId,
      expect.anything(),
      preview.payload_sha256,
      "import_agent_metric_evidence_as_unconfirmed_proposal",
      expect.any(String),
      expect.anything(),
    );
    expect(local.decideMetricLifecycleProposal).toHaveBeenCalledWith(
      sessionId,
      proposal.proposal_id,
      expect.objectContaining({
        decision: "confirm",
        confirmation: "apply_local_user_metric_lifecycle_decision",
        expected_source_run_id: runId,
      }),
      expect.any(String),
      expect.anything(),
    );
  });

  it("cancels a decision with Escape and does not publish a refresh after rejection", async () => {
    const local = transport([proposal]);
    const changed = vi.fn();
    render(<MetricEvidenceFilePanel compact={false} onEvidenceChanged={changed} sessionId={sessionId} sourceRunId={runId} transport={local} />);

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const group = screen.getByRole("group", { name: /Reject ambiguity resolution/i });
    expect(screen.getByRole("button", { name: "Apply rejection" })).toHaveFocus();
    fireEvent.keyDown(group, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Apply rejection" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply rejection" }));
    expect(await screen.findByText(/No evidence was admitted/i)).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });

  it("fails closed when native user-presence capability is absent or unavailable", async () => {
    const withoutPresence = transport([proposal]);
    delete withoutPresence.getUserPresenceCapability;
    const { unmount } = render(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={withoutPresence} />,
    );
    expect(await screen.findByText(/proposals remain unconfirmed/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Confirm evidence" })).toBeDisabled();
    unmount();

    const unavailable = transport([proposal]);
    vi.mocked(unavailable.getUserPresenceCapability!).mockResolvedValue({
      contract_version: "native-user-presence-capability-v1",
      confirmation_available: false,
      mode: "unavailable",
    });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={unavailable} />);
    expect(await screen.findByRole("button", { name: "Confirm evidence" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(unavailable.decideMetricLifecycleProposal).not.toHaveBeenCalled();
  });

  it("rejects empty, oversized, wrong-extension, and wrong-media files before reading bytes", async () => {
    const local = transport();
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    const picker = await screen.findByLabelText("Choose canonical evidence file");

    fireEvent.change(picker, { target: { files: [canonicalFile("")] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/non-empty.*no larger than 64 KiB/i);
    fireEvent.change(picker, { target: { files: [canonicalFile("x".repeat(64 * 1024 + 1))] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/no larger than 64 KiB/i);
    fireEvent.change(picker, { target: { files: [canonicalFile("{}", "synthetic.txt", "application/json")] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/Choose a .json file/i);
    fireEvent.change(picker, { target: { files: [canonicalFile("{}", "synthetic.json", "text/plain")] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/canonical agent-evidence media type/i);
    expect(local.previewAgentMetricEvidence).not.toHaveBeenCalled();
  });

  it("bounds schema errors and never renders selected raw file content", async () => {
    const local = transport();
    vi.mocked(local.previewAgentMetricEvidence!).mockRejectedValue(new Error("synthetic-secret-canary"));
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    fireEvent.change(await screen.findByLabelText("Choose canonical evidence file"), {
      target: { files: [canonicalFile("raw-private-fixture-content")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/failed strict local schema validation/i);
    expect(screen.queryByText(/synthetic-secret-canary|raw-private-fixture-content/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
  });

  it("rejects an expired or differently bound preview as stale", async () => {
    const local = transport();
    vi.mocked(local.previewAgentMetricEvidence!).mockResolvedValue({
      ...preview,
      expected_source_run_id: nextRunId,
      expires_at: "2020-01-01T00:00:00+00:00",
    });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    fireEvent.change(await screen.findByLabelText("Choose canonical evidence file"), {
      target: { files: [canonicalFile()] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/stale or bound to another exact sealed source run/i);
    expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "stale");
  });

  it("drops a delayed preview when the exact source run changes", async () => {
    const delayed = deferred<AgentMetricEvidencePreview>();
    const local = transport();
    vi.mocked(local.previewAgentMetricEvidence!).mockReturnValueOnce(delayed.promise);
    const view = render(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />,
    );
    fireEvent.change(await screen.findByLabelText("Choose canonical evidence file"), {
      target: { files: [canonicalFile()] },
    });
    view.rerender(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={nextRunId} transport={local} />,
    );
    await act(async () => delayed.resolve(preview));

    expect(await screen.findByText(/No unconfirmed proposals are bound to this exact sealed run/i)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
    expect(screen.queryByText(/example-agent/i)).not.toBeInTheDocument();
  });

  it("synchronously hides an A preview on the first B render and makes its captured import action inert", async () => {
    const local = transport();
    const view = render(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />,
    );
    fireEvent.change(await screen.findByLabelText("Choose canonical evidence file"), {
      target: { files: [canonicalFile()] },
    });
    const staleImport = await screen.findByRole("button", { name: "Import as unconfirmed" });
    expect(screen.getByText(/Producer claim: example-agent/i)).toBeInTheDocument();

    view.rerender(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={nextRunId} transport={local} />,
    );

    expect(screen.queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
    expect(screen.queryByText(/example-agent/i)).not.toBeInTheDocument();
    fireEvent.click(staleImport);
    expect(local.importAgentMetricEvidence).not.toHaveBeenCalled();
  });

  it("synchronously hides A proposals on the first B render and makes a captured decision action inert", async () => {
    const local = transport([proposal]);
    const view = render(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Confirm evidence" }));
    const staleApply = screen.getByRole("button", { name: "Apply confirmation" });

    view.rerender(
      <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={nextRunId} transport={local} />,
    );

    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply confirmation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Confirm ambiguity resolution/i })).not.toBeInTheDocument();
    fireEvent.click(staleApply);
    expect(local.decideMetricLifecycleProposal).not.toHaveBeenCalled();
  });

  it("rejects an imported proposal that loses the exact preview binding", async () => {
    const local = transport();
    vi.mocked(local.importAgentMetricEvidence!).mockResolvedValue({
      payload_sha256: preview.payload_sha256,
      proposal: makeProposal({ source_run_id: nextRunId }),
      applied: true,
      producer_claim_persisted: false,
      raw_payload_persisted: false,
      requires_authenticated_local_user_confirmation: true,
    });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    fireEvent.change(await screen.findByLabelText("Choose canonical evidence file"), {
      target: { files: [canonicalFile()] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Import as unconfirmed" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/did not preserve the exact preview and sealed-run binding/i);
    expect(screen.queryByRole("button", { name: "Confirm evidence" })).not.toBeInTheDocument();
  });

  it("rejects a mismatched decision response and never announces evidence changed", async () => {
    const local = transport([proposal]);
    const changed = vi.fn();
    vi.mocked(local.decideMetricLifecycleProposal!).mockResolvedValue({
      proposal: makeProposal({
        source_run_id: nextRunId,
        status: "confirmed",
        decision_id: "7".repeat(64),
        decision: "confirm",
        decided_at: "2042-01-01T00:01:00+00:00",
      }),
      applied: true,
    });
    render(<MetricEvidenceFilePanel compact={false} onEvidenceChanged={changed} sessionId={sessionId} sourceRunId={runId} transport={local} />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm evidence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply confirmation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/did not preserve the exact proposal and sealed-run binding/i);
    expect(changed).not.toHaveBeenCalled();
  });

  it("reports already confirmed and rejected exact-run decisions without making them actionable", async () => {
    const confirmed = makeProposal({
      status: "confirmed",
      decision_id: "7".repeat(64),
      decision: "confirm",
      decided_at: "2042-01-01T00:01:00+00:00",
    });
    const rejected = makeProposal({
      proposal_id: "9".repeat(64),
      status: "rejected",
      decision_id: "a".repeat(64),
      decision: "reject",
      decided_at: "2042-01-01T00:02:00+00:00",
    });
    render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={transport([confirmed, rejected])} />);

    expect(await screen.findByText(/1 confirmed · 1 rejected decisions recorded/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm evidence|Reject/ })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "confirmed");
  });

  it("expires an idle strict preview and replaces it with reselect and refresh guidance", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2042-01-01T00:00:00Z"));
      const local = transport();
      render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />);
      await flushEffects();
      fireEvent.change(screen.getByLabelText("Choose canonical evidence file"), {
        target: { files: [canonicalFile()] },
      });
      await flushEffects();

      expect(screen.getByRole("region", { name: "Strict local preview" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Import as unconfirmed" })).toBeEnabled();
      expect(screen.getByText(/Strict preview ready/i)).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(60 * 60 * 1000);
      });

      expect(screen.queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Import as unconfirmed" })).not.toBeInTheDocument();
      expect(screen.queryByText(/example-agent/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Strict preview ready/i)).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/strict preview expired.*Select the canonical file again before importing/i);
      expect(screen.getByRole("button", { name: "Refresh exact-run review" })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "stale");
      expect(local.importAgentMetricEvidence).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("never lets a replaced or unmounted preview timer disturb a newer context", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2042-01-01T00:00:00Z"));
      const local = transport();
      vi.mocked(local.previewAgentMetricEvidence!).mockResolvedValueOnce({
        ...preview,
        expires_at: "2042-01-01T00:10:00+00:00",
      });
      const view = render(
        <MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={runId} transport={local} />,
      );
      await flushEffects();
      const picker = screen.getByLabelText("Choose canonical evidence file");
      fireEvent.change(picker, { target: { files: [canonicalFile()] } });
      await flushEffects();
      fireEvent.change(picker, { target: { files: [canonicalFile()] } });
      await flushEffects();

      await act(async () => {
        vi.advanceTimersByTime(20 * 60 * 1000);
      });

      expect(screen.getByRole("region", { name: "Strict local preview" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Import as unconfirmed" })).toBeEnabled();
      expect(screen.getByText(/Strict preview ready/i)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();

      view.unmount();
      expect(() => act(() => {
        vi.advanceTimersByTime(2 * 60 * 60 * 1000);
      })).not.toThrow();

      render(<MetricEvidenceFilePanel compact={false} sessionId={sessionId} sourceRunId={nextRunId} transport={local} />);
      await flushEffects();
      await act(async () => {
        vi.advanceTimersByTime(2 * 60 * 60 * 1000);
      });

      expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toHaveAttribute("data-state", "empty");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
