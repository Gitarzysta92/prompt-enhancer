import type { McpManagedServer } from "../../shared/api/contracts";
import {
  beginTrustedMcpAcceptance,
  trustedMcpBaselineIssue,
  trustedMcpStepPassed,
  type TrustedMcpAcceptanceRun,
  type TrustedMcpAcceptanceStep,
} from "./trustedMcpAcceptance";
import "./AgentMcpAcceptancePanel.css";

const STEPS: readonly { key: TrustedMcpAcceptanceStep; label: string }[] = [
  { key: "baseline", label: "Clean reviewed MCPB plan" },
  { key: "install", label: "Verified install and probe cleanup" },
  { key: "project_admission", label: "Exact project and tools admitted" },
  { key: "host_start", label: "Hidden host ready and project-scoped" },
  { key: "tool_call", label: "Freshly approved model tool call" },
  { key: "host_stop", label: "Host, process, lease and routing stopped" },
  { key: "update", label: "Verified update with rollback retained" },
  { key: "rollback", label: "No-execution rollback completed" },
  { key: "rollback_cleanup", label: "Retained rollback generation removed" },
  { key: "uninstall", label: "Package removed with zero authority" },
];

const NEXT_ACTION: Record<Exclude<TrustedMcpAcceptanceRun["phase"], "complete">, string> = {
  install: "Use the normal Install control below and approve its exact native preview.",
  project_admission: "Choose this active project, admit at least one reviewed tool, and save the project admission.",
  host_start: "Start this project tool host with the normal runtime control.",
  tool_call: "Return to this same chat and let the model request one admitted MCP tool; approve that one call.",
  host_stop: "Return here and stop the project tool host. Cleanup must be verified.",
  update: "Apply one exact Registry update after reviewing its native preview.",
  rollback: "Roll back to the original verified generation without starting it.",
  rollback_cleanup: "Remove the retained superseded generation without starting it.",
  uninstall: "Uninstall the restored package and verify the final authority-free state.",
};

function nextAction(run: TrustedMcpAcceptanceRun): string {
  return run.phase === "complete" ? "" : NEXT_ACTION[run.phase];
}

export function AgentMcpAcceptancePanel({
  activeProjectId,
  activeSessionId,
  eventHead,
  onRunChange,
  run,
  server,
}: {
  activeProjectId: string | null;
  activeSessionId: string | null;
  eventHead: number;
  onRunChange: (run: TrustedMcpAcceptanceRun | null) => void;
  run: TrustedMcpAcceptanceRun | null;
  server: McpManagedServer;
}) {
  const baselineIssue = trustedMcpBaselineIssue(server, activeProjectId, activeSessionId);
  const boundElsewhere = run !== null && run.managementId !== server.management_id;
  const complete = run?.phase === "complete" && run.invalidReason === null;

  function begin(): void {
    if (baselineIssue !== null || activeProjectId === null || activeSessionId === null) return;
    onRunChange(beginTrustedMcpAcceptance(
      server,
      activeProjectId,
      activeSessionId,
      eventHead,
    ));
  }

  return (
    <section aria-label="Trusted MCP lifecycle acceptance" className="agent-mcp-acceptance">
      <header>
        <span>
          <small>Release acceptance · guided, never automatic</small>
          <h4>Trusted MCP lifecycle proof</h4>
        </span>
        <strong data-state={complete ? "passed" : run ? boundElsewhere || run.invalidReason ? "blocked" : "active" : "idle"}>
          {complete ? "Complete" : run ? boundElsewhere ? "Other plan" : run.invalidReason ? "Invalid" : "In progress" : "Off"}
        </strong>
      </header>
      <p>
        This page-only ledger observes exact successful receipts from the controls you use. It never installs,
        starts, calls, updates, rolls back, or removes anything by itself.
      </p>
      <small className="agent-mcp-acceptance__memory">
        It survives closing Settings and clears on app reload. Prompts, arguments, results, credentials, paths,
        package bytes and process output are never copied into it.
      </small>

      {run === null ? (
        <div className="agent-mcp-acceptance__begin">
          <button className="button button--ghost" disabled={baselineIssue !== null} onClick={begin} type="button">
            Begin trusted MCP proof
          </button>
          {baselineIssue !== null && <small>{baselineIssue}</small>}
        </div>
      ) : boundElsewhere ? (
        <div className="agent-mcp-acceptance__notice" role="status">
          <strong>A proof is already bound to another managed server.</strong>
          <p>Return to that server’s plan to continue, or clear its page-only receipt and begin again here.</p>
          <button className="button button--ghost" onClick={() => onRunChange(null)} type="button">Clear page-only receipt</button>
        </div>
      ) : (
        <>
          <ol className="agent-mcp-acceptance__steps">
            {STEPS.map((item) => {
              const passed = trustedMcpStepPassed(run, item.key);
              return (
                <li data-state={passed ? "passed" : "waiting"} key={item.key}>
                  <span>{item.label}</span>
                  <strong>{passed ? "Passed" : "Waiting"}</strong>
                </li>
              );
            })}
          </ol>
          <div aria-live="polite" className="agent-mcp-acceptance__notice" role="status">
            {run.invalidReason === "out_of_order" ? (
              <p>A later lifecycle action occurred before its required evidence. This run cannot be combined or reordered; clear it and begin again from a clean plan.</p>
            ) : run.invalidReason === "evidence_invalid" ? (
              <p>A returned receipt did not prove the required scope, cleanup, or zero-authority guarantees. This run is fail-closed; inspect the managed state before beginning again.</p>
            ) : complete ? (
              <p>The same reviewed server, project and live chat completed the full trusted MCP lifecycle with final process, lease, connection and tool authority removed.</p>
            ) : activeProjectId !== run.projectId || activeSessionId !== run.sessionId ? (
              <p>Return to the live Agent chat that began this proof. Evidence is never combined across projects or sessions.</p>
            ) : (
              <p>{nextAction(run)}</p>
            )}
          </div>
          <button className="button button--ghost" onClick={() => onRunChange(null)} type="button">
            Clear page-only receipt
          </button>
        </>
      )}
    </section>
  );
}
