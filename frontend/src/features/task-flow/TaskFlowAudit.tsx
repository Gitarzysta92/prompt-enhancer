import { useEffect, useMemo, useRef, useState } from "react";
import type { PromptEnhancerTransport, TaskDecision } from "../../shared/api/contracts";
import { formatTimestamp, shortId, titleFromKey } from "../../shared/lib/format";
import type { AppRoute } from "../../shared/platform/platform";
import { Icon } from "../../shared/ui/Icon";
import type { TaskFlowItem } from "./taskFlowModel";

type DecisionTransport = Pick<PromptEnhancerTransport, "getCandidateDecisions">;

function decisionLinkRoute(decision: TaskDecision, taskId: string, revision: number): AppRoute | null {
  const linked = decision.revision_links.some((item) =>
    item.task_id === taskId && item.revision === revision);
  return linked ? { name: "task", taskId, revision } : null;
}

function DecisionReceipt({
  decision,
  navigate,
}: {
  decision: TaskDecision;
  navigate: (route: AppRoute) => void;
}) {
  return (
    <li className="task-flow-audit__decision">
      <div>
        <strong>{titleFromKey(decision.action)}</strong>
        <time dateTime={decision.decided_at}>{formatTimestamp(decision.decided_at)}</time>
      </div>
      <p>
        Receipt <span className="mono">{shortId(decision.decision_id)}</span>
        {` · ${decision.decision_schema_version}`}
        {decision.decision_code === null ? "" : ` · reason ${titleFromKey(decision.decision_code)}`}
      </p>
      {decision.revision_links.length === 0 ? (
        <p>No task revision link was recorded. This is expected for a rejection.</p>
      ) : (
        <ul aria-label={`${titleFromKey(decision.action)} revision links`}>
          {decision.revision_links.map((link) => {
            const route = decisionLinkRoute(decision, link.task_id, link.revision);
            return (
              <li key={`${link.role}:${link.task_id}:${link.revision}`}>
                <span>{titleFromKey(link.role)} revision {link.revision} · task <span className="mono">{shortId(link.task_id)}</span></span>
                {route !== null && (
                  <button className="button button--secondary button--compact" onClick={() => navigate(route)} type="button">
                    Open <Icon name="arrow" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

export function TaskFlowAudit({
  item,
  taskHistory,
  decisions,
  transport,
  navigate,
  onDecisionsLoaded,
}: {
  item: TaskFlowItem;
  taskHistory: readonly TaskFlowItem[];
  decisions: readonly TaskDecision[] | undefined;
  transport: DecisionTransport;
  navigate: (route: AppRoute) => void;
  onDecisionsLoaded: (candidateId: string, values: readonly TaskDecision[]) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const sortedHistory = useMemo(
    () => [...taskHistory].sort((left, right) => {
      const byTime = left.occurredAt.localeCompare(right.occurredAt);
      return byTime !== 0 ? byTime : left.id.localeCompare(right.id);
    }),
    [taskHistory],
  );

  async function loadCandidateAudit() {
    if (item.kind !== "candidate" || !item.reviewDecisionRecorded || decisions !== undefined || loading) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const response = await transport.getCandidateDecisions(item.sourceId, controller.signal);
      if (response.candidate_id !== item.sourceId) {
        throw new Error("Decision audit identity did not match the proposal");
      }
      const matching = response.decisions.filter((decision) =>
        decision.candidate_ids.includes(item.sourceId));
      if (matching.length !== response.decisions.length) {
        throw new Error("Decision audit lineage did not match the proposal");
      }
      onDecisionsLoaded(item.sourceId, matching);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Decision audit could not be loaded");
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  if (item.kind === "candidate") {
    const decided = item.reviewDecisionRecorded;
    return (
      <details
        className="task-flow-audit"
        onToggle={(event) => {
          if (event.currentTarget.open) void loadCandidateAudit();
        }}
      >
        <summary>
          <span>Immutable review audit</span>
          <small>{decided ? (decisions === undefined ? "load receipt" : `${decisions.length} receipt${decisions.length === 1 ? "" : "s"}`) : "no decision recorded"}</small>
        </summary>
        <div className="task-flow-audit__body">
          <p>
            Proposal created {formatTimestamp(item.occurredAt)} · discovery {item.provenance.version} · fingerprint <span className="mono">{shortId(item.provenance.fingerprint)}</span>.
          </p>
          {!decided && <p>No accept, reject, merge, or split receipt exists for this proposal.</p>}
          {decided && item.decisionId === null && (
            <p>A decision is recorded; its receipt identifier is not exposed. The receipt is unknown, not absent.</p>
          )}
          {loading && <p role="status">Loading the local decision receipt…</p>}
          {error !== null && <p role="alert">{error}</p>}
          {decisions !== undefined && decisions.length === 0 && (
            <p role="alert">The proposal says a decision exists, but its immutable receipt was not returned.</p>
          )}
          {decisions !== undefined && decisions.length > 0 && (
            <ol aria-label="Immutable review decisions">
              {decisions.map((decision) => (
                <DecisionReceipt decision={decision} key={decision.decision_id} navigate={navigate} />
              ))}
            </ol>
          )}
        </div>
      </details>
    );
  }

  return (
    <details className="task-flow-audit">
      <summary>
        <span>Lifecycle, revision & analysis audit</span>
        <small>{item.workLifecycle?.eventCount ?? "unknown"} lifecycle receipt{item.workLifecycle?.eventCount === 1 ? "" : "s"}</small>
      </summary>
      <div className="task-flow-audit__body">
        <p>
          In-progress receipt {item.taskStartedAt === null ? "Unknown" : formatTimestamp(item.taskStartedAt)} · done receipt {item.taskFinishedAt === null ? "Unknown" : formatTimestamp(item.taskFinishedAt)}. Receipt times do not prove real-world duration.
        </p>
        {item.workLifecycle?.authority !== "authoritative" ? (
          <p role="note">No authoritative matching lifecycle snapshot is projected for this revision. No state is inferred.</p>
        ) : item.workLifecycle.events.length === 0 ? (
          <p>Legacy / no-receipt lifecycle: work state remains Unknown.</p>
        ) : (
          <>
            <ol aria-label="Immutable task lifecycle receipts" className="task-flow-audit__lifecycle">
              {item.workLifecycle.events.map((event) => (
                <li key={event.event_id}>
                  <div>
                    <strong>
                      #{event.sequence} · {event.event_kind === "correction" ? "Correction / undo" : "Explicit transition"}
                    </strong>
                    <time dateTime={event.created_at}>{formatTimestamp(event.created_at)}</time>
                  </div>
                  <p>
                    {event.prior_state === null ? "Unknown" : titleFromKey(event.prior_state)} → {event.resulting_state === null ? "Unknown" : titleFromKey(event.resulting_state)}
                    {" · receipt "}<span className="mono">{shortId(event.event_id)}</span>
                    {event.supersedes_event_id === null ? "" : ` · supersedes ${shortId(event.supersedes_event_id)}`}
                  </p>
                  <p>Explicit local user · input fingerprint <span className="mono">{shortId(event.task_input_fingerprint)}</span></p>
                </li>
              ))}
            </ol>
            {!item.workLifecycle.eventsComplete && (
              <p role="alert">This lifecycle audit page is bounded and incomplete. Timing and correction controls stay conservative.</p>
            )}
          </>
        )}
        <h4>Immutable revisions and separate analysis</h4>
        <ol aria-label="Immutable task revision history">
          {sortedHistory.map((revision) => (
            <li key={revision.id}>
              <div>
                <strong>{revision.title}</strong>
                <time dateTime={revision.occurredAt}>{formatTimestamp(revision.occurredAt)}</time>
              </div>
              <p>
                Raw state {titleFromKey(revision.lifecycle.status)} · fingerprint <span className="mono">{shortId(revision.provenance.fingerprint)}</span>
              </p>
              {revision.analysis.runs.length === 0 ? (
                <p>{revision.analysis.label}. {revision.analysis.detail}</p>
              ) : (
                <ul aria-label={`${revision.title} analysis events`}>
                  {revision.analysis.runs.map((run) => (
                    <li key={run.runId}>
                      <span>{titleFromKey(run.status)} · started {formatTimestamp(run.startedAt)} · finished {run.finishedAt === null ? "unknown" : formatTimestamp(run.finishedAt)}</span>
                      {run.failureCode === null ? null : <span> · failure {titleFromKey(run.failureCode)}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
        <p>Work-state corrections append a superseding receipt; task revision history remains immutable and analysis never transitions either ledger.</p>
      </div>
    </details>
  );
}
