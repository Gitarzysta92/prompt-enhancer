import type {
  AnalysisRun,
  CandidateListItem,
  ContentFreeListPage,
  PromptEnhancerTransport,
  TaskLifecycleSnapshot,
  TaskRevision,
} from "../../shared/api/contracts";

export const TASK_FLOW_PAGE_SIZE = 100;
export const TASK_FLOW_RECORD_CAP_PER_SOURCE = 5_000;

export type TaskFlowSourceKey = "candidates" | "tasks" | "lifecycles" | "runs";
export type TaskFlowSourceBoundary =
  | "page_end_observed"
  | "cap_reached"
  | "duplicate_observed"
  | "duplicate_and_cap_reached";

export interface TaskFlowSourceReceipt {
  source: TaskFlowSourceKey;
  loaded: number;
  records_seen: number;
  page_size: number;
  record_cap: number;
  boundary: TaskFlowSourceBoundary;
  duplicate_count: number;
}
export interface TaskFlowLoadProgress {
  source: TaskFlowSourceKey;
  loaded: number;
  records_seen: number;
  record_cap: number;
}

export interface TaskFlowLoadResult {
  candidates: CandidateListItem[];
  tasks: TaskRevision[];
  lifecycles: TaskLifecycleSnapshot[];
  runs: AnalysisRun[];
  receipts: readonly TaskFlowSourceReceipt[];
  /** The four HTTP indexes are never represented as one atomic snapshot. */
  consistency: "non_atomic_multi_request";
}

type TaskFlowListTransport = Pick<
  PromptEnhancerTransport,
  "listCandidates" | "listTaskRevisions" | "listTaskLifecycles" | "listAnalysisRuns"
>;

interface PageResponse<T> {
  values: readonly T[];
  limit: number;
  offset: number;
}

interface LoadOptions {
  pageSize?: number;
  recordCap?: number;
  onProgress?: (progress: TaskFlowLoadProgress) => void;
}

function validateBounds(pageSize: number, recordCap: number): void {
  if (
    !Number.isInteger(pageSize)
    || pageSize < 1
    || pageSize > 100
    || !Number.isInteger(recordCap)
    || recordCap < pageSize
    || recordCap > TASK_FLOW_RECORD_CAP_PER_SOURCE
  ) {
    throw new Error("Task Flow pagination bounds are invalid");
  }
}

async function loadSource<T>(
  source: TaskFlowSourceKey,
  loadPage: (page: ContentFreeListPage) => Promise<PageResponse<T>>,
  identity: (value: T) => string,
  options: Required<Pick<LoadOptions, "pageSize" | "recordCap">> & Pick<LoadOptions, "onProgress">,
): Promise<{ values: T[]; receipt: TaskFlowSourceReceipt }> {
  const values: T[] = [];
  const identities = new Set<string>();
  let offset = 0;
  let duplicateCount = 0;
  let pageEndObserved = false;

  while (offset < options.recordCap) {
    const limit = Math.min(options.pageSize, options.recordCap - offset);
    const response = await loadPage({ limit, offset });
    if (
      response.limit !== limit
      || response.offset !== offset
      || response.values.length > limit
    ) {
      throw new Error(`Task Flow ${source} page contract was invalid`);
    }
    for (const value of response.values) {
      const key = identity(value);
      if (identities.has(key)) {
        duplicateCount += 1;
        continue;
      }
      identities.add(key);
      values.push(value);
    }
    offset += response.values.length;
    options.onProgress?.({
      source,
      loaded: values.length,
      records_seen: offset,
      record_cap: options.recordCap,
    });
    if (response.values.length < limit) {
      pageEndObserved = true;
      break;
    }
  }

  const capReached = !pageEndObserved && offset >= options.recordCap;
  const boundary: TaskFlowSourceBoundary = duplicateCount > 0
    ? capReached ? "duplicate_and_cap_reached" : "duplicate_observed"
    : pageEndObserved ? "page_end_observed" : "cap_reached";
  return {
    values,
    receipt: {
      source,
      loaded: values.length,
      records_seen: offset,
      page_size: options.pageSize,
      record_cap: options.recordCap,
      boundary,
      duplicate_count: duplicateCount,
    },
  };
}

/**
 * Traverse all four bounded content-free indexes. A short page proves only
 * that one index ended during its own request sequence, not one shared
 * point-in-time snapshot.
 */
export async function loadTaskFlowSources(
  transport: TaskFlowListTransport,
  signal: AbortSignal,
  options: LoadOptions = {},
): Promise<TaskFlowLoadResult> {
  const pageSize = options.pageSize ?? TASK_FLOW_PAGE_SIZE;
  const recordCap = options.recordCap ?? TASK_FLOW_RECORD_CAP_PER_SOURCE;
  validateBounds(pageSize, recordCap);
  const shared = { pageSize, recordCap, onProgress: options.onProgress };

  const [candidates, tasks, lifecycles, runs] = await Promise.all([
    loadSource(
      "candidates",
      async (page) => {
        const response = await transport.listCandidates("all", signal, page);
        return { values: response.candidates, limit: response.limit, offset: response.offset };
      },
      (item) => item.candidate.candidate_id,
      shared,
    ),
    loadSource(
      "tasks",
      async (page) => {
        const response = await transport.listTaskRevisions(undefined, signal, page);
        return { values: response.tasks, limit: response.limit, offset: response.offset };
      },
      (item) => `${item.task_id}:${item.revision}`,
      shared,
    ),
    loadSource(
      "lifecycles",
      async (page) => {
        const response = await transport.listTaskLifecycles(signal, page, 100);
        return { values: response.lifecycles, limit: response.limit, offset: response.offset };
      },
      (item) => `${item.task_id}:${item.task_revision}`,
      shared,
    ),
    loadSource(
      "runs",
      async (page) => {
        const response = await transport.listAnalysisRuns(undefined, signal, page);
        return { values: response.runs, limit: response.limit, offset: response.offset };
      },
      (item) => item.run_id,
      shared,
    ),
  ]);
  signal.throwIfAborted();
  return {
    candidates: candidates.values,
    tasks: tasks.values,
    lifecycles: lifecycles.values,
    runs: runs.values,
    receipts: [candidates.receipt, tasks.receipt, lifecycles.receipt, runs.receipt],
    consistency: "non_atomic_multi_request",
  };
}
