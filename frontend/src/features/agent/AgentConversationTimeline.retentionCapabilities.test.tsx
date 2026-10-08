import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentCatalogSession } from "../../shared/api/contracts";
import { RetainedHistoryView } from "./AgentConversationTimeline";

const SESSION = "a".repeat(32);

function session(): AgentCatalogSession {
  return {
    contract_version: "agent-catalog.v2",
    session_id: SESSION,
    project_id: "b".repeat(32),
    title: "Synthetic retained conversation",
    workspace: "D:\\example\\retained",
    model_alias: null,
    created_at: "2040-01-01T00:00:00Z",
    updated_at: "2040-01-01T00:01:00Z",
    last_opened_at: "2040-01-01T00:00:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    history_state: "durable_local",
    retention_policy: "local_history",
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: true,
    lineage: null,
  };
}

function renderHistory(
  resumeSupported: boolean,
  exportSupported: boolean,
  onResume = vi.fn(),
  onExport = vi.fn(),
  options: {
    archivedAt?: string | null;
    exportBusy?: boolean;
    resumeBusy?: boolean;
    state?: "idle" | "loading" | "ready" | "error";
    message?: string;
  } = {},
) {
  const retained = session();
  retained.archived_at = options.archivedAt ?? null;
  render(
    <RetainedHistoryView
      artifactsPanel={null}
      events={[]}
      exportBusy={options.exportBusy ?? false}
      exportSupported={exportSupported}
      focusTurnRequest={null}
      forkBusy={false}
      forkSupported={false}
      message={options.message ?? ""}
      onClear={vi.fn()}
      onExport={onExport}
      onFork={vi.fn()}
      onNewChat={vi.fn()}
      onResume={onResume}
      onReviseTurn={undefined}
      resumeBusy={options.resumeBusy ?? false}
      resumeSupported={resumeSupported}
      session={retained}
      state={options.state ?? "ready"}
      turnRevisionBusy={null}
    />,
  );
  return { onResume, onExport };
}

describe("RetainedHistoryView transport capabilities", () => {
  it("shows accessible disabled reasons and cannot invoke unsupported actions", () => {
    const { onResume, onExport } = renderHistory(false, false);
    const resume = screen.getByRole("button", { name: "Resume unavailable" });
    const exportButton = screen.getByRole("button", { name: "Export unavailable" });

    expect(resume).toBeDisabled();
    expect(exportButton).toBeDisabled();
    expect(resume).toHaveAccessibleDescription(/transport does not provide retained-session resume/i);
    expect(exportButton).toHaveAccessibleDescription(/transport does not provide retained-history export/i);
    fireEvent.click(resume);
    fireEvent.click(exportButton);
    expect(onResume).not.toHaveBeenCalled();
    expect(onExport).not.toHaveBeenCalled();
  });

  it("keeps supported resume and export actions enabled and callable when ready", () => {
    const { onResume, onExport } = renderHistory(true, true);
    fireEvent.click(screen.getByRole("button", { name: "Resume chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(onResume).toHaveBeenCalledOnce();
    expect(onExport).toHaveBeenCalledOnce();
  });

  it.each([
    { exportSupported: true, resumeSupported: false, unsupported: "Resume unavailable", supported: "Export JSON" },
    { exportSupported: false, resumeSupported: true, unsupported: "Export unavailable", supported: "Resume chat" },
  ])("gates mixed optional capabilities independently", ({ exportSupported, resumeSupported, unsupported, supported }) => {
    renderHistory(resumeSupported, exportSupported);
    expect(screen.getByRole("button", { name: unsupported })).toBeDisabled();
    expect(screen.getByRole("button", { name: supported })).toBeEnabled();
  });

  it("preserves the resume busy gate independently of export capability support", () => {
    renderHistory(true, true, vi.fn(), vi.fn(), { resumeBusy: true });
    expect(screen.getByRole("button", { name: "Resuming…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeEnabled();
  });

  it("preserves the export busy gate independently of resume capability support", () => {
    renderHistory(true, true, vi.fn(), vi.fn(), { exportBusy: true });
    expect(screen.getByRole("button", { name: "Resume chat" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Exporting…" })).toBeDisabled();
  });

  it("keeps export available for an archived retained chat while resume stays disabled", () => {
    renderHistory(true, true, vi.fn(), vi.fn(), { archivedAt: "2040-01-01T00:02:00Z" });
    expect(screen.getByRole("button", { name: "Restore chat before resuming" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeEnabled();
  });

  it("keeps both supported actions disabled and reports retained-history errors", () => {
    renderHistory(true, true, vi.fn(), vi.fn(), { state: "error", message: "Synthetic retained history failure" });
    expect(screen.getByRole("button", { name: "Resume chat" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Synthetic retained history failure");
  });

  it("preserves ready-state gating for supported actions while loading", () => {
    render(
      <RetainedHistoryView
        artifactsPanel={null}
        events={[]}
        exportBusy={false}
        exportSupported
        focusTurnRequest={null}
        forkBusy={false}
        forkSupported={false}
        message=""
        onClear={vi.fn()}
        onExport={vi.fn()}
        onFork={vi.fn()}
        onNewChat={vi.fn()}
        onResume={vi.fn()}
        onReviseTurn={undefined}
        resumeBusy={false}
        resumeSupported
        session={session()}
        state="loading"
        turnRevisionBusy={null}
      />,
    );
    expect(screen.getByRole("button", { name: "Resume chat" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeDisabled();
  });
});
