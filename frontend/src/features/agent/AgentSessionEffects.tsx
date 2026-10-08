import { useMemo } from "react";
import type { AgentEvent, AgentTurnSummary, AgentWriteReceipt } from "../../shared/api/contracts";
import { isAgentTurnSummary } from "../../shared/api/agentTurnContract";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import "./AgentSessionEffects.css";

const EFFECT_PATH_PAGE = 50;

type ObservedWrite = { receipt: AgentWriteReceipt; turnNumber: number };
type FileReceipts = { path: string; writes: ObservedWrite[] };

function plural(value: number, one: string, many = `${one}s`): string {
  return `${value} ${value === 1 ? one : many}`;
}

function latestLabel(write: AgentWriteReceipt): string {
  if (write.state === "unverified") return "latest effect unverified";
  if (write.operation === "created") return "latest receipt created the file";
  if (write.operation === "modified") return "latest receipt modified the file";
  return "latest content unchanged";
}

function validTurnSummaries(events: AgentEvent[]): {
  duplicate: boolean;
  invalid: boolean;
  summaries: AgentTurnSummary[];
} {
  const byTurn = new Map<string, AgentTurnSummary>();
  const turnNumbers = new Set<number>();
  let duplicate = false;
  let invalid = false;
  for (const event of events) {
    if (event.kind !== "done") continue;
    if (!event.turn_id || !event.turn_summary || !isAgentTurnSummary(event.turn_summary, event.turn_id)) {
      invalid = true;
      continue;
    }
    if (byTurn.has(event.turn_id) || turnNumbers.has(event.turn_summary.turn_number)) {
      duplicate = true;
      continue;
    }
    byTurn.set(event.turn_id, event.turn_summary);
    turnNumbers.add(event.turn_summary.turn_number);
  }
  return { duplicate, invalid, summaries: [...byTurn.values()].sort((left, right) => left.turn_number - right.turn_number) };
}

export function AgentSessionEffects({
  events,
  fileActionsDisabled,
  historyGap,
  onOpenFile,
  running,
  scopeKey = "current-session",
  turnCount,
}: {
  events: AgentEvent[];
  fileActionsDisabled: boolean;
  historyGap: boolean;
  onOpenFile?: (path: string) => void;
  running: boolean;
  scopeKey?: string;
  turnCount: number;
}) {
  const snapshot = useMemo(() => {
    const { duplicate, invalid, summaries } = validTurnSummaries(events);
    const summarizedTurns = new Set(summaries.map((summary) => summary.turn_id));
    const pendingToolCalls = events.filter((event) => event.kind === "tool_call" && (!event.turn_id || !summarizedTurns.has(event.turn_id))).length;
    const observedActions = summaries.reduce((sum, summary) => sum + summary.tools_requested, pendingToolCalls);
    const writes: ObservedWrite[] = summaries.flatMap((summary) => summary.writes.map((receipt) => ({ receipt, turnNumber: summary.turn_number })));
    const files = new Map<string, ObservedWrite[]>();
    for (const write of writes) files.set(write.receipt.path, [...(files.get(write.receipt.path) ?? []), write]);
    const grouped: FileReceipts[] = [...files].map(([path, receipts]) => ({ path, writes: receipts }));
    const reviewedPaths = grouped.length;
    const unverifiedWrites = writes.filter(({ receipt }) => receipt.state === "unverified").length;
    const commandAttempts = summaries.reduce((sum, summary) => sum + summary.untracked_command_calls, 0);
    const missingSummaries = summaries.length !== turnCount;
    const inconsistentSummaries = invalid || duplicate || summaries.some((summary) => summary.turn_number > turnCount);
    const coverage = historyGap || inconsistentSummaries
      ? "partial"
      : running
        ? "running"
        : missingSummaries
          ? "incomplete"
          : "complete";
    return { commandAttempts, coverage, grouped, inconsistentSummaries, observedActions, reviewedPaths, unverifiedWrites, writes };
  }, [events, historyGap, running, turnCount]);

  const coverageLabel = snapshot.coverage === "complete"
    ? "Complete retained session history"
    : snapshot.coverage === "running"
      ? "Current turn not summarized yet"
      : snapshot.coverage === "incomplete"
        ? "Retained turn summaries incomplete"
        : "Partial retained history";
  const pathPage = useBoundedListPage({
    itemCount: snapshot.grouped.length,
    pageSize: EFFECT_PATH_PAGE,
    resetKey: scopeKey,
  });
  const visiblePaths = snapshot.grouped.slice(pathPage.start, pathPage.end);

  return <details className="agent-session-effects" data-coverage={snapshot.coverage}>
    <summary aria-label="Session activity and write receipts">
      <span>
        <strong>Session activity</strong>
        <small>{coverageLabel}</small>
      </span>
      <span className="agent-session-effects__compact">
        {plural(snapshot.observedActions, "observed action")}
        {snapshot.writes.length > 0 ? ` · ${plural(snapshot.writes.length, "reviewed write")}` : ""}
        {snapshot.reviewedPaths > 0 ? ` · ${plural(snapshot.reviewedPaths, "reviewed path")}` : ""}
        {snapshot.unverifiedWrites > 0 ? ` · ${plural(snapshot.unverifiedWrites, "unverified write")}` : ""}
      </span>
    </summary>
    <div className="agent-session-effects__body">
      <div className="agent-session-effects__coverage" data-coverage={snapshot.coverage}>
        <strong>{coverageLabel}</strong>
        {historyGap && <span>Earlier in-memory events expired, so the receipts below are only the retained suffix.</span>}
        {snapshot.inconsistentSummaries && <span>Retained turn summaries conflict with each other or with the session turn count.</span>}
        {snapshot.coverage === "running" && <span>The current turn can add tool and file effects until its final receipt arrives.</span>}
        {snapshot.coverage === "incomplete" && <span>Not every admitted turn has a retained, verified turn summary.</span>}
      </div>

      {snapshot.grouped.length === 0 ? (
        <p>No direct reviewed file writes were recorded in the retained Agent turns.</p>
      ) : (
        <ul aria-label="Observed reviewed file receipts" className="agent-session-effects__files">
          {visiblePaths.map((file) => {
            const latest = file.writes[file.writes.length - 1];
            const hasUnverified = file.writes.some(({ receipt }) => receipt.state === "unverified");
            const observedTurns = [...new Set(file.writes.map((write) => write.turnNumber))];
            return <li data-write-state={hasUnverified ? "unverified" : "verified"} key={file.path}>
              <div>
                {onOpenFile ? (
                  <button
                    aria-label={`Open ${file.path} from session effects`}
                    disabled={fileActionsDisabled}
                    onClick={() => onOpenFile(file.path)}
                    type="button"
                  >{file.path}</button>
                ) : <code>{file.path}</code>}
                <span>{plural(file.writes.length, "reviewed receipt")} · {latestLabel(latest.receipt)}</span>
              </div>
              <small>Observed in turn{observedTurns.length === 1 ? "" : "s"} {observedTurns.join(", ")}</small>
            </li>;
          })}
        </ul>
      )}
      <BoundedListPager label="Reviewed path pages" page={pathPage} />

      {snapshot.unverifiedWrites > 0 && (
        <p className="agent-session-effects__warning">
          {plural(snapshot.unverifiedWrites, "unverified write")} require{snapshot.unverifiedWrites === 1 ? "s" : ""} current-file inspection before another change.
        </p>
      )}
      {snapshot.commandAttempts > 0 && (
        <p className="agent-session-effects__warning">
          {plural(snapshot.commandAttempts, "command attempt")} may have file effects that are not inventoried.
        </p>
      )}
      <p className="agent-session-effects__note">
        This is historical activity, not current file state. Use the reviewed change set for the live net effect. External and command effects remain outside reviewed-path authority. Receipts remain in server memory only.
      </p>
    </div>
  </details>;
}
