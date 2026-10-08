import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TransportError } from "../../shared/api/httpTransport";
import { LiveMiniWindow, openLiveWindow } from "./LiveMiniWindow";

const PROJECT = "a".repeat(64);
const SESSION = "b".repeat(64);

function sessionsPage() {
  return {
    sessions: [{ session_id: SESSION, project_id: PROJECT, provider: "claude_code", session_display_name: "Add retries", project_display_name: "example-app" }],
    limit: 100, offset: 0, total: 1, has_more: false,
  };
}

function liveSessionTimeline() {
  return {
    contract_version: "session-timeline.v1" as const,
    session_id: SESSION,
    provider: "claude_code",
    project_id: PROJECT,
    project_display_name: "example-app",
    session_display_name: "Add retries",
    started_at: "2026-03-02T09:00:00Z",
    ended_at: "2026-03-02T09:10:00Z",
    events_complete: true,
    truncated: false,
    turns: [{ index: 0, started_at: "2026-03-02T09:00:00Z", ended_at: "2026-03-02T09:04:00Z" }],
    tools: [],
    markers: [],
    usage: { requests: 0, input_tokens: null, output_tokens: null, cached_input_tokens: null },
    counts: { events: 1, turns: 1, tools: 0, verifications_passed: 0, verifications_failed: 0, verifications_unknown: 0, tool_errors: 0 },
  };
}

describe("LiveMiniWindow", () => {
  it("opens one named popup per project or session", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    openLiveWindow({ name: "live", projectId: PROJECT });
    openLiveWindow({ name: "live", projectId: PROJECT, sessionId: SESSION });
    expect(open).toHaveBeenCalledTimes(2);
    expect(open.mock.calls[0][0]).toBe(`/live/projects/${PROJECT}`);
    expect(open.mock.calls[0][1]).toBe(`pe-live-${PROJECT.slice(0, 12)}-project`);
    expect(open.mock.calls[1][1]).toBe(`pe-live-${PROJECT.slice(0, 12)}-${SESSION.slice(0, 12)}`);
    expect(String(open.mock.calls[0][2])).toContain("width=480");
    open.mockRestore();
  });

  it("shows a session by name with its latest analysis, job and timeline", async () => {
    const transport = {
      listProjectSessions: vi.fn(async () => ({
        sessions: [{ session_id: SESSION, project_id: PROJECT, provider: "claude_code", session_display_name: "Add retries", project_display_name: "example-app" }],
        limit: 100, offset: 0, total: 1, has_more: false,
      })),
      getLatestSessionQualityAnalysis: vi.fn(async () => ({
        run: { run_id: "c".repeat(64), status: "completed" },
        results: [
          { key: "outcome.first_pass_verification", value_state: "known", fraction: { numerator: 1, denominator: 1 } },
          { key: "prompt.task_definition_coverage", value_state: "unknown", fraction: null },
        ],
      })),
      getLatestSessionAnalysisJob: vi.fn(async () => { throw new TransportError("none", 404); }),
      getSessionTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
      getProjectTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
    };
    render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
    await screen.findByRole("heading", { level: 1, name: "Add retries" });
    await screen.findByText("completed · 1/2 known");
    expect(screen.getByText("1/1")).toBeTruthy();
    await screen.findByText("none");
    expect(screen.getByRole("link", { name: "Open in dashboard" }).getAttribute("href")).toContain(`/projects/${PROJECT}/sessions/${SESSION}/metrics/prompt-quality`);
    expect(screen.getByText(/every 20s/)).toBeTruthy();
  });

  it("refreshes without remounting the timeline pane, keeping its zoom state", async () => {
    const transport = {
      listProjectSessions: vi.fn(async () => sessionsPage()),
      getLatestSessionQualityAnalysis: vi.fn(async () => { throw new TransportError("none", 404); }),
      getLatestSessionAnalysisJob: vi.fn(async () => { throw new TransportError("none", 404); }),
      getSessionTimeline: vi.fn(async () => liveSessionTimeline()),
      getProjectTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
    };
    render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
    const chart = await screen.findByRole("group", { name: /use plus and minus to zoom/i });
    fireEvent.keyDown(chart, { key: "+" });
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => expect(transport.getSessionTimeline).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    await screen.findByText("none yet");
  });

  it("preserves the mounted chart and zoom during the automatic 20-second refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const transport = {
        listProjectSessions: vi.fn(async () => sessionsPage()),
        getLatestSessionQualityAnalysis: vi.fn().mockRejectedValue(new TransportError("none", 404)),
        getLatestSessionAnalysisJob: vi.fn().mockRejectedValue(new TransportError("none", 404)),
        getSessionTimeline: vi.fn(async () => liveSessionTimeline()),
        getProjectTimeline: vi.fn(),
      };
      render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
      const chart = await screen.findByRole("group", { name: /use plus and minus to zoom/i });
      fireEvent.keyDown(chart, { key: "+" });
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
      expect(transport.getSessionTimeline).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("group", { name: /use plus and minus to zoom/i })).toBe(chart);
      expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    } finally { vi.useRealTimers(); }
  });

  it("clears metadata immediately when the same IDs move to a different transport", async () => {
    const first = {
      listProjectSessions: vi.fn(async () => sessionsPage()),
      getLatestSessionQualityAnalysis: vi.fn().mockRejectedValue(new TransportError("none", 404)),
      getLatestSessionAnalysisJob: vi.fn().mockRejectedValue(new TransportError("none", 404)),
      getSessionTimeline: vi.fn().mockRejectedValue(new TransportError("none", 404)),
      getProjectTimeline: vi.fn(),
    };
    const { rerender } = render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={first as never} />);
    await screen.findByRole("heading", { name: "Add retries" });
    const second = { ...first, listProjectSessions: vi.fn(() => new Promise(() => undefined)) };
    rerender(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={second as never} />);
    expect(screen.queryByRole("heading", { name: "Add retries" })).toBeNull();
    expect(screen.queryByText("example-app")).toBeNull();
    expect(screen.queryByText("none yet")).toBeNull();
  });

  it("marks metadata unavailable when the latest analysis or job cannot be fetched", async () => {
    const transport = {
      listProjectSessions: vi.fn(async () => sessionsPage()),
      getLatestSessionQualityAnalysis: vi.fn(async () => { throw new TransportError("boom", 500); }),
      getLatestSessionAnalysisJob: vi.fn(async () => { throw new TransportError("down", 503); }),
      getSessionTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
      getProjectTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
    };
    render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
    await vi.waitFor(() => expect(screen.getAllByText("unavailable").length).toBe(2));
    expect(screen.queryByText("none yet")).toBeNull();
    expect(screen.queryByText("none")).toBeNull();
  });

  it.each([{}, { numerator: 1, denominator: 0 }, { numerator: -1, denominator: 2 }, { numerator: 3, denominator: 2 }, { numerator: 0.5, denominator: 2 }])("shows unknown for an invalid known first-pass fraction %j", async (fraction) => {
    const transport = {
      listProjectSessions: vi.fn(async () => sessionsPage()),
      getLatestSessionQualityAnalysis: vi.fn(async () => ({
        run: { run_id: "c".repeat(64), status: "completed" },
        results: [{ key: "outcome.first_pass_verification", value_state: "known", fraction }],
      })),
      getLatestSessionAnalysisJob: vi.fn(async () => { throw new TransportError("none", 404); }),
      getSessionTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
      getProjectTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
    };
    const { container } = render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
    await screen.findByText("completed · 1/1 known");
    expect(screen.getByText("unknown")).toBeTruthy();
    expect(container.textContent).not.toContain("undefined");
  });

  it("reports an initial load failure instead of loading forever, and marks later failures stale", async () => {
    let fail = true;
    const transport = {
      listProjectSessions: vi.fn(async () => { if (fail) throw new TransportError("boom", 500); return sessionsPage(); }),
      getLatestSessionQualityAnalysis: vi.fn(async () => { throw new TransportError("none", 404); }),
      getLatestSessionAnalysisJob: vi.fn(async () => { throw new TransportError("none", 404); }),
      getSessionTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
      getProjectTimeline: vi.fn(async () => { throw new TransportError("none", 404); }),
    };
    render(<LiveMiniWindow projectId={PROJECT} sessionId={SESSION} transport={transport as never} />);
    await screen.findByText(/Could not load · use Refresh to retry/);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(/^Updated /);
    fail = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(/· stale/);
  });
});
