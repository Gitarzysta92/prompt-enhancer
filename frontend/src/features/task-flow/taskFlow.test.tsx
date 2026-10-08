import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AnalysisRun, PromptEnhancerTransport } from "../../shared/api/contracts";
import {
  SYNTHETIC_CANDIDATES,
  SYNTHETIC_RUN,
  SYNTHETIC_TASK_LIFECYCLES,
  SYNTHETIC_TASKS,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { TaskFlowPage } from "./TaskFlowPage";
import { TaskFlowCard } from "./TaskFlowBoard";
import { TaskFlowSummary } from "./TaskFlowSummary";
import { projectTaskFlow, taskFlowTimelineScale, timelinePosition } from "./taskFlowAdapter";
import { applyTaskFlowFilters, DEFAULT_TASK_FLOW_FILTERS } from "./taskFlowModel";

const completeIndex = { analysisIndexEnded: true, lifecycleIndexEnded: true } as const;

describe("projectTaskFlow", () => {
  it("keeps proposals, explicit review receipts, and confirmed revisions distinct", () => {
    const items = projectTaskFlow(
      { candidates: SYNTHETIC_CANDIDATES, tasks: SYNTHETIC_TASKS, lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [SYNTHETIC_RUN] },
      completeIndex,
    );
    expect(items.map((item) => [item.kind, item.column])).toEqual([
      ["candidate", "reviewed"],
      ["confirmed", "in_progress"],
      ["candidate", "proposed"],
      ["candidate", "proposed"],
    ]);
    const proposal = items.find((item) => item.column === "proposed")!;
    expect(proposal.lifecycle).toEqual({
      source: "discovery_candidate",
      status: "undecided",
      label: "Detected grouping · explicit review required",
    });
    expect(proposal.analysis.state).toBe("not_applicable");
    expect(proposal.route).toEqual({ name: "discovery" });

    const reviewed = items.find((item) => item.column === "reviewed")!;
    expect(reviewed.lifecycle.status).toBe("accept");
    expect(reviewed.decisionId).toBe(SYNTHETIC_CANDIDATES[2].decision_id);

    const revision = items.find((item) => item.kind === "confirmed")!;
    expect(revision.column).toBe("in_progress");
    expect(revision.lifecycle).toEqual({
      source: "task_revision",
      status: "confirmed",
      label: "Raw revision state · Confirmed",
    });
    expect(revision.analysis.state).toBe("completed");
    expect(revision.analysis.runs).toHaveLength(1);
    expect(revision.taskStartedAt).toBe("2040-01-01T14:05:20Z");
    expect(revision.taskFinishedAt).toBeNull();
    expect(revision.provenance.fingerprint).toBe(SYNTHETIC_TASKS[0].input_fingerprint);
  });

  it("never promotes analysis completion, failure, or a hostile lifecycle token into work state", () => {
    const task = { ...SYNTHETIC_TASKS[0], lifecycle_state: "done" };
    const completed = projectTaskFlow(
      { candidates: [], tasks: [task], lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [SYNTHETIC_RUN] },
      completeIndex,
    )[0];
    expect(completed.column).toBe("in_progress");
    expect(completed.lifecycle.status).toBe("done");
    expect(completed.analysis.state).toBe("completed");

    const failedRun: AnalysisRun = {
      ...SYNTHETIC_RUN,
      status: "failed",
      failure_code: "example_failure",
      finished_at: "2040-01-01T14:06:03Z",
    };
    const failed = projectTaskFlow(
      { candidates: [], tasks: [task], lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [failedRun] },
      completeIndex,
    )[0];
    expect(failed.column).toBe("in_progress");
    expect(failed.analysis.state).toBe("failed");
    expect(failed.taskFinishedAt).toBeNull();
  });

  it("keeps every matching run and reports the newest run without erasing older facts", () => {
    const older = { ...SYNTHETIC_RUN, started_at: "2040-01-01T14:06:00Z", finished_at: "2040-01-01T14:06:02Z" };
    const newer: AnalysisRun = {
      ...SYNTHETIC_RUN,
      run_id: "f".repeat(64),
      status: "running",
      started_at: "2040-01-01T15:00:00Z",
      finished_at: null,
      failure_code: null,
    };
    const item = projectTaskFlow(
      { candidates: [], tasks: SYNTHETIC_TASKS, lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [newer, older] },
      completeIndex,
    )[0];
    expect(item.analysis.state).toBe("running");
    expect(item.analysis.runs.map((run) => run.status)).toEqual(["completed", "running"]);
    expect(item.column).toBe("in_progress");
  });

  it("distinguishes a proven run-index end, an incomplete index, and fingerprint mismatch", () => {
    const mismatched = { ...SYNTHETIC_RUN, input_fingerprint: "f".repeat(64) };
    const knownAbsence = projectTaskFlow(
      { candidates: [], tasks: SYNTHETIC_TASKS, lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [mismatched] },
      { analysisIndexEnded: true, lifecycleIndexEnded: true },
    )[0];
    expect(knownAbsence.analysis.state).toBe("not_observed");
    expect(knownAbsence.analysis.runs).toEqual([]);

    const incomplete = projectTaskFlow(
      { candidates: [], tasks: SYNTHETIC_TASKS, lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [] },
      { analysisIndexEnded: false, lifecycleIndexEnded: true },
    )[0];
    expect(incomplete.analysis.state).toBe("unknown");
    expect(incomplete.analysis.detail).toMatch(/did not prove its end/i);
  });

  it("places a human rejection in its own column without implying a successor", () => {
    const rejected = {
      ...SYNTHETIC_CANDIDATES[0],
      decision_status: "decided" as const,
      decision_id: "e".repeat(64),
      decision_action: "reject" as const,
    };
    const [item] = projectTaskFlow({ candidates: [rejected], tasks: [], lifecycles: [], runs: [] }, completeIndex);
    expect(item.column).toBe("rejected");
    expect(item.kind).toBe("candidate");
    expect(item.route).toEqual({ name: "discovery" });
  });

  it("keeps a decided proposal with no exposed action out of every outcome column", async () => {
    const missingAction = {
      ...SYNTHETIC_CANDIDATES[0],
      decision_status: "decided" as const,
      decision_id: null,
      decision_action: null,
    };
    const [item] = projectTaskFlow({ candidates: [missingAction], tasks: [], lifecycles: [], runs: [] }, completeIndex);
    expect(item.column).toBe("decided_unknown");
    expect(item.column).not.toBe("reviewed");
    expect(item.column).not.toBe("rejected");
    expect(item.lifecycle.label).toContain("action not exposed");

    render(<TaskFlowSummary decisionAudits={new Map()} total={1} visible={[item]} />);
    expect(screen.getByRole("region", { name: "Task flow compact summary" })).toHaveTextContent("Accepted / merged / split0");
    expect(screen.getByRole("region", { name: "Task flow compact summary" })).toHaveTextContent("Decision action unknown1");

    const getCandidateDecisions = vi.fn(async () => ({
      candidate_id: item.sourceId,
      decisions: [],
    }));
    const onDecisionsLoaded = vi.fn();
    const card = render(
      <TaskFlowCard
        allItems={[item]}
        decisionAudits={new Map()}
        item={item}
        onDecisionsLoaded={onDecisionsLoaded}
        onLifecycleChanged={() => undefined}
        onOpen={() => undefined}
        transport={{ ...createSyntheticTransport(), getCandidateDecisions }}
      />,
    );
    expect(card.container).toHaveTextContent("Decision recorded · receipt identifier not exposed");
    expect(card.container).not.toHaveTextContent("No review decision recorded");
    expect(card.container).not.toHaveTextContent("Not confirmed");
    const audit = card.container.querySelector("details.task-flow-audit")!;
    fireEvent.click(audit.querySelector("summary")!);
    expect(audit).toHaveTextContent("The receipt is unknown, not absent");
    expect(audit).not.toHaveTextContent("No accept, reject, merge, or split receipt exists");
    await waitFor(() => expect(getCandidateDecisions).toHaveBeenCalledWith(
      item.sourceId,
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(onDecisionsLoaded).toHaveBeenCalledWith(item.sourceId, []));
  });

  it("filters both projections from one exact filter set", () => {
    const items = projectTaskFlow(
      { candidates: SYNTHETIC_CANDIDATES, tasks: SYNTHETIC_TASKS, lifecycles: SYNTHETIC_TASK_LIFECYCLES, runs: [SYNTHETIC_RUN] },
      completeIndex,
    );
    expect(applyTaskFlowFilters(items, DEFAULT_TASK_FLOW_FILTERS)).toHaveLength(4);
    expect(applyTaskFlowFilters(items, { ...DEFAULT_TASK_FLOW_FILTERS, kind: "confirmed" })).toHaveLength(1);
    expect(applyTaskFlowFilters(items, { ...DEFAULT_TASK_FLOW_FILTERS, analysis: "completed" })).toHaveLength(1);
    expect(applyTaskFlowFilters(items, { ...DEFAULT_TASK_FLOW_FILTERS, column: "reviewed" })).toHaveLength(1);
    expect(applyTaskFlowFilters(items, { ...DEFAULT_TASK_FLOW_FILTERS, projectId: "0".repeat(64) })).toHaveLength(0);
  });

  it("builds chronology only from explicit valid event timestamps", () => {
    const scale = taskFlowTimelineScale([
      { occurredAt: "2040-01-01T14:00:00Z" },
      { occurredAt: "2040-01-02T10:15:00Z" },
      { occurredAt: null },
      { occurredAt: "not-a-time" },
    ])!;
    expect(scale.start).toBe(new Date("2040-01-01T14:00:00Z").getTime());
    expect(scale.end).toBe(new Date("2040-01-02T10:15:00Z").getTime());
    expect(scale.ticks).toHaveLength(5);
    expect(timelinePosition(scale, "2040-01-01T14:00:00Z")).toBe(0);
    expect(timelinePosition(scale, "2040-01-02T10:15:00Z")).toBe(1);
    expect(timelinePosition(scale, "not a date")).toBeNull();
    expect(taskFlowTimelineScale([])).toBeNull();
  });
});

describe("TaskFlowPage", () => {
  it("renders evidence-neutral columns, compact truth summary, and exact chronology", async () => {
    const navigate = vi.fn();
    render(<TaskFlowPage navigate={navigate} runtimeMode="synthetic_demo" transport={createSyntheticTransport()} />);
    const board = await screen.findByRole("group", { name: "Task flow board" });
    expect(within(board).getByRole("region", { name: "Confirmed work board" })).toBeVisible();
    expect(within(board).getByRole("region", { name: "Proposal review ledger" })).toBeVisible();
    const columns = Array.from(board.querySelectorAll<HTMLElement>(".task-flow-column"));
    expect(columns.map((column) => column.getAttribute("data-column"))).toEqual([
      "work_unknown",
      "backlog",
      "in_progress",
      "done",
      "historical",
      "unreconciled",
      "proposed",
      "reviewed",
      "rejected",
      "decided_unknown",
    ]);
    const proposed = within(board).getByRole("region", { name: "Proposed groupings" });
    const inProgress = within(board).getByRole("region", { name: "In progress" });
    const reviewed = within(board).getByRole("region", { name: "Accepted · merged · split" });
    expect(within(proposed).getAllByRole("article")).toHaveLength(2);
    expect(within(inProgress).getAllByRole("article")).toHaveLength(1);
    expect(within(reviewed).getAllByRole("article")).toHaveLength(1);
    expect(within(board).getByRole("region", { name: "Done" })).toHaveTextContent(/Nothing in this column/);
    expect(within(board).getByRole("region", { name: "Work state unknown" })).toHaveTextContent(/Nothing in this column/);
    expect(screen.getByRole("note", { name: "Fictional synthetic demo" })).toBeVisible();

    const summary = screen.getByRole("region", { name: "Task flow compact summary" });
    expect(summary).toHaveTextContent("Explicit local receipts only");
    expect(summary).toHaveTextContent("In progress1");
    expect(summary).toHaveTextContent("0 team-sourced records · 0 remote-synced records");
    expect(summary).toHaveTextContent("1 completed · 0 running · 0 failed");

    expect(screen.getByRole("region", { name: "Proposal & explicit review records" }).getElementsByTagName("button")).toHaveLength(3);
    expect(screen.getByRole("region", { name: "Confirmed revision records" }).getElementsByTagName("button")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Explicit task lifecycle receipts" }).getElementsByTagName("button")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Analysis events (not task lifecycle)" }).getElementsByTagName("button")).toHaveLength(2);
    expect(screen.getByText(/Lifecycle points are server receipt times/)).toBeVisible();

    const resetFilters = screen.getByRole("button", { name: "Reset filters" });
    expect(resetFilters).toBeDisabled();
    expect(resetFilters).toHaveAccessibleDescription("Filters already use their defaults.");

    fireEvent.change(screen.getByRole("combobox", { name: "Kind" }), { target: { value: "confirmed" } });
    expect(within(proposed).queryAllByRole("article")).toHaveLength(0);
    expect(within(inProgress).getAllByRole("article")).toHaveLength(1);
    expect(document.querySelector(".count-summary")?.textContent).toBe("0 proposal records · 1 confirmed revisions · current filters");
    expect(resetFilters).toBeEnabled();
    expect(resetFilters).toHaveAccessibleDescription("Reset every task-flow filter to its default.");
    fireEvent.click(resetFilters);
    expect(within(proposed).getAllByRole("article")).toHaveLength(2);

    fireEvent.click(within(inProgress).getByRole("button", { name: /Open revision/ }));
    expect(navigate).toHaveBeenCalledWith({ name: "task", taskId: SYNTHETIC_TASKS[0].task_id, revision: 1 });
  });

  it("loads immutable decision audit only on demand and adds its exact decision event", async () => {
    const base = createSyntheticTransport();
    const getCandidateDecisions = vi.spyOn(base, "getCandidateDecisions");
    render(<TaskFlowPage navigate={() => undefined} runtimeMode="synthetic_demo" transport={base} />);
    const reviewed = await screen.findByRole("region", { name: "Accepted · merged · split" });
    expect(getCandidateDecisions).not.toHaveBeenCalled();
    const audit = within(reviewed).getByText("Immutable review audit").closest("details")!;
    fireEvent.click(audit.querySelector("summary")!);

    expect(await within(audit).findByRole("list", { name: "Immutable review decisions" })).toBeVisible();
    expect(within(audit).getByText("444444...4444")).toBeVisible();
    expect(audit).toHaveTextContent("Output revision 1");
    expect(getCandidateDecisions).toHaveBeenCalledTimes(1);
    expect(getCandidateDecisions.mock.calls[0][0]).toBe(SYNTHETIC_CANDIDATES[2].candidate.candidate_id);
    expect(getCandidateDecisions.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    await waitFor(() => {
      expect(screen.getByRole("region", { name: "Proposal & explicit review records" }).getElementsByTagName("button")).toHaveLength(4);
    });
    expect(screen.getByRole("region", { name: "Task flow compact summary" })).toHaveTextContent("Audit receipts loaded1");
  });

  it("shows append-only lifecycle receipts beside immutable revisions and analysis", async () => {
    render(<TaskFlowPage navigate={() => undefined} runtimeMode="synthetic_demo" transport={createSyntheticTransport()} />);
    const confirmed = await screen.findByRole("region", { name: "In progress" });
    const audit = within(confirmed).getByText("Lifecycle, revision & analysis audit").closest("details")!;
    fireEvent.click(audit.querySelector("summary")!);
    expect(within(audit).getByText(/In-progress receipt/)).toBeVisible();
    expect(within(audit).getByRole("list", { name: "Immutable task lifecycle receipts" })).toBeVisible();
    expect(within(audit).getByRole("list", { name: "Immutable task revision history" })).toBeVisible();
    expect(within(audit).getByText(/Completed · started/)).toBeVisible();
    expect(within(audit).getByText(/corrections append a superseding receipt/)).toBeVisible();
  });

  it("keeps full pseudonyms and session membership out of visible text", async () => {
    const { container } = render(
      <TaskFlowPage navigate={() => undefined} runtimeMode="synthetic_demo" transport={createSyntheticTransport()} />,
    );
    await screen.findByRole("group", { name: "Task flow board" });
    expect(container.textContent).not.toMatch(/\b[0-9a-f]{64}\b/u);
    expect(container.textContent).not.toContain(SYNTHETIC_TASKS[0].session_ids[0]);
  });

  it("stamps a true local exact-zero surface without synthetic provenance", async () => {
    const localTransport: Pick<
      PromptEnhancerTransport,
      | "listCandidates"
      | "listTaskRevisions"
      | "listTaskLifecycles"
      | "listAnalysisRuns"
      | "getCandidateDecisions"
      | "transitionTaskLifecycle"
      | "correctTaskLifecycle"
    > = {
      async listCandidates(_status, _signal, page) {
        return { candidates: [], limit: page?.limit ?? 100, offset: page?.offset ?? 0 };
      },
      async listTaskRevisions(_taskId, _signal, page) {
        return { tasks: [], limit: page?.limit ?? 100, offset: page?.offset ?? 0 };
      },
      async listAnalysisRuns(_taskId, _signal, page) {
        return { runs: [], limit: page?.limit ?? 100, offset: page?.offset ?? 0 };
      },
      async listTaskLifecycles(_signal, page) {
        return { lifecycles: [], limit: page?.limit ?? 100, offset: page?.offset ?? 0 };
      },
      async getCandidateDecisions(candidateId) {
        return { candidate_id: candidateId, decisions: [] };
      },
      async transitionTaskLifecycle() {
        throw new Error("No local task lifecycle exists");
      },
      async correctTaskLifecycle() {
        throw new Error("No local task lifecycle exists");
      },
    };
    render(<TaskFlowPage navigate={() => undefined} runtimeMode="local_real" transport={localTransport} />);
    expect(await screen.findByText(/Local indexes loaded 0 candidates · 0 tasks · 0 lifecycles · 0 runs/)).toBeVisible();
    expect(screen.getByRole("region", { name: "Task flow compact summary" })).toHaveTextContent("0 team-sourced records · 0 remote-synced records");
    expect(screen.queryByText(/Synthetic fixture indexes loaded/)).toBeNull();
  });

  it("never leaves retained task records mounted after a failed source reload", async () => {
    const success = createSyntheticTransport();
    const failure = new Error("Synthetic Task Flow reload failure");
    const failed: typeof success = {
      ...success,
      listCandidates: async () => { throw failure; },
      listTaskRevisions: async () => { throw failure; },
      listAnalysisRuns: async () => { throw failure; },
    };
    const view = render(<TaskFlowPage navigate={() => undefined} runtimeMode="local_real" transport={success} />);
    expect(await screen.findByRole("group", { name: "Task flow board" })).toBeVisible();
    view.rerender(<TaskFlowPage navigate={() => undefined} runtimeMode="local_real" transport={failed} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(failure.message);
    expect(screen.queryByRole("group", { name: "Task flow board" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Task flow compact summary" })).toBeNull();
  });
});
