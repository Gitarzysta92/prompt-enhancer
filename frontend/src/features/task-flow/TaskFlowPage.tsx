import { useCallback, useEffect, useMemo, useState } from "react";
import type { PromptEnhancerTransport, TaskDecision } from "../../shared/api/contracts";
import type { AppRoute } from "../../shared/platform/platform";
import type { RuntimeDataMode } from "../../shared/platform/runtimeMode";
import { shortId } from "../../shared/lib/format";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { FictionalNotice } from "../../shared/ui/FictionalNotice";
import { Icon } from "../../shared/ui/Icon";
import { TaskFlowBoard } from "./TaskFlowBoard";
import { TaskFlowSummary } from "./TaskFlowSummary";
import { TaskFlowTimeline } from "./TaskFlowTimeline";
import { projectTaskFlow } from "./taskFlowAdapter";
import {
  TASK_FLOW_RECORD_CAP_PER_SOURCE,
  loadTaskFlowSources,
  type TaskFlowLoadProgress,
  type TaskFlowSourceReceipt,
} from "./taskFlowLoader";
import {
  DEFAULT_TASK_FLOW_FILTERS,
  TASK_FLOW_ANALYSIS_LABELS,
  TASK_FLOW_COLUMNS,
  TASK_FLOW_KIND_LABELS,
  applyTaskFlowFilters,
  type TaskFlowFilters,
  type TaskFlowItem,
} from "./taskFlowModel";
import "./TaskFlow.css";

type TaskFlowTransport = Pick<
  PromptEnhancerTransport,
  | "listCandidates"
  | "listTaskRevisions"
  | "listTaskLifecycles"
  | "listAnalysisRuns"
  | "getCandidateDecisions"
  | "transitionTaskLifecycle"
  | "correctTaskLifecycle"
>;

function wideBoardDefault(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return !window.matchMedia("(max-width: 600px)").matches;
}

/**
 * Local task-record workspace. Proposal, review, revision, and analysis facts
 * are presented on separate axes; no text or model inference becomes a task or
 * a backlog/in-progress/done claim.
 */
export function TaskFlowPage({
  transport,
  navigate,
  runtimeMode,
}: {
  transport: TaskFlowTransport;
  navigate: (route: AppRoute) => void;
  runtimeMode: RuntimeDataMode;
}) {
  const [items, setItems] = useState<TaskFlowItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<TaskFlowFilters>(DEFAULT_TASK_FLOW_FILTERS);
  const [reloadToken, setReloadToken] = useState(0);
  const [sourceReceipts, setSourceReceipts] = useState<readonly TaskFlowSourceReceipt[] | null>(null);
  const [loadProgress, setLoadProgress] = useState<Partial<Record<TaskFlowLoadProgress["source"], TaskFlowLoadProgress>>>({});
  const [decisionAudits, setDecisionAudits] = useState<ReadonlyMap<string, readonly TaskDecision[]>>(() => new Map());
  const [lifecycleNotice, setLifecycleNotice] = useState<string | null>(null);
  const [boardOpen, setBoardOpen] = useState(wideBoardDefault);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setItems(null);
    setSourceReceipts(null);
    setLoadProgress({});
    setDecisionAudits(new Map());
    loadTaskFlowSources(transport, controller.signal, {
      onProgress(progress) {
        if (controller.signal.aborted) return;
        setLoadProgress((current) => ({ ...current, [progress.source]: progress }));
      },
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        const runReceipt = result.receipts.find((receipt) => receipt.source === "runs");
        const lifecycleReceipt = result.receipts.find((receipt) => receipt.source === "lifecycles");
        setItems(projectTaskFlow(result, {
          analysisIndexEnded: runReceipt?.boundary === "page_end_observed",
          lifecycleIndexEnded: lifecycleReceipt?.boundary === "page_end_observed",
        }));
        setSourceReceipts(result.receipts);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Task records could not be loaded");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reloadToken, transport]);

  const projects = useMemo(() => [...new Set((items ?? []).map((item) => item.projectId))], [items]);
  const visible = useMemo(() => applyTaskFlowFilters(items ?? [], filters), [filters, items]);
  const counts = useMemo(() => ({
    proposals: visible.filter((item) => item.kind === "candidate").length,
    confirmed: visible.filter((item) => item.kind === "confirmed").length,
  }), [visible]);
  const incompleteReceipt = sourceReceipts?.find((receipt) => receipt.boundary !== "page_end_observed") ?? null;
  const progressLabel = (["candidates", "tasks", "lifecycles", "runs"] as const)
    .map((source) => `${loadProgress[source]?.loaded ?? 0} ${source}`)
    .join(" · ");

  const open = useCallback((item: TaskFlowItem) => {
    if (item.route !== null) navigate(item.route);
  }, [navigate]);

  const recordDecisionAudit = useCallback((candidateId: string, values: readonly TaskDecision[]) => {
    setDecisionAudits((current) => {
      const next = new Map(current);
      next.set(candidateId, values);
      return next;
    });
  }, []);

  const update = (patch: Partial<TaskFlowFilters>) =>
    setFilters((current) => ({ ...current, ...patch }));
  const filtersAreDefault = Object.entries(DEFAULT_TASK_FLOW_FILTERS)
    .every(([key, value]) => filters[key as keyof TaskFlowFilters] === value);

  return (
    <section aria-labelledby="task-flow-title" className="task-flow">
      <header className="page-header route-header task-flow__header">
        <div>
          <p className="eyebrow">Evidence-honest task records</p>
          <h1 id="task-flow-title">Task flow</h1>
          <p>Detected groupings stay proposals until accept, reject, merge, or split. Only explicit local-user receipts can place a confirmed current revision in backlog, in progress, or done; analysis never changes work state.</p>
        </div>
        <div className="page-header__meta">
          <span className="privacy-chip">
            <Icon name="lock" /> {runtimeMode === "synthetic_demo" ? "Local · synthetic records" : "Local · this installation only"}
          </span>
          <span className="count-summary"><strong>{counts.proposals}</strong> proposal records · <strong>{counts.confirmed}</strong> confirmed revisions · current filters</span>
        </div>
      </header>

      {runtimeMode === "synthetic_demo" && (
        <FictionalNotice compact>
          Every proposal, decision, revision, and analysis event on this board is a content-free synthetic fixture; nothing here reflects a real session.
        </FictionalNotice>
      )}

      {lifecycleNotice !== null && (
        <p className="task-flow__lifecycle-notice" role="status">{lifecycleNotice}</p>
      )}

      {items !== null && (
        <TaskFlowSummary decisionAudits={decisionAudits} total={items.length} visible={visible} />
      )}

      {sourceReceipts !== null && (
        <div
          className="task-flow__completeness"
          data-state={incompleteReceipt === null ? "non-atomic" : "incomplete"}
          role={incompleteReceipt === null ? "status" : "alert"}
        >
          <Icon name={incompleteReceipt === null ? "activity" : "x"} />
          <div>
            <strong>
              {incompleteReceipt === null
                ? "Page ends observed · point-in-time completeness not proven"
                : incompleteReceipt.boundary === "cap_reached" || incompleteReceipt.boundary === "duplicate_and_cap_reached"
                  ? `Incomplete · ${incompleteReceipt.source} reached the ${incompleteReceipt.record_cap.toLocaleString()}-record cap`
                  : `Incomplete · ${incompleteReceipt.source} changed across pages`}
            </strong>
            <p>
              {runtimeMode === "synthetic_demo" ? "Synthetic fixture" : "Local"} indexes loaded {sourceReceipts.map((receipt) => `${receipt.loaded.toLocaleString()} ${receipt.source}`).join(" · ")}.
              Candidate, task, lifecycle, and run pages are separate requests, not one atomic snapshot; refresh after activity to reconcile.
              Each source is bounded at {TASK_FLOW_RECORD_CAP_PER_SOURCE.toLocaleString()} records. Missing analysis stays unknown and lifecycle mismatches stay unreconciled when an index end is not proven.
            </p>
          </div>
        </div>
      )}

      <form aria-label="Task flow filters" className="task-flow__filters" onSubmit={(event) => event.preventDefault()}>
        <label>
          <span>Kind</span>
          <select onChange={(event) => update({ kind: event.target.value as TaskFlowFilters["kind"] })} value={filters.kind}>
            <option value="all">Proposals and confirmed revisions</option>
            <option value="candidate">{TASK_FLOW_KIND_LABELS.candidate}s only</option>
            <option value="confirmed">{TASK_FLOW_KIND_LABELS.confirmed}s only</option>
          </select>
        </label>
        <label>
          <span>Record / work column</span>
          <select onChange={(event) => update({ column: event.target.value as TaskFlowFilters["column"] })} value={filters.column}>
            <option value="all">All record columns</option>
            {TASK_FLOW_COLUMNS.map((column) => <option key={column.id} value={column.id}>{column.label}</option>)}
          </select>
        </label>
        <label>
          <span>Analysis fact</span>
          <select onChange={(event) => update({ analysis: event.target.value as TaskFlowFilters["analysis"] })} value={filters.analysis}>
            <option value="all">Any analysis fact</option>
            {(Object.keys(TASK_FLOW_ANALYSIS_LABELS) as Array<keyof typeof TASK_FLOW_ANALYSIS_LABELS>).map((state) => (
              <option key={state} value={state}>{TASK_FLOW_ANALYSIS_LABELS[state]}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Project</span>
          <select onChange={(event) => update({ projectId: event.target.value })} value={filters.projectId}>
            <option value="all">All projects</option>
            {projects.map((projectId) => <option key={projectId} value={projectId}>Project {shortId(projectId)}</option>)}
          </select>
        </label>
        <button
          aria-describedby="task-flow-reset-status"
          className="button button--secondary button--compact"
          disabled={filtersAreDefault}
          onClick={() => setFilters(DEFAULT_TASK_FLOW_FILTERS)}
          type="button"
        >
          Reset filters
        </button>
        <span className="sr-only" id="task-flow-reset-status">
          {filtersAreDefault ? "Filters already use their defaults." : "Reset every task-flow filter to its default."}
        </span>
      </form>

      {error !== null && <ErrorState message={error} onRetry={() => setReloadToken((value) => value + 1)} />}
      {loading && items === null ? (
        <LoadingState label={`Loading bounded task records · ${progressLabel}`} />
      ) : items === null ? null : (
        <>
          <details
            className="task-flow__board-disclosure"
            onToggle={(event) => setBoardOpen(event.currentTarget.open)}
            open={boardOpen}
          >
            <summary>
              <span>Kanban · immutable record kinds</span>
              <small>{visible.length} visible · explicit receipts only · no inferred work state</small>
            </summary>
            <TaskFlowBoard
              allItems={items}
              decisionAudits={decisionAudits}
              items={visible}
              onDecisionsLoaded={recordDecisionAudit}
              onLifecycleChanged={(message) => {
                setLifecycleNotice(message);
                setReloadToken((value) => value + 1);
              }}
              onOpen={open}
              transport={transport}
            />
          </details>
          <details className="task-flow__timeline" open>
            <summary>
              <span>Chronological record & event timeline</span>
              <small>Receipt times only; missing start or finish remains Unknown</small>
            </summary>
            <TaskFlowTimeline decisionAudits={decisionAudits} items={visible} onOpen={open} />
          </details>
        </>
      )}
    </section>
  );
}
