import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AnalysisRun,
  AnalysisRunResponse,
  PromptEnhancerTransport,
  TaskRevisionResponse,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_RESULTS,
  SYNTHETIC_RUN,
  SYNTHETIC_TASKS,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { TaskDetail } from "./TaskDetail";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

describe("TaskDetail analysis lifecycle", () => {
  it("keeps one semantic route heading while a task revision loads or fails", async () => {
    const pending = deferred<TaskRevisionResponse>();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getTaskRevision: vi.fn(() => pending.promise),
      listAnalysisRuns: vi.fn(async () => ({ runs: [], limit: 100, offset: 0 })),
    };
    render(
      <TaskDetail
        navigate={vi.fn()}
        revision={1}
        taskId={"c".repeat(64)}
        transport={transport}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Task analysis" })).toBeVisible();
    expect(screen.getByText("Loading the selected immutable task revision and its analysis evidence.")).toBeVisible();

    await act(async () => {
      pending.reject(new Error("example-private-diagnostic"));
      await pending.promise.catch(() => undefined);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Task detail could not be loaded");
    expect(screen.getByRole("heading", { level: 1, name: "Task analysis" })).toBeVisible();
    expect(screen.getByText(/no task or analysis result is being inferred/i)).toBeVisible();
    expect(screen.queryByText(/example-private-diagnostic/)).not.toBeInTheDocument();
  });

  it("keeps the task and previous results available when an analysis request fails", async () => {
    const startAnalysis = vi.fn().mockRejectedValue(new Error("example-diagnostic-must-stay-hidden"));
    const transport = { ...createSyntheticTransport(), startAnalysis };
    render(<TaskDetail navigate={vi.fn()} revision={SYNTHETIC_RUN.task_revision} taskId={SYNTHETIC_RUN.task_id} transport={transport} />);

    await screen.findByText("Core Metadata Task - v3");
    fireEvent.click(screen.getByRole("button", { name: "Run latest pack" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm the analysis result");
    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
    expect(screen.getByText("Core Metadata Task - v3")).toBeVisible();
    expect(screen.queryByText(/example-diagnostic-must-stay-hidden/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload results" }));
    await screen.findByText("Core Metadata Task - v3");
    expect(startAnalysis).toHaveBeenCalledTimes(1);
  });

  it("ignores a task response from a previous route even when the transport ignores abort", async () => {
    const pending = deferred<TaskRevisionResponse>();
    const first = { ...SYNTHETIC_TASKS[0], task_type: "bug_fix" };
    const second = { ...first, task_id: "b".repeat(64), task_type: "documentation" };
    let firstSignal: AbortSignal | undefined;
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getTaskRevision: vi.fn((id, _revision, signal) => {
        if (id === first.task_id) { firstSignal = signal; return pending.promise; }
        return Promise.resolve({ task: second });
      }),
      listAnalysisRuns: vi.fn(async () => ({ runs: [], limit: 100, offset: 0 })),
    };
    const view = render(<TaskDetail navigate={vi.fn()} revision={first.revision} taskId={first.task_id} transport={transport} />);
    view.rerender(<TaskDetail navigate={vi.fn()} revision={second.revision} taskId={second.task_id} transport={transport} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Documentation" })).toBeVisible();
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => { pending.resolve({ task: first }); await pending.promise; });
    expect(screen.getByRole("heading", { level: 1, name: "Documentation" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Bug Fix" })).not.toBeInTheDocument();
  });

  it("ignores late run details and their errors after navigation", async () => {
    const pending = deferred<AnalysisRunResponse>();
    const first = SYNTHETIC_TASKS[0];
    const second = { ...first, task_id: "b".repeat(64), task_type: "documentation" };
    const getAnalysisRun = vi.fn(() => pending.promise);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getTaskRevision: vi.fn(async (id) => ({ task: id === first.task_id ? first : second })),
      listAnalysisRuns: vi.fn(async (id) => ({ runs: id === first.task_id ? [SYNTHETIC_RUN] : [], limit: 100, offset: 0 })),
      getAnalysisRun,
    };
    const view = render(<TaskDetail navigate={vi.fn()} revision={first.revision} taskId={first.task_id} transport={transport} />);
    await act(async () => { await Promise.resolve(); });
    expect(getAnalysisRun).toHaveBeenCalledTimes(1);
    view.rerender(<TaskDetail navigate={vi.fn()} revision={second.revision} taskId={second.task_id} transport={transport} />);
    await screen.findByRole("heading", { level: 1, name: "Documentation" });
    await act(async () => { pending.reject(new Error("example-late-error")); await pending.promise.catch(() => undefined); });
    expect(screen.getByRole("heading", { level: 1, name: "Documentation" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not reload the previous task when its analysis finishes after navigation", async () => {
    const pending = deferred<Awaited<ReturnType<PromptEnhancerTransport["startAnalysis"]>>>();
    const first = SYNTHETIC_TASKS[0];
    const second = { ...first, task_id: "b".repeat(64), task_type: "documentation" };
    const getTaskRevision = vi.fn(async (id: string) => ({ task: id === first.task_id ? first : second }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getTaskRevision,
      listAnalysisRuns: vi.fn(async () => ({ runs: [], limit: 100, offset: 0 })),
      startAnalysis: vi.fn(() => pending.promise),
    };
    const view = render(<TaskDetail navigate={vi.fn()} revision={first.revision} taskId={first.task_id} transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    view.rerender(<TaskDetail navigate={vi.fn()} revision={second.revision} taskId={second.task_id} transport={transport} />);
    await screen.findByRole("heading", { level: 1, name: "Documentation" });
    await act(async () => {
      pending.resolve({ run_id: "a".repeat(64), status: "completed", result_count: 0, applied: true });
      await pending.promise;
    });
    expect(getTaskRevision).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { level: 1, name: "Documentation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("can append a latest-pack run without replacing an existing run", async () => {
    const base = createSyntheticTransport();
    const oldRun: AnalysisRun = {
      ...SYNTHETIC_RUN,
      metric_pack_version: 2,
    };
    const currentRun: AnalysisRun = {
      ...SYNTHETIC_RUN,
      run_id: "a".repeat(64),
      metric_pack_version: 3,
      metric_engine_version: "task-deterministic-2",
      schema_version: 6,
      started_at: "2040-01-03T12:00:00Z",
      finished_at: "2040-01-03T12:00:02Z",
    };
    let latestPackStarted = false;
    const startAnalysis = vi.fn(async () => {
      latestPackStarted = true;
      return {
        run_id: currentRun.run_id,
        status: "completed" as const,
        result_count: SYNTHETIC_RESULTS.length,
        applied: true,
      };
    });
    const transport: PromptEnhancerTransport = {
      ...base,
      listAnalysisRuns: vi.fn(async () => ({
        runs: latestPackStarted ? [currentRun, oldRun] : [oldRun],
        limit: 100,
        offset: 0,
      })),
      getAnalysisRun: vi.fn(async (runId) => ({
        run: runId === currentRun.run_id ? currentRun : oldRun,
        results: SYNTHETIC_RESULTS,
      })),
      startAnalysis,
    };

    render(
      <TaskDetail
        navigate={vi.fn()}
        revision={oldRun.task_revision}
        taskId={oldRun.task_id}
        transport={transport}
      />,
    );

    expect(await screen.findByText("Core Metadata Task - v2")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Run latest pack" }));

    expect(await screen.findByText("Core Metadata Task - v3")).toBeVisible();
    expect(startAnalysis).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Core Metadata Task - v2")).not.toBeInTheDocument();
  });
});
