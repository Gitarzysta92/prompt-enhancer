import { useRef } from "react";
import type { ReactNode } from "react";

export interface AgentConversationActivity {
  detail: string;
  label: string;
  tone: string;
}

export function AgentConversationHeader({
  actionCount,
  actions,
  activity,
  details,
  reasoningLabel,
  reasoningState,
  runtimeActions,
  runtimeFeedback,
  runtimeNote,
  runtimeState,
  runtimeStatus,
  showRuntimeNotice,
  turnCount,
}: {
  actionCount: number;
  actions: ReactNode;
  activity: AgentConversationActivity;
  details: ReactNode;
  reasoningLabel: string;
  reasoningState: "enabled" | "off" | "visible";
  runtimeActions?: ReactNode;
  runtimeFeedback?: ReactNode;
  runtimeNote?: ReactNode;
  runtimeState: string;
  runtimeStatus: string;
  showRuntimeNotice: boolean;
  turnCount: number;
}) {
  const detailsRef = useRef<HTMLDetailsElement>(null);

  function closeDetails(): void {
    const disclosure = detailsRef.current;
    if (!disclosure) return;
    disclosure.open = false;
    disclosure.querySelector<HTMLElement>("summary")?.focus();
  }

  return (
    <header className="agent__session-header">
      <section aria-label="Agent activity status" className="agent__activity-overview">
        <div className="agent__run-state" data-tone={activity.tone}>
          <span aria-hidden="true" className="agent__run-dot" />
          <span>
            <strong>{activity.label}</strong>
            <small>{activity.detail}</small>
          </span>
        </div>
        <div aria-label="Session activity facts" className="agent__run-facts">
          <span>{turnCount} {turnCount === 1 ? "turn" : "turns"}</span>
          <span>{actionCount} observed {actionCount === 1 ? "action" : "actions"}</span>
          <span data-reasoning={reasoningState}>{reasoningLabel}</span>
        </div>
        <div className="agent__run-actions">
          {actions}
          <details className="agent__session-details" ref={detailsRef}>
            <summary className="button button--ghost">Chat details</summary>
            <div aria-label="Chat details" className="agent__session-details-card" role="group">
              <header className="agent__session-details-head">
                <strong>Session facts</strong>
                <button className="button button--ghost" onClick={closeDetails} type="button">Close chat details</button>
              </header>
              {details}
            </div>
          </details>
        </div>
      </section>

      {showRuntimeNotice ? (
        <div className="agent__model-readiness" data-state={runtimeState}>
          <span id="agent-session-model-status">{runtimeStatus}</span>
          {runtimeActions && <div className="agent__model-actions">{runtimeActions}</div>}
          {runtimeNote}
          {runtimeFeedback}
        </div>
      ) : (
        <span className="sr-only" id="agent-session-model-status">{runtimeStatus}</span>
      )}
    </header>
  );
}
