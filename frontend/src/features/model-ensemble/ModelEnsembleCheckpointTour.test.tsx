import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPage,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { describe, expect, it, vi } from "vitest";
import { MetricWorkspace } from "./MetricWorkspace";
import { ModelEnsemblePanel } from "./ModelEnsemblePanel";
import {
  CHECKPOINT_CAPABILITY,
  CHECKPOINT_COMPATIBILITY,
  CHECKPOINT_PROJECT_ID,
  CHECKPOINT_RUN_A,
  CHECKPOINT_RUN_B,
  CHECKPOINT_SESSION_A,
  CHECKPOINT_SESSION_B,
  checkpointFile,
  checkpointHead,
  checkpointRun,
  checkpointStages,
  checkpointTrajectory,
  checkpointTransport,
  type CheckpointTransportLane,
} from "./modelEnsembleCheckpointTour.test-fixtures";

// This checkpoint intentionally stops at UI-07. Keep the later evidence cards
// outside this host tour so their independent implementation lanes cannot
// change the meaning or stability of these integration assertions.
vi.mock("./RequirementPlanEvidencePanel", () => ({
  RequirementPlanEvidencePanel: () => null,
}));
vi.mock("./RequirementActionEvidencePanel", () => ({
  RequirementActionEvidencePanel: () => null,
}));

const shortIdentity = (identity: string) => `${identity.slice(0, 8)}…${identity.slice(-4)}`;

function WorkspacePair({
  lane,
  onEvidenceChanged,
  run,
  sessionId,
  suffix,
  trajectory,
}: {
  lane: CheckpointTransportLane;
  onEvidenceChanged: () => void;
  run: ModelEnsembleRun;
  sessionId: string;
  suffix: "a" | "b";
  trajectory: ModelEnsembleTrajectoryPage;
}) {
  const history = {
    points: trajectory.points,
    headRunId: trajectory.head_run_id,
    selectedRunId: trajectory.head_run_id,
    onSelectRun: vi.fn(),
  };
  const shared = {
    attemptStages: checkpointStages(suffix),
    history,
    lensId: "task-framing" as const,
    onLensChange: vi.fn(),
    run,
    runId: run.run_id,
    snapshotLabel: "Sealed synthetic checkpoint",
    stageRun: run,
    transport: lane.transport,
  };
  return (
    <>
      <div data-testid="full-workspace-host">
        <MetricWorkspace
          {...shared}
          evidenceEnabled
          evidenceSessionId={sessionId}
          mode="full"
          onEvidenceChanged={onEvidenceChanged}
        />
      </div>
      <div data-testid="compact-workspace-host">
        <MetricWorkspace {...shared} mode="compact" />
      </div>
    </>
  );
}

function withoutGenericEvidence(transport: PromptEnhancerTransport): PromptEnhancerTransport {
  return {
    ...transport,
    previewAgentMetricEvidence: undefined,
    importAgentMetricEvidence: undefined,
    listMetricLifecycleProposals: undefined,
    decideMetricLifecycleProposal: undefined,
  };
}

describe("UI-03 through UI-07 synthetic integration tour", () => {
  it("connects the canonical shell to sealed metric, help, history, stage, and generic-evidence actions", async () => {
    const run = checkpointRun(CHECKPOINT_RUN_A, "a");
    const head = checkpointHead(run, CHECKPOINT_SESSION_A, "a");
    const trajectory = checkpointTrajectory(run, head.watch.watch_id, "c".repeat(64));
    const lane = checkpointTransport({
      run,
      head,
      trajectory,
      sessionId: CHECKPOINT_SESSION_A,
      suffix: "a",
    });

    render(
      <ModelEnsemblePanel
        analysisCapability={CHECKPOINT_CAPABILITY}
        category="prompt-quality"
        projectId={CHECKPOINT_PROJECT_ID}
        providerCompatibility={CHECKPOINT_COMPATIBILITY}
        sessionId={CHECKPOINT_SESSION_A}
        transport={lane.transport}
      />,
    );

    expect(screen.getByRole("heading", {
      level: 2,
      name: /measure the analyzed window, then estimate every eligible axis locally/i,
    })).toBeVisible();
    expect(await screen.findByRole("heading", {
      level: 3,
      name: `Metric workspace · Snapshot ${shortIdentity(run.run_id)}`,
    })).toBeVisible();
    expect(screen.getByText("Sealed source window")).toBeVisible();
    expect(screen.getByRole("img", { name: /task framing typed local metric radar with fixed axes/i })).toBeVisible();

    const exactBoard = screen.getByRole("region", {
      name: /task framing · exact metric values/i,
    });
    fireEvent.click(within(exactBoard).getByRole("button", {
      name: /task definition coverage/i,
    }));
    const knowledgeCard = screen.getByRole("region", {
      name: /task definition coverage knowledge card/i,
    });
    expect(within(knowledgeCard).getByRole("region", { name: "Current metric guidance" })).toBeVisible();
    expect(knowledgeCard).toHaveTextContent("Scope");

    const models = screen.getByText("Models").closest("details");
    expect(models).not.toBeNull();
    fireEvent.click(within(models!).getByText("Models"));
    expect(within(models!).getAllByText("Latest durable attempt")).toHaveLength(2);
    expect(within(models!).getByText("not recorded · unload receipt missing")).toBeVisible();

    const history = screen.getByText("History").closest("details");
    expect(history).not.toBeNull();
    fireEvent.click(within(history!).getByText("History"));
    expect(
      await within(history!).findByText("1 of 2 loaded snapshots have a numeric receipt.", { exact: false }),
    ).toBeVisible();
    expect(within(history!).getByRole("img", { name: "Selected metric history" })).toHaveAttribute(
      "data-numeric-count",
      "1",
    );
    expect(within(history!).getByText("State only · No record")).toBeVisible();

    const evidence = await screen.findByRole("region", { name: "Import agent metric evidence" });
    await waitFor(() => {
      expect(within(evidence).getByRole("button", { name: "Confirm evidence" })).toBeEnabled();
    });
    fireEvent.change(within(evidence).getByLabelText("Choose canonical evidence file"), {
      target: { files: [checkpointFile("a")] },
    });
    expect(await within(evidence).findByRole("region", { name: "Strict local preview" })).toBeVisible();
    fireEvent.click(within(evidence).getByRole("button", { name: "Import as unconfirmed" }));
    await waitFor(() => expect(lane.importEvidence).toHaveBeenCalledTimes(1));
    fireEvent.click(within(evidence).getAllByRole("button", { name: "Confirm evidence" })[0]);
    fireEvent.click(within(evidence).getByRole("button", { name: "Apply confirmation" }));
    await waitFor(() => expect(lane.decideProposal).toHaveBeenCalledTimes(1));
    expect(within(evidence).getByText(/evidence confirmed for this sealed run/i)).toBeVisible();
    expect(lane.listProposals).toHaveBeenCalledWith(
      CHECKPOINT_SESSION_A,
      expect.any(AbortSignal),
    );
    expect(lane.previewEvidence).toHaveBeenCalledWith(
      CHECKPOINT_SESSION_A,
      expect.anything(),
      expect.any(AbortSignal),
    );
    expect(lane.previewEvidence.mock.calls[0][1]).toHaveProperty("byteLength");
    expect(lane.decideProposal).toHaveBeenCalledWith(
      CHECKPOINT_SESSION_A,
      expect.any(String),
      expect.objectContaining({
        decision: "confirm",
        expected_source_run_id: run.run_id,
      }),
      expect.any(String),
      expect.any(AbortSignal),
    );
    expect(lane.getHead).toHaveBeenCalledWith(CHECKPOINT_SESSION_A, expect.any(AbortSignal));
    expect(lane.getSnapshot).toHaveBeenCalledWith(run.run_id, expect.any(AbortSignal));
    expect(lane.getTrajectory).toHaveBeenCalledWith(
      head.watch.watch_id,
      24,
      undefined,
      expect.any(AbortSignal),
    );
  });

  it("drops stale A state and actions synchronously across run and transport changes", async () => {
    const runA = checkpointRun(CHECKPOINT_RUN_A, "a");
    const headA = checkpointHead(runA, CHECKPOINT_SESSION_A, "a");
    const trajectoryA = checkpointTrajectory(runA, headA.watch.watch_id, "c".repeat(64));
    const laneA = checkpointTransport({
      run: runA,
      head: headA,
      trajectory: trajectoryA,
      sessionId: CHECKPOINT_SESSION_A,
      suffix: "a",
      proposalCount: 2,
    });
    const runB = checkpointRun(CHECKPOINT_RUN_B, "b");
    const headB = checkpointHead(runB, CHECKPOINT_SESSION_B, "b");
    const trajectoryB = checkpointTrajectory(runB, headB.watch.watch_id, "d".repeat(64));
    const laneB = checkpointTransport({
      run: runB,
      head: headB,
      trajectory: trajectoryB,
      sessionId: CHECKPOINT_SESSION_B,
      suffix: "b",
    });
    const lanePresenceUnavailable = checkpointTransport({
      run: runB,
      head: headB,
      trajectory: trajectoryB,
      sessionId: CHECKPOINT_SESSION_B,
      suffix: "b",
      confirmationAvailable: false,
    });
    const onEvidenceChanged = vi.fn();
    const view = render(
      <WorkspacePair
        lane={laneA}
        onEvidenceChanged={onEvidenceChanged}
        run={runA}
        sessionId={CHECKPOINT_SESSION_A}
        suffix="a"
        trajectory={trajectoryA}
      />,
    );

    const fullA = screen.getByTestId("full-workspace-host");
    const compactA = screen.getByTestId("compact-workspace-host");
    await waitFor(() => {
      expect(within(fullA).getAllByRole("button", { name: "Confirm evidence" })).toHaveLength(2);
    });
    fireEvent.click(within(fullA).getAllByRole("button", { name: "Confirm evidence" })[0]);
    fireEvent.click(within(fullA).getByRole("button", { name: "Apply confirmation" }));
    await waitFor(() => {
      expect(laneA.decideProposal).toHaveBeenCalledTimes(1);
      expect(onEvidenceChanged).toHaveBeenCalledTimes(1);
    });

    const boardA = within(fullA).getByRole("region", { name: /task framing · exact metric values/i });
    fireEvent.click(within(boardA).getByRole("button", { name: /task definition coverage/i }));
    expect(within(fullA).getByRole("region", { name: /task definition coverage knowledge card/i })).toBeVisible();

    const fullModelsA = within(fullA).getByText("Models").closest("details")!;
    const compactModelsA = within(compactA).getByText("Models").closest("details")!;
    const fullHistoryA = within(fullA).getByText("History").closest("details")!;
    const compactHistoryA = within(compactA).getByText("History").closest("details")!;
    for (const disclosure of [fullModelsA, compactModelsA, fullHistoryA, compactHistoryA]) {
      fireEvent.click(disclosure.querySelector("summary")!);
    }
    expect(within(fullModelsA).getByText("example-org/factor-a")).toBeVisible();

    fireEvent.change(within(fullA).getByLabelText("Choose canonical evidence file"), {
      target: { files: [checkpointFile("a")] },
    });
    expect(await within(fullA).findByRole("region", { name: "Strict local preview" })).toBeVisible();
    const staleImportA = within(fullA).getByRole("button", { name: "Import as unconfirmed" });
    fireEvent.click(within(fullA).getByRole("button", { name: "Confirm evidence" }));
    const staleDecisionA = within(fullA).getByRole("button", { name: "Apply confirmation" });

    view.rerender(
      <WorkspacePair
        lane={laneB}
        onEvidenceChanged={onEvidenceChanged}
        run={runB}
        sessionId={CHECKPOINT_SESSION_B}
        suffix="b"
        trajectory={trajectoryB}
      />,
    );

    const fullB = screen.getByTestId("full-workspace-host");
    const compactB = screen.getByTestId("compact-workspace-host");
    expect(within(fullB).queryByRole("region", { name: /task definition coverage knowledge card/i })).not.toBeInTheDocument();
    expect(within(fullB).queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
    expect(within(fullB).queryByRole("button", { name: "Apply confirmation" })).not.toBeInTheDocument();
    expect(within(fullB).queryByText("example-agent-a", { exact: false })).not.toBeInTheDocument();
    expect(within(fullB).queryByText("example-org/factor-a")).not.toBeInTheDocument();
    expect(within(fullB).getByText("example-org/factor-b")).toBeVisible();
    expect(within(fullB).getByText(`run ${shortIdentity(runB.run_id)}`)).toBeVisible();
    fireEvent.click(staleImportA);
    fireEvent.click(staleDecisionA);
    expect(laneA.importEvidence).not.toHaveBeenCalled();
    expect(laneA.decideProposal).toHaveBeenCalledTimes(1);

    const fullSummaryB = within(fullB).getByLabelText("20-contract receipt summary");
    const compactSummaryB = within(compactB).getByLabelText("20-contract receipt summary");
    expect(compactSummaryB).toHaveTextContent(fullSummaryB.textContent ?? "");
    expect(within(fullB).getByText("Models").parentElement?.textContent).toBe(
      within(compactB).getByText("Models").parentElement?.textContent,
    );
    expect(within(fullB).getByText("History").parentElement?.textContent).toBe(
      within(compactB).getByText("History").parentElement?.textContent,
    );
    const unknownValue = fullB.querySelector('[data-status="unknown"]');
    expect(unknownValue).not.toBeNull();
    expect(unknownValue).toHaveTextContent("Unknown");
    expect(unknownValue).not.toHaveTextContent("0%");

    await waitFor(() => {
      expect(within(fullB).getByRole("button", { name: "Confirm evidence" })).toBeEnabled();
    });
    fireEvent.change(within(fullB).getByLabelText("Choose canonical evidence file"), {
      target: { files: [checkpointFile("b")] },
    });
    expect(await within(fullB).findByRole("region", { name: "Strict local preview" })).toBeVisible();
    const staleImportB = within(fullB).getByRole("button", { name: "Import as unconfirmed" });
    fireEvent.click(within(fullB).getByRole("button", { name: "Confirm evidence" }));
    const staleDecisionB = within(fullB).getByRole("button", { name: "Apply confirmation" });

    view.rerender(
      <WorkspacePair
        lane={lanePresenceUnavailable}
        onEvidenceChanged={onEvidenceChanged}
        run={runB}
        sessionId={CHECKPOINT_SESSION_B}
        suffix="b"
        trajectory={trajectoryB}
      />,
    );
    expect(within(fullB).queryByRole("region", { name: "Strict local preview" })).not.toBeInTheDocument();
    expect(within(fullB).queryByRole("button", { name: "Apply confirmation" })).not.toBeInTheDocument();
    fireEvent.click(staleImportB);
    fireEvent.click(staleDecisionB);
    expect(laneB.importEvidence).not.toHaveBeenCalled();
    expect(laneB.decideProposal).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(within(fullB).getByText(/native user-presence confirmation is unavailable/i)).toBeVisible();
      expect(within(fullB).getByRole("button", { name: "Confirm evidence" })).toBeDisabled();
    });

    view.rerender(
      <WorkspacePair
        lane={{
          ...lanePresenceUnavailable,
          transport: withoutGenericEvidence(lanePresenceUnavailable.transport),
        }}
        onEvidenceChanged={onEvidenceChanged}
        run={runB}
        sessionId={CHECKPOINT_SESSION_B}
        suffix="b"
        trajectory={trajectoryB}
      />,
    );
    expect(within(fullB).getByText(/does not expose the reviewed evidence-file boundary/i)).toBeVisible();
    expect(within(fullB).queryByLabelText("Choose canonical evidence file")).not.toBeInTheDocument();
  });
});
