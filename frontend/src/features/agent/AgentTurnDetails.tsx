import type { AgentTurnSummary } from "../../shared/api/contracts";
import { isAgentTurnSummary } from "../../shared/api/agentTurnContract";
import "./AgentTurnDetails.css";

export type AgentTurnRevisionMode = "edit" | "regenerate" | "retry";

const REASONS: Record<AgentTurnSummary["reason"], string> = {
  inference_not_authorized: "The external model request was not approved or its review expired. No unapproved request was sent.",
  answer_complete: "The model completed its response. This is not verification that the task succeeded.",
  stop_requested: "Stopped at your request. Review any file or tool effects already recorded below.",
  step_limit: "The turn reached its model-step limit. Send another message to continue.",
  model_response_limit: "The response token limit was reached; partial output was not admitted as a completed answer.",
  model_response_filtered: "The runtime filtered the response.",
  model_completion_unrecognized: "The runtime returned an unrecognized completion reason.",
  model_stream_incomplete: "The stream ended without a completion receipt.",
  model_stream_failed: "The response stream could not finish.",
  model_reply_unusable: "The runtime response could not be accepted.",
  model_reply_too_large: "The response exceeded the local safety limit.",
  model_answer_missing: "The model exposed reasoning but no final answer or tool request.",
  runtime_unreachable: "The model runtime could not be reached.",
  runtime_http_error: "The model runtime rejected the request.",
  turn_failed: "The turn could not finish. Review the recorded effects before retrying.",
  command_cleanup_unconfirmed: "Command processes may still be running. Agent work is paused; inspect those processes before restarting the app. Earlier effects were not undone.",
  context_window_exceeded: "The protected system instructions and current request could not fit the served model's measured context window.",
};

function elapsed(value: number | null | undefined): string {
  if (value == null) return "Not measured";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}
function tokens(value: number | null | undefined): string {
  return value == null ? "Not reported" : value.toLocaleString("en-US");
}

export function AgentTurnDetails({
  summary,
  turnId,
  onOpenFile,
  fileActionsDisabled = false,
  onRevise,
  revisionBusyMode = null,
  revisionDisabled = false,
  sourceHasAttachments = false,
}: {
  summary: AgentTurnSummary;
  turnId: string;
  onOpenFile?: (path: string) => void;
  fileActionsDisabled?: boolean;
  onRevise?: (mode: AgentTurnRevisionMode) => void;
  revisionBusyMode?: AgentTurnRevisionMode | null;
  revisionDisabled?: boolean;
  sourceHasAttachments?: boolean;
}) {
  if (!isAgentTurnSummary(summary, turnId)) return <p className="agent__status" role="status">Turn details could not be verified.</p>;
  const label = { completed: "Response complete", stopped: "Stopped", failed: "Incomplete", step_limit: "Step limit reached" }[summary.status];
  const usage = summary.usage;
  const usageLabel = usage.state === "reported" ? `${tokens(usage.total_tokens)} reported tokens`
    : usage.state === "invalid" ? "Usage invalid" : usage.state === "partial" ? "Usage incomplete" : "Usage not reported";
  const writtenPaths = new Set(summary.writes
    .filter((write) => write.state === "verified" && (write.operation === "created" || write.operation === "modified"))
    .map((write) => write.path));
  const reviewedNoChange = summary.writes.some(
    (write) => write.state === "verified" && write.operation === "unchanged",
  );
  const unverifiedWrites = summary.writes.filter((write) => write.state === "unverified").length;
  const tools = [
    [summary.tools_succeeded, "successful"], [summary.tools_failed, "failed"],
    [summary.tools_not_approved, "not approved"], [summary.tools_cancelled, "cancelled"],
    [summary.tools_unverified, "unverified"],
  ].filter(([count]) => Number(count) > 0).map(([count, state]) => `${count} ${state}`).join(" · ");
  const automaticRevisionMode: AgentTurnRevisionMode = summary.status === "completed" ? "regenerate" : "retry";
  const automaticRevisionLabel = automaticRevisionMode === "regenerate" ? "Regenerate in branch" : "Retry in branch";
  const automaticRevisionDisabled = revisionDisabled || revisionBusyMode !== null || sourceHasAttachments;
  return <details
    className="agent-turn-details"
    data-termination={summary.status}
    id={`agent-turn-${turnId}`}
    tabIndex={-1}
  >
    <summary aria-label={`Turn ${summary.turn_number} details`}>
      <span className="agent-turn-details__title">Turn {summary.turn_number} <span>{label}</span></span>
      <span className="agent-turn-details__compact">
        {elapsed(summary.duration_ms)} · {usageLabel}
        {writtenPaths.size > 0
          ? ` · ${writtenPaths.size} reviewed path${writtenPaths.size === 1 ? "" : "s"}`
          : reviewedNoChange
            ? " · no file content changes"
            : " · no reviewed file writes"}
        {unverifiedWrites > 0 ? ` · ${unverifiedWrites} unverified write${unverifiedWrites === 1 ? "" : "s"}` : ""}
      </span>
    </summary>
    <div className="agent-turn-details__body">
      <p>{REASONS[summary.reason]}</p>
      <p className="agent-turn-details__model">Model alias used: <code>{summary.model_alias}</code></p>
      <dl aria-label="Turn telemetry" className="agent-turn-details__metrics">
        <div><dt>Elapsed · incl. approval waits</dt><dd>{elapsed(summary.duration_ms)}</dd></div>
        <div><dt>Model request time</dt><dd>{elapsed(summary.model_wait_ms)}</dd></div>
        <div><dt>First streamed text</dt><dd>{elapsed(summary.time_to_first_text_ms)}</dd></div>
        <div><dt>Model requests</dt><dd>{usage.model_requests}</dd></div>
        <div><dt>Input tokens</dt><dd>{tokens(usage.prompt_tokens)}</dd></div>
        <div><dt>Output tokens</dt><dd>{tokens(usage.completion_tokens)}</dd></div>
        <div><dt>Total tokens</dt><dd>{tokens(usage.total_tokens)}</dd></div>
        <div><dt>Cached input tokens</dt><dd>{tokens(usage.cached_prompt_tokens)}</dd></div>
        <div><dt>Reasoning tokens</dt><dd>{tokens(usage.reasoning_tokens)}</dd></div>
      </dl>
      <p className="agent-turn-details__note">Usage is runtime-reported, not estimated. Complete counters: {usage.reported_requests}/{usage.model_requests} requests. Missing request counts are never added as zero. Timing is observed by this server, not GPU-only inference time.</p>
      {usage.state === "invalid" && <p className="agent-turn-details__warning">Inconsistent or malformed usage was rejected. No turn token total is available.</p>}
      <p>Tool requests: {summary.tools_requested}{tools ? ` · ${tools}` : ""}</p>
      <h3>Agent file writes</h3>
      {summary.writes.length === 0 && (
        <p>No direct file-write receipt was recorded for this turn. Model text alone is not evidence that a file or document was created.</p>
      )}
      {summary.writes.length > 0 && <ul className="agent-turn-details__writes">
        {summary.writes.map((write, index) => <li key={`${index}:${write.path}`} data-write-state={write.state}>
          <div className="agent-turn-details__write-head">
            {onOpenFile ? <button type="button" disabled={fileActionsDisabled} aria-label={`Open ${write.path} in workspace`} onClick={() => onOpenFile(write.path)}>{write.path}</button> : <code>{write.path}</code>}
            <span>{write.state === "unverified" ? "Effect unverified" : write.operation === "created" ? "Created" : write.operation === "unchanged" ? "Content unchanged" : "Modified"}</span>
          </div>
          {write.state === "verified" ? <>
            <span className="agent-turn-details__line-counts">+{write.added_lines} / −{write.removed_lines} lines · {write.byte_size?.toLocaleString("en-US")} bytes</span>
            <details className="agent-turn-details__revision"><summary>Verified revision</summary><code>{write.after_sha256}</code></details>
          </> : <p className="agent-turn-details__warning">A write was attempted but its final file content could not be verified. Inspect the current file before retrying.</p>}
        </li>)}
      </ul>}
      {summary.untracked_command_calls > 0 && <p className="agent-turn-details__warning">{summary.untracked_command_calls} command attempt{summary.untracked_command_calls === 1 ? "" : "s"}: file effects are not inventoried.</p>}
      <p className="agent-turn-details__note">Each entry is a historical reviewed-write receipt, not current file state. The session change set compares retained baselines with live reviewed paths. Opening a file shows its current content, which may differ from this turn. These details remain in server memory only.</p>
      {onRevise && (
        <div aria-label={`Turn ${summary.turn_number} revision actions`} className="agent-turn-details__revision-actions">
          <div>
            <button
              className="button button--ghost"
              disabled={revisionDisabled || revisionBusyMode !== null}
              onClick={() => onRevise("edit")}
              type="button"
            >{revisionBusyMode === "edit" ? "Preparing editable branch…" : "Edit in branch"}</button>
            <button
              className="button button--ghost"
              disabled={automaticRevisionDisabled}
              onClick={() => onRevise(automaticRevisionMode)}
              type="button"
            >{revisionBusyMode === automaticRevisionMode ? "Preparing branch…" : automaticRevisionLabel}</button>
          </div>
          <p className="agent-turn-details__note">
            A revision starts from a new retained branch immediately before this turn. The source chat and existing workspace effects are not rewritten or rolled back.
            {sourceHasAttachments ? " Automatic retry is unavailable because message attachments are never copied into a branch; edit the branch and add them again." : " Protected actions still require their own review."}
          </p>
        </div>
      )}
    </div>
  </details>;
}
