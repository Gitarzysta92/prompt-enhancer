import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectTimeline } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { ProjectTimelinePane, safeProjectTimeline } from "./ProjectTimelinePane";

const PROJECT = "b".repeat(64);
const S1 = "1".repeat(64);
const S2 = "2".repeat(64);

function timeline(): ProjectTimeline {
  return {
    contract_version: "project-timeline.v1" as const,
    project_id: PROJECT,
    project_display_name: "example-app",
    providers: ["claude_code", "codex"],
    first_started_at: "2026-03-01T09:00:00Z",
    last_ended_at: "2026-03-05T12:00:00Z",
    sessions: [
      { session_id: S1, provider: "codex", display_name: "Plan the uploader", started_at: "2026-03-01T09:00:00Z", ended_at: "2026-03-01T10:00:00Z", terminal_state: "completed", events_complete: true },
      { session_id: S2, provider: "claude_code", display_name: "Add retries", started_at: "2026-03-05T09:00:00Z", ended_at: "2026-03-05T12:00:00Z", terminal_state: null, events_complete: true },
    ],
    tasks: [
      { task_id: "c".repeat(64), revision: 1, task_type: "unknown", lifecycle_state: "reviewed", session_ids: [S1], display_name: "Plan the uploader", started_at: "2026-03-01T09:00:00Z", ended_at: "2026-03-01T10:00:00Z" },
    ],
    activity: [{ day: "2026-03-01", sessions: 1 }, { day: "2026-03-05", sessions: 1 }],
    sessions_drawn: 2,
    truncated: false,
  };
}

describe("ProjectTimelinePane", () => {
  it("validates the contract", () => {
    expect(safeProjectTimeline(timeline())).toBe(true);
    expect(safeProjectTimeline({ ...timeline(), contract_version: "x" })).toBe(false);
  });

  it("draws task windows and sessions, and opens a session on click", async () => {
    const onOpenSession = vi.fn();
    const getProjectTimeline = vi.fn(async (_id: string, _signal?: AbortSignal) => timeline());
    const { container } = render(<ProjectTimelinePane onOpenSession={onOpenSession} projectId={PROJECT} transport={{ getProjectTimeline }} />);
    await screen.findByRole("heading", { name: "Tasks and sessions over time" });
    expect(getProjectTimeline).toHaveBeenCalledWith(PROJECT, expect.anything());
    expect(container.querySelectorAll(".project-timeline__task").length).toBe(1);
    expect(container.querySelectorAll(".project-timeline__session").length).toBe(2);
    expect(container.querySelectorAll(".project-timeline__activity").length).toBe(2);
    expect(screen.getByText("Active days").nextSibling?.textContent).toBe("2");
    fireEvent.click(container.querySelectorAll(".project-timeline__session")[1]);
    expect(onOpenSession).toHaveBeenCalledWith(S2);
    // The 30-day range keeps both sessions (they are four days apart).
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    expect(container.querySelectorAll(".project-timeline__session").length).toBe(2);
  });

  it("hides itself when the project has no timeline", async () => {
    const missing = vi.fn(async () => { throw new TransportError("nope", 404); });
    const { container } = render(<ProjectTimelinePane projectId={PROJECT} transport={{ getProjectTimeline: missing }} />);
    await vi.waitFor(() => expect(missing).toHaveBeenCalled());
    await vi.waitFor(() => expect(container.textContent).toBe(""));
  });

  it("refreshes in place: keeps the selected range and flags failed refreshes with retry", async () => {
    let fail = false;
    const getProjectTimeline = vi.fn(async () => {
      if (fail) throw new TransportError("boom", 500);
      return timeline();
    });
    const transport = { getProjectTimeline };
    const { rerender } = render(<ProjectTimelinePane projectId={PROJECT} refreshToken={0} transport={transport} />);
    await screen.findByRole("heading", { name: "Tasks and sessions over time" });
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");

    rerender(<ProjectTimelinePane projectId={PROJECT} refreshToken={1} transport={transport} />);
    await vi.waitFor(() => expect(getProjectTimeline).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/The last refresh failed/)).toBeNull();

    fail = true;
    rerender(<ProjectTimelinePane projectId={PROJECT} refreshToken={2} transport={transport} />);
    await screen.findByText(/The last refresh failed/);
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(getProjectTimeline).toHaveBeenCalledTimes(4));
    await vi.waitFor(() => expect(screen.queryByText(/The last refresh failed/)).toBeNull());
  });

  it.each([403, 404])("clears the retained project timeline after an authoritative %s refresh response", async (status) => {
    const transport = { getProjectTimeline: vi.fn().mockResolvedValueOnce(timeline()).mockRejectedValueOnce(new TransportError("synthetic withdrawal", status)) };
    const { rerender } = render(<ProjectTimelinePane refreshToken={0} projectId={PROJECT} transport={transport} />);
    await screen.findByRole("heading", { name: "Tasks and sessions over time" });
    rerender(<ProjectTimelinePane refreshToken={1} projectId={PROJECT} transport={transport} />);
    await vi.waitFor(() => expect(screen.queryByRole("heading", { name: "Tasks and sessions over time" })).toBeNull());
    expect(screen.queryByText(/showing the last verified timeline/)).toBeNull();
  });

  it("drops the previous project's chart and range when the project changes", async () => {
    const OTHER = "f".repeat(64);
    const getProjectTimeline = vi.fn(async (id: string) => ({ ...timeline(), project_id: id }));
    const transport = { getProjectTimeline };
    const { container, rerender } = render(<ProjectTimelinePane projectId={PROJECT} transport={transport} />);
    await screen.findByRole("heading", { name: "Tasks and sessions over time" });
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));

    rerender(<ProjectTimelinePane projectId={OTHER} transport={transport} />);
    expect(container.querySelector(".project-timeline__session")).toBeNull();
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();

    await screen.findByRole("heading", { name: "Tasks and sessions over time" });
    expect(getProjectTimeline).toHaveBeenLastCalledWith(OTHER, expect.anything());
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });
});
