import { describe, expect, it, vi } from "vitest";
import type {
  AnalysisRun,
  CandidateListItem,
  ContentFreeListPage,
  TaskLifecycleSnapshot,
  TaskRevision,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_CANDIDATES,
  SYNTHETIC_RUN,
  SYNTHETIC_TASK_LIFECYCLES,
  SYNTHETIC_TASKS,
} from "../../shared/api/syntheticFixtures";
import { projectTaskFlow } from "./taskFlowAdapter";
import { loadTaskFlowSources } from "./taskFlowLoader";

function page<T>(values: readonly T[], request: ContentFreeListPage) {
  return {
    values: values.slice(request.offset, request.offset + request.limit),
    limit: request.limit,
    offset: request.offset,
  };
}

function transportFor({
  candidates = [],
  tasks = [],
  lifecycles = [],
  runs = [],
}: {
  candidates?: readonly CandidateListItem[];
  tasks?: readonly TaskRevision[];
  lifecycles?: readonly TaskLifecycleSnapshot[];
  runs?: readonly AnalysisRun[];
}) {
  return {
    listCandidates: vi.fn(async (_status, _signal, request: ContentFreeListPage) => {
      const result = page(candidates, request);
      return { candidates: result.values, limit: result.limit, offset: result.offset };
    }),
    listTaskRevisions: vi.fn(async (_taskId, _signal, request: ContentFreeListPage) => {
      const result = page(tasks, request);
      return { tasks: result.values, limit: result.limit, offset: result.offset };
    }),
    listTaskLifecycles: vi.fn(async (_signal, request: ContentFreeListPage) => {
      const result = page(lifecycles, request);
      return { lifecycles: result.values, limit: result.limit, offset: result.offset };
    }),
    listAnalysisRuns: vi.fn(async (_taskId, _signal, request: ContentFreeListPage) => {
      const result = page(runs, request);
      return { runs: result.values, limit: result.limit, offset: result.offset };
    }),
  };
}

describe("Task Flow bounded pagination", () => {
  it("finds a matching analysis run beyond the former 100-record first page", async () => {
    const unrelated = Array.from({ length: 100 }, (_, index): AnalysisRun => ({
      ...SYNTHETIC_RUN,
      run_id: (index + 10).toString(16).padStart(64, "0"),
      task_id: "d".repeat(64),
    }));
    const matching: AnalysisRun = {
      ...SYNTHETIC_RUN,
      run_id: "e".repeat(64),
    };
    const transport = transportFor({
      tasks: SYNTHETIC_TASKS,
      lifecycles: SYNTHETIC_TASK_LIFECYCLES,
      runs: [...unrelated, matching],
    });

    const result = await loadTaskFlowSources(
      transport,
      new AbortController().signal,
    );
    const [task] = projectTaskFlow(result, {
      analysisIndexEnded: result.receipts.find((receipt) => receipt.source === "runs")?.boundary === "page_end_observed",
      lifecycleIndexEnded: result.receipts.find((receipt) => receipt.source === "lifecycles")?.boundary === "page_end_observed",
    }).filter((item) => item.kind === "confirmed");

    expect(task.column).toBe("in_progress");
    expect(task.analysis.label).toBe("Latest analysis completed");
    expect(transport.listAnalysisRuns.mock.calls.map((call) => call[2]?.offset)).toEqual([0, 100]);
    expect(result.receipts.find((receipt) => receipt.source === "runs")).toMatchObject({
      loaded: 101,
      boundary: "page_end_observed",
    });
  });

  it("reports an exact incomplete boundary when a source reaches its cap", async () => {
    const candidates = Array.from({ length: 3 }, (_, index): CandidateListItem => ({
      ...SYNTHETIC_CANDIDATES[0],
      candidate: {
        ...SYNTHETIC_CANDIDATES[0].candidate,
        candidate_id: (index + 1).toString(16).padStart(64, "0"),
      },
    }));
    const result = await loadTaskFlowSources(
      transportFor({ candidates }),
      new AbortController().signal,
      { pageSize: 2, recordCap: 2 },
    );

    expect(result.candidates).toHaveLength(2);
    expect(result.receipts.find((receipt) => receipt.source === "candidates")).toEqual({
      source: "candidates",
      loaded: 2,
      records_seen: 2,
      page_size: 2,
      record_cap: 2,
      boundary: "cap_reached",
      duplicate_count: 0,
    });
    expect(result.consistency).toBe("non_atomic_multi_request");
  });

  it("marks a duplicated page boundary as unstable instead of claiming completeness", async () => {
    const first = SYNTHETIC_CANDIDATES[0];
    const second: CandidateListItem = {
      ...first,
      candidate: { ...first.candidate, candidate_id: "b".repeat(64) },
    };
    const result = await loadTaskFlowSources(
      transportFor({ candidates: [first, second, second] }),
      new AbortController().signal,
      { pageSize: 2, recordCap: 10 },
    );

    expect(result.candidates).toHaveLength(2);
    expect(result.receipts.find((receipt) => receipt.source === "candidates")).toMatchObject({
      boundary: "duplicate_observed",
      duplicate_count: 1,
      records_seen: 3,
    });
  });

  it("preserves both duplicate instability and the hard cap boundary", async () => {
    const first = SYNTHETIC_CANDIDATES[0];
    const second: CandidateListItem = {
      ...first,
      candidate: { ...first.candidate, candidate_id: "b".repeat(64) },
    };
    const result = await loadTaskFlowSources(
      transportFor({ candidates: [first, second, second] }),
      new AbortController().signal,
      { pageSize: 2, recordCap: 3 },
    );

    expect(result.receipts.find((receipt) => receipt.source === "candidates")).toMatchObject({
      boundary: "duplicate_and_cap_reached",
      duplicate_count: 1,
      records_seen: 3,
      record_cap: 3,
    });
  });
});
