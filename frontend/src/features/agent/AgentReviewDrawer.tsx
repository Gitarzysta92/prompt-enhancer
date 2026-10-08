import { useRef, type KeyboardEvent, type ReactNode } from "react";

import "./AgentReviewDrawer.css";

export type AgentReviewView = "files" | "changes";

type Props = {
  activeView: AgentReviewView;
  changesPanel: ReactNode;
  filesPanel: ReactNode;
  onActiveViewChange: (view: AgentReviewView) => void;
  onClose: () => void;
};

const REVIEW_VIEWS: readonly AgentReviewView[] = ["files", "changes"];

export function AgentReviewDrawer({
  activeView,
  changesPanel,
  filesPanel,
  onActiveViewChange,
  onClose,
}: Props) {
  const filesTab = useRef<HTMLButtonElement | null>(null);
  const changesTab = useRef<HTMLButtonElement | null>(null);

  function select(view: AgentReviewView, focus: boolean): void {
    onActiveViewChange(view);
    if (focus) (view === "files" ? filesTab.current : changesTab.current)?.focus();
  }

  function moveTab(event: KeyboardEvent<HTMLDivElement>): void {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = REVIEW_VIEWS.indexOf(activeView);
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? REVIEW_VIEWS.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + REVIEW_VIEWS.length) % REVIEW_VIEWS.length;
    select(REVIEW_VIEWS[next], true);
  }

  return (
    <aside aria-label="Files and review drawer" className="agent-review" data-active-view={activeView}>
      <header className="agent-review__head">
        <span>
          <small>Workspace</small>
          <strong>Files &amp; review</strong>
        </span>
        <div aria-label="Files and review sections" className="agent-review__tabs" onKeyDown={moveTab} role="tablist">
          <button
            aria-controls="agent-review-files-panel"
            aria-selected={activeView === "files"}
            id="agent-review-files-tab"
            onClick={() => select("files", false)}
            ref={filesTab}
            role="tab"
            tabIndex={activeView === "files" ? 0 : -1}
            type="button"
          >Files</button>
          <button
            aria-controls="agent-review-changes-panel"
            aria-selected={activeView === "changes"}
            id="agent-review-changes-tab"
            onClick={() => select("changes", false)}
            ref={changesTab}
            role="tab"
            tabIndex={activeView === "changes" ? 0 : -1}
            type="button"
          >Changes</button>
        </div>
        <button aria-label="Hide workspace" className="button button--ghost" onClick={onClose} type="button">Close</button>
      </header>

      <div
        aria-labelledby="agent-review-files-tab"
        className="agent-review__panel"
        hidden={activeView !== "files"}
        id="agent-review-files-panel"
        role="tabpanel"
      >{filesPanel}</div>
      <div
        aria-labelledby="agent-review-changes-tab"
        className="agent-review__panel agent-review__panel--changes"
        hidden={activeView !== "changes"}
        id="agent-review-changes-panel"
        role="tabpanel"
      >{changesPanel}</div>
    </aside>
  );
}
