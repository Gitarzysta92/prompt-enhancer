import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionTimeline } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { boundedTemporalSample, SessionTimelinePane, safeTimeline } from "./SessionTimelinePane";

const SESSION = "a".repeat(64);

function timeline(): SessionTimeline {
  return {
    contract_version: "session-timeline.v1" as const,
    session_id: SESSION,
    provider: "claude_code",
    project_id: "b".repeat(64),
    project_display_name: "example-app",
    session_display_name: "Add retries to the uploader",
    started_at: "2026-03-02T09:00:00Z",
    ended_at: "2026-03-02T09:10:00Z",
    events_complete: true,
    truncated: false,
    turns: [
      { index: 0, started_at: "2026-03-02T09:00:00Z", ended_at: "2026-03-02T09:04:00Z" },
      { index: 1, started_at: "2026-03-02T09:05:00Z", ended_at: null },
    ],
    tools: [
      { started_at: "2026-03-02T09:01:00Z", ended_at: "2026-03-02T09:01:30Z", category: "file_write", success: null, duration_ms: 30000, verification: false },
      { started_at: "2026-03-02T09:02:00Z", ended_at: "2026-03-02T09:03:00Z", category: "test", success: true, duration_ms: 60000, verification: true },
      { started_at: "2026-03-02T09:06:00Z", ended_at: "2026-03-02T09:07:00Z", category: "test", success: false, duration_ms: 60000, verification: true },
    ],
    markers: [{ at: "2026-03-02T09:08:00Z", kind: "compaction" }],
    usage: { requests: 3, input_tokens: 12000, output_tokens: 800, cached_input_tokens: null },
    counts: { events: 12, turns: 2, tools: 3, verifications_passed: 1, verifications_failed: 1, verifications_unknown: 0, tool_errors: 1 },
  };
}

describe("SessionTimelinePane", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("validates the contract", () => {
    expect(safeTimeline(timeline())).toBe(true);
    expect(safeTimeline({ ...timeline(), contract_version: "nope" })).toBe(false);
    expect(boundedTemporalSample([0, 1, 2, 3, 4], 3)).toEqual([0, 2, 4]);
    expect(boundedTemporalSample([0, 1], 0)).toEqual([]);
  });

  it("bounds every SVG lane at the maximum synthetic payload", async () => {
    const base = Date.parse("2026-03-02T09:00:00Z");
    const turns = Array.from({ length: 2_000 }, (_, index) => ({
      ended_at: new Date(base + index * 1_000 + 500).toISOString(),
      index,
      started_at: new Date(base + index * 1_000).toISOString(),
    }));
    const tools = Array.from({ length: 2_000 }, (_, index) => ({
      category: index % 2 === 0 ? "test" as const : "file_read" as const,
      duration_ms: 500,
      ended_at: new Date(base + index * 1_000 + 750).toISOString(),
      started_at: new Date(base + index * 1_000 + 250).toISOString(),
      success: true,
      verification: index % 2 === 0,
    }));
    const markers = Array.from({ length: 2_000 }, (_, index) => ({
      at: new Date(base + index * 1_000).toISOString(),
      kind: "compaction" as const,
    }));
    const maximum = {
      ...timeline(),
      counts: { events: 6_000, turns: 2_000, tools: 2_000, verifications_passed: 1_000, verifications_failed: 0, verifications_unknown: 0, tool_errors: 0 },
      ended_at: new Date(base + 2_000_000).toISOString(),
      markers,
      tools,
      turns,
    };
    const { container } = render(<SessionTimelinePane sessionId={SESSION} transport={{
      getSessionTimeline: vi.fn().mockResolvedValue(maximum),
    }} />);

    await screen.findByRole("heading", { name: "What happened, when" });
    expect(container.querySelectorAll(".session-timeline__turn")).toHaveLength(300);
    expect(container.querySelectorAll(".session-timeline__gap")).toHaveLength(300);
    expect(container.querySelectorAll(".session-timeline__tool")).toHaveLength(500);
    expect(container.querySelectorAll(".session-timeline__check")).toHaveLength(200);
    expect(container.querySelectorAll(".session-timeline__marker")).toHaveLength(200);
    expect(screen.getByText("Drawing 1,500 of 8,000 timeline items in this view. Zoom in to reveal more local detail.")).toBeVisible();
  });

  it("draws turns, tools, checks and markers with honest counts", async () => {
    const getSessionTimeline = vi.fn(async (_id: string, _signal?: AbortSignal) => timeline());
    const { container } = render(<SessionTimelinePane sessionId={SESSION} transport={{ getSessionTimeline }} />);
    await screen.findByRole("heading", { name: "What happened, when" });
    expect(getSessionTimeline).toHaveBeenCalledWith(SESSION, expect.anything());
    expect(screen.getAllByText("10m 0s").length).toBeGreaterThan(0);
    expect(screen.getByText("1 passed · 1 failed")).toBeTruthy();
    expect(screen.getByText("3 · 1 failed")).toBeTruthy();
    expect(screen.getByText("12.0k in · 800 out")).toBeTruthy();
    expect(container.querySelectorAll(".session-timeline__turn").length).toBe(2);
    // Verification runs render in the Checks lane with their outcome; plain tools keep their category and mark failures with an outline.
    expect(container.querySelectorAll(".session-timeline__tool").length).toBe(1);
    expect(container.querySelectorAll(".session-timeline__check--passed").length).toBe(1);
    expect(container.querySelectorAll(".session-timeline__check--failed").length).toBe(1);
    expect(container.querySelectorAll(".session-timeline__marker--compaction").length).toBe(1);
    // Nothing textual beyond labels: no command, path or prompt text is rendered.
    expect(container.textContent).not.toMatch(/pytest|\/srv\//);
  });

  it("offers bounded keyboard zoom, directional pan and reset controls with announced position", async () => {
    const getSessionTimeline = vi.fn(async () => timeline());
    render(<SessionTimelinePane sessionId={SESSION} transport={{ getSessionTimeline }} />);
    const chart = await screen.findByRole("group", { name: /use plus and minus to zoom/i });
    const viewControls = screen.getByRole("group", { name: "Timeline view controls" });
    const status = screen.getByRole("status");

    expect(chart).toHaveAttribute("tabindex", "0");
    expect(status).toHaveTextContent("Showing full timeline, from 0s to 10m 0s");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Earlier" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Later" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Full timeline" })).toBeDisabled();

    chart.focus();
    fireEvent.keyDown(chart, { key: "+" });
    expect(status).toHaveTextContent("Showing 5m 0s of 10m 0s, from 2m 30s to 7m 30s");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Earlier" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Later" })).toBeEnabled();

    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(status).toHaveTextContent("Showing 5m 0s of 10m 0s, from 3m 45s to 8m 45s");

    fireEvent.click(screen.getByRole("button", { name: "Earlier" }));
    expect(status).toHaveTextContent("from 2m 30s to 7m 30s");
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(status).toHaveTextContent("from 5m 0s to 10m 0s");
    expect(screen.getByRole("button", { name: "Later" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(status).toHaveTextContent("Showing full timeline, from 0s to 10m 0s");

    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    for (let step = 0; step < 6; step += 1) fireEvent.click(zoomIn);
    expect(status).toHaveTextContent("Showing 9s of 10m 0s, from 4m 55s to 5m 5s");
    expect(zoomIn).toBeDisabled();
    expect(fireEvent.keyDown(chart, { key: "+" })).toBe(true);

    expect(fireEvent.keyDown(chart, { key: "Home" })).toBe(false);
    expect(status).toHaveTextContent("Showing full timeline, from 0s to 10m 0s");
    expect(viewControls).toBeVisible();
  });

  it("applies the same minimum view boundary to pointer brushing", async () => {
    class TestPointerEvent extends MouseEvent {
      readonly pointerId: number;

      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    vi.stubGlobal("PointerEvent", TestPointerEvent);
    const getSessionTimeline = vi.fn(async () => timeline());
    render(<SessionTimelinePane sessionId={SESSION} transport={{ getSessionTimeline }} />);
    const chart = await screen.findByRole("group", { name: /drag horizontally to zoom/i });
    const status = screen.getByRole("status");
    const svg = chart.querySelector("svg")!;
    const setPointerCapture = vi.fn();
    Object.defineProperty(chart, "setPointerCapture", { configurable: true, value: setPointerCapture });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 1000,
      top: 0,
      width: 1000,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.pointerDown(chart, { button: 0, clientX: 400, pointerId: 1 });
    expect(setPointerCapture).toHaveBeenCalledWith(1);
    fireEvent.pointerMove(chart, { clientX: 425, pointerId: 1 });
    expect(Number(chart.querySelector(".session-timeline__brush")?.getAttribute("width"))).toBeCloseTo(25);
    fireEvent.pointerUp(chart, { clientX: 425, pointerId: 1 });

    expect(status).toHaveTextContent("Showing 9s of 10m 0s, from 4m 29s to 4m 38s");
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
  });

  it("hides itself when the runtime has no timeline and reports verification failures", async () => {
    const missing = vi.fn(async () => { throw new TransportError("nope", 404); });
    const { container, unmount } = render(<SessionTimelinePane sessionId={SESSION} transport={{ getSessionTimeline: missing }} />);
    await vi.waitFor(() => expect(missing).toHaveBeenCalled());
    await vi.waitFor(() => expect(container.textContent).toBe(""));
    unmount();
    const broken = vi.fn(async () => ({ contract_version: "other" }));
    render(<SessionTimelinePane sessionId={SESSION} transport={{ getSessionTimeline: broken as never }} />);
    await screen.findByRole("alert");
  });

  it("refreshes in place: keeps zoom and filters, marks failed refreshes stale and retries without mutation", async () => {
    let fail = false;
    const getSessionTimeline = vi.fn(async () => {
      if (fail) throw new TransportError("boom", 500);
      return timeline();
    });
    const transport = { getSessionTimeline };
    const { rerender } = render(<SessionTimelinePane refreshToken={0} sessionId={SESSION} transport={transport} />);
    const chart = await screen.findByRole("group", { name: /use plus and minus to zoom/i });
    fireEvent.keyDown(chart, { key: "+" });
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    fireEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByRole("button", { name: "Write" })).toHaveAttribute("aria-pressed", "false");

    rerender(<SessionTimelinePane refreshToken={1} sessionId={SESSION} transport={transport} />);
    await vi.waitFor(() => expect(getSessionTimeline).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    expect(screen.getByRole("button", { name: "Write" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/The last refresh failed/)).toBeNull();

    fail = true;
    rerender(<SessionTimelinePane refreshToken={2} sessionId={SESSION} transport={transport} />);
    await screen.findByText(/The last refresh failed/);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
    expect(screen.getByRole("button", { name: "Write" })).toHaveAttribute("aria-pressed", "false");

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(getSessionTimeline).toHaveBeenCalledTimes(4));
    await vi.waitFor(() => expect(screen.queryByText(/The last refresh failed/)).toBeNull());
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");
  });

  it.each([403, 404])("clears the retained timeline after an authoritative %s refresh response", async (status) => {
    const transport = { getSessionTimeline: vi.fn().mockResolvedValueOnce(timeline()).mockRejectedValueOnce(new TransportError("synthetic withdrawal", status)) };
    const { rerender } = render(<SessionTimelinePane refreshToken={0} sessionId={SESSION} transport={transport} />);
    await screen.findByRole("heading", { name: "What happened, when" });
    rerender(<SessionTimelinePane refreshToken={1} sessionId={SESSION} transport={transport} />);
    await vi.waitFor(() => expect(screen.queryByRole("heading", { name: "What happened, when" })).toBeNull());
    expect(screen.queryByText(/showing the last verified timeline/)).toBeNull();
  });

  it("resets the view and drops the previous session's data when the session changes", async () => {
    const OTHER = "e".repeat(64);
    const getSessionTimeline = vi.fn(async (id: string) => ({ ...timeline(), session_id: id }));
    const transport = { getSessionTimeline };
    const { container, rerender } = render(<SessionTimelinePane sessionId={SESSION} transport={transport} />);
    const chart = await screen.findByRole("group", { name: /use plus and minus to zoom/i });
    fireEvent.keyDown(chart, { key: "+" });
    expect(screen.getByRole("status")).toHaveTextContent("Showing 5m 0s of 10m 0s");

    rerender(<SessionTimelinePane sessionId={OTHER} transport={transport} />);
    // The previous session's chart must not survive even one render.
    expect(container.querySelector(".session-timeline__turn")).toBeNull();
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();

    await screen.findByRole("heading", { name: "What happened, when" });
    expect(getSessionTimeline).toHaveBeenLastCalledWith(OTHER, expect.anything());
    expect(screen.getByRole("status")).toHaveTextContent("Showing full timeline, from 0s to 10m 0s");
  });
});
