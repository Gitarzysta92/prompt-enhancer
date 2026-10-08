import type {
  Provider,
  TaskLifecycleEvent,
  TaskLifecycleState,
} from "../../shared/api/contracts";
import type { AppRoute } from "../../shared/platform/platform";

/** Discovery proposals and human-confirmed revisions are never interchangeable. */
export type TaskFlowKind = "candidate" | "confirmed";

export type TaskFlowColumnId =
  | "proposed"
  | "reviewed"
  | "rejected"
  | "decided_unknown"
  | "work_unknown"
  | "backlog"
  | "in_progress"
  | "done"
  | "historical"
  | "unreconciled";

export type TaskFlowColumnGroup = "work" | "review";

export interface TaskFlowColumn {
  id: TaskFlowColumnId;
  label: string;
  kind: TaskFlowKind;
  group: TaskFlowColumnGroup;
  description: string;
}

export const TASK_FLOW_COLUMNS: readonly TaskFlowColumn[] = [
  {
    id: "work_unknown",
    label: "Work state unknown",
    kind: "confirmed",
    group: "work",
    description: "The current revision has no effective explicit work-state receipt.",
  },
  {
    id: "backlog",
    label: "Backlog",
    kind: "confirmed",
    group: "work",
    description: "A local user explicitly placed the current revision in backlog.",
  },
  {
    id: "in_progress",
    label: "In progress",
    kind: "confirmed",
    group: "work",
    description: "A local user explicitly recorded work in progress.",
  },
  {
    id: "done",
    label: "Done",
    kind: "confirmed",
    group: "work",
    description: "A local user explicitly recorded done. Analysis never sets this state.",
  },
  {
    id: "historical",
    label: "Historical revisions",
    kind: "confirmed",
    group: "work",
    description: "Superseded immutable revisions; current work state is intentionally not projected here.",
  },
  {
    id: "unreconciled",
    label: "State not reconciled",
    kind: "confirmed",
    group: "work",
    description: "Separate bounded indexes did not yield a matching lifecycle snapshot.",
  },
  {
    id: "proposed",
    label: "Proposed groupings",
    kind: "candidate",
    group: "review",
    description: "Detected groupings awaiting an explicit human decision. They are not tasks.",
  },
  {
    id: "reviewed",
    label: "Accepted · merged · split",
    kind: "candidate",
    group: "review",
    description: "Reviewed proposal receipts. Their output revisions appear separately.",
  },
  {
    id: "rejected",
    label: "Rejected proposals",
    kind: "candidate",
    group: "review",
    description: "Explicitly rejected proposals. No successor task is implied.",
  },
  {
    id: "decided_unknown",
    label: "Decided · action unknown",
    kind: "candidate",
    group: "review",
    description: "A decision is reported, but its action is not exposed. No outcome is inferred.",
  },
];

export const TASK_FLOW_COLUMN_GROUPS: readonly {
  id: TaskFlowColumnGroup;
  label: string;
  description: string;
}[] = [
  {
    id: "work",
    label: "Confirmed work board",
    description: "Only explicit local-user lifecycle receipts place a current revision in backlog, in progress, or done.",
  },
  {
    id: "review",
    label: "Proposal review ledger",
    description: "Detected groupings and immutable human review outcomes remain separate from confirmed work state.",
  },
];

export type TaskFlowLifecycleSource =
  | "discovery_candidate"
  | "review_decision"
  | "task_revision";

export interface TaskFlowLifecycle {
  source: TaskFlowLifecycleSource;
  /** Raw status token from the source record (never renamed into a work state). */
  status: string;
  label: string;
}

export type TaskFlowWorkLifecycleAuthority =
  | "authoritative"
  | "historical_not_loaded"
  | "unreconciled";

export interface TaskFlowWorkLifecycle {
  authority: TaskFlowWorkLifecycleAuthority;
  currentState: TaskLifecycleState | null;
  label: string;
  currentTaskRevision: number | null;
  headEventId: string | null;
  eventCount: number | null;
  priorRevisionEventCount: number | null;
  events: readonly TaskLifecycleEvent[];
  eventsComplete: boolean;
}

export interface TaskFlowProvenance {
  origin: string;
  version: string;
  fingerprint: string;
  dataTier: string | null;
}

export type TaskFlowEvidenceState =
  | "observed_complete"
  | "observed_partial"
  | "not_observed"
  | "no_eligible"
  | "not_applicable";

export interface TaskFlowEvidenceFact {
  state: TaskFlowEvidenceState;
  label: string;
  detail: string;
}

export type TaskFlowAnalysisState =
  | "running"
  | "completed"
  | "failed"
  | "not_observed"
  | "unknown"
  | "not_applicable";

export interface TaskFlowAnalysisRunFact {
  runId: string;
  status: "running" | "completed" | "failed";
  startedAt: string;
  finishedAt: string | null;
  failureCode: string | null;
  provenance: TaskFlowProvenance;
}

export interface TaskFlowAnalysisFact {
  state: TaskFlowAnalysisState;
  label: string;
  detail: string;
  runs: readonly TaskFlowAnalysisRunFact[];
}

export interface TaskFlowItem {
  id: string;
  /** Pseudonymous candidate or task identity, retained for exact audit joins. */
  sourceId: string;
  kind: TaskFlowKind;
  column: TaskFlowColumnId;
  title: string;
  subtitle: string;
  projectId: string;
  /** Provider when the source record exposes it; task revisions do not. */
  provider: Provider | null;
  sessionCount: number;
  lifecycle: TaskFlowLifecycle;
  /** Explicit work-state receipts, kept separate from raw revision metadata. */
  workLifecycle: TaskFlowWorkLifecycle | null;
  provenance: TaskFlowProvenance;
  evidence: TaskFlowEvidenceFact;
  analysis: TaskFlowAnalysisFact;
  /** Creation time of this exact immutable record, not task start time. */
  occurredAt: string;
  /** Receipt time of the latest effective transition to in-progress, if proven. */
  taskStartedAt: string | null;
  /** Receipt time of the latest effective transition to done, if proven. */
  taskFinishedAt: string | null;
  decisionId: string | null;
  decisionAction: "accept" | "reject" | "merge" | "split" | null;
  /** Authoritative CandidateListItem decision_status, not inferred from nullable receipt fields. */
  reviewDecisionRecorded: boolean;
  confidence: number | null;
  coverage: number | null;
  route: AppRoute | null;
}

export interface TaskFlowFilters {
  kind: "all" | TaskFlowKind;
  column: "all" | TaskFlowColumnId;
  analysis: "all" | TaskFlowAnalysisState;
  projectId: "all" | string;
}

export const DEFAULT_TASK_FLOW_FILTERS: TaskFlowFilters = {
  kind: "all",
  column: "all",
  analysis: "all",
  projectId: "all",
};

export const TASK_FLOW_KIND_LABELS: Readonly<Record<TaskFlowKind, string>> = {
  candidate: "Proposal",
  confirmed: "Confirmed revision",
};

export const TASK_FLOW_ANALYSIS_LABELS: Readonly<Record<TaskFlowAnalysisState, string>> = {
  running: "Analysis running",
  completed: "Analysis completed",
  failed: "Analysis failed",
  not_observed: "No matching analysis observed",
  unknown: "Analysis history incomplete",
  not_applicable: "Not applicable to proposals",
};

export const TASK_FLOW_SOURCE_LABELS: Readonly<Record<TaskFlowLifecycleSource, string>> = {
  discovery_candidate: "Discovery proposal",
  review_decision: "Human review decision",
  task_revision: "Task revision",
};

export function applyTaskFlowFilters(
  items: readonly TaskFlowItem[],
  filters: TaskFlowFilters,
): TaskFlowItem[] {
  return items.filter((item) =>
    (filters.kind === "all" || item.kind === filters.kind)
    && (filters.column === "all" || item.column === filters.column)
    && (filters.analysis === "all" || item.analysis.state === filters.analysis)
    && (filters.projectId === "all" || item.projectId === filters.projectId));
}
