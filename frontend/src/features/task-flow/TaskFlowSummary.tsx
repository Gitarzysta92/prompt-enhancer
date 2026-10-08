import type { TaskDecision } from "../../shared/api/contracts";
import { Icon } from "../../shared/ui/Icon";
import type { TaskFlowItem } from "./taskFlowModel";

export function TaskFlowSummary({
  visible,
  total,
  decisionAudits,
}: {
  visible: readonly TaskFlowItem[];
  total: number;
  decisionAudits: ReadonlyMap<string, readonly TaskDecision[]>;
}) {
  const confirmed = visible.filter((item) => item.kind === "confirmed");
  const runs = confirmed.flatMap((item) => item.analysis.runs);
  const decisions = new Set(
    [...decisionAudits.values()].flatMap((values) => values.map((decision) => decision.decision_id)),
  );
  const counts = {
    proposed: visible.filter((item) => item.column === "proposed").length,
    confirmed: confirmed.length,
    reviewed: visible.filter((item) => item.column === "reviewed").length,
    rejected: visible.filter((item) => item.column === "rejected").length,
    decidedUnknown: visible.filter((item) => item.column === "decided_unknown").length,
    workUnknown: visible.filter((item) => item.column === "work_unknown").length,
    backlog: visible.filter((item) => item.column === "backlog").length,
    inProgress: visible.filter((item) => item.column === "in_progress").length,
    done: visible.filter((item) => item.column === "done").length,
    historical: visible.filter((item) => item.column === "historical").length,
    unreconciled: visible.filter((item) => item.column === "unreconciled").length,
    completedRuns: runs.filter((run) => run.status === "completed").length,
    activeRuns: runs.filter((run) => run.status === "running").length,
    failedRuns: runs.filter((run) => run.status === "failed").length,
  };
  return (
    <section aria-label="Task flow compact summary" className="task-flow-summary">
      <header>
        <div>
          <Icon name="activity" />
          <strong>Local record summary</strong>
        </div>
        <small>{visible.length} of {total} records in current filters</small>
      </header>
      <dl>
        <div><dt>Needs review</dt><dd>{counts.proposed}</dd></div>
        <div><dt>Confirmed revisions</dt><dd>{counts.confirmed}</dd></div>
        <div><dt>Accepted / merged / split</dt><dd>{counts.reviewed}</dd></div>
        <div><dt>Rejected</dt><dd>{counts.rejected}</dd></div>
        <div><dt>Decision action unknown</dt><dd>{counts.decidedUnknown}</dd></div>
        <div><dt>Work state Unknown</dt><dd>{counts.workUnknown}</dd></div>
        <div><dt>Backlog</dt><dd>{counts.backlog}</dd></div>
        <div><dt>In progress</dt><dd>{counts.inProgress}</dd></div>
        <div><dt>Done</dt><dd>{counts.done}</dd></div>
        <div><dt>Historical / unreconciled</dt><dd>{counts.historical} / {counts.unreconciled}</dd></div>
        <div><dt>Analysis only</dt><dd>{counts.completedRuns} completed · {counts.activeRuns} running · {counts.failedRuns} failed</dd></div>
        <div><dt>Audit receipts loaded</dt><dd>{decisions.size}</dd></div>
      </dl>
      <div className="task-flow-summary__truth" role="note">
        <strong>Explicit local receipts only</strong>
        <span>Unknown is preserved · analysis cannot move work columns · missing receipt timing remains Unknown</span>
      </div>
      <p className="task-flow-summary__scope">
        <Icon name="lock" /> Local-only source set · 0 team-sourced records · 0 remote-synced records · no transcript or source content loaded
      </p>
    </section>
  );
}
