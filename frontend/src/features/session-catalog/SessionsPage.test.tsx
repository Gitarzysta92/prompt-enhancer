import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CodexSession } from "../../shared/api/contracts";
import { SessionsPage, durationLabel, safeSessionRow } from "./SessionsPage";

function row(input: {
  id: string;
  project: string;
  projectName: string | null;
  title: string | null;
  provider: CodexSession["provider"];
  started: string;
  ended?: string | null;
}): CodexSession {
  return {
    session_id: input.id.repeat(64).slice(0, 64),
    installation_id: "1".repeat(64),
    project_id: input.project.repeat(64).slice(0, 64),
    project_display_name: input.projectName,
    session_display_name: input.title,
    provider: input.provider,
    project_display_name_origin: input.projectName ? "provider" : "unknown",
    session_display_name_origin: input.title ? "provider" : "unknown",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: input.started,
    ended_at: input.ended ?? null,
    terminal_state: null,
    events_complete: false,
  };
}

const ROWS: CodexSession[] = [
  row({ id: "a", project: "1", projectName: "prompt-enhancer", title: "Add retries to the uploader", provider: "claude_code", started: "2040-02-02T09:00:00Z", ended: "2040-02-02T09:42:00Z" }),
  row({ id: "b", project: "1", projectName: "prompt-enhancer", title: "Refactor discovery inbox", provider: "codex", started: "2040-02-01T09:00:00Z", ended: "2040-02-01T12:05:00Z" }),
  row({ id: "c", project: "2", projectName: "example-observatory", title: null, provider: "codex", started: "2040-01-30T09:00:00Z" }),
];

function transportWith(rows: CodexSession[]) {
  return { listCodexSessions: vi.fn(async (_limit: number, _offset: number) => ({ sessions: rows, limit: 100, offset: 0 })) };
}

describe("SessionsPage", () => {
  it("lists every session newest first by name, never by identifier", async () => {
    const transport = transportWith(ROWS);
    render(<SessionsPage navigate={vi.fn()} transport={transport} />);
    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(within(items[0]).getByText("Add retries to the uploader")).toBeInTheDocument();
    expect(within(items[0]).getByText("prompt-enhancer")).toBeInTheDocument();
    expect(within(items[0]).getByLabelText("Source: Claude Code")).toBeInTheDocument();
    expect(within(items[0]).getByText("42 min")).toBeInTheDocument();
    expect(within(items[1]).getByText("3 h 5 min")).toBeInTheDocument();
    expect(within(items[2]).getByText("Untitled session")).toBeInTheDocument();
    expect(within(items[2]).getByText("End not recorded")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 sessions · 1 without a title/)).toBeInTheDocument();
    for (const r of ROWS) {
      expect(document.body.textContent).not.toContain(r.session_id);
      expect(document.body.textContent).not.toContain(r.project_id);
    }
  });

  it("filters by source and searches by project or title, and opens the session route", async () => {
    const navigate = vi.fn();
    render(<SessionsPage navigate={navigate} transport={transportWith(ROWS)} />);
    await screen.findAllByRole("listitem");
    fireEvent.click(screen.getByRole("button", { name: "Claude Code" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "All sources" }));
    fireEvent.change(screen.getByLabelText("Search sessions by project or title"), { target: { value: "observatory" } });
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    fireEvent.click(within(items[0]).getAllByRole("button")[0]);
    expect(navigate).toHaveBeenCalledWith({
      name: "session_metrics",
      projectId: ROWS[2].project_id,
      sessionId: ROWS[2].session_id,
      category: "readiness",
    });
  });

  it("fails closed on an invalid catalog row and explains an empty store", async () => {
    render(<SessionsPage navigate={vi.fn()} transport={transportWith([{ ...ROWS[0], session_id: "not-a-pseudonym" }])} />);
    await waitFor(() => expect(screen.getByText(/response was invalid/)).toBeInTheDocument());
    expect(safeSessionRow({ ...ROWS[0], provider: "mystery" })).toBe(false);
    expect(safeSessionRow({ ...ROWS[0], session_display_name: "line\nbreak" })).toBe(false);
    expect(durationLabel("2040-01-01T00:00:00Z", "2040-01-01T00:00:30Z")).toBe("30s");
    expect(durationLabel("bad", null)).toBe("Start unknown");
  });

  it("shows an empty state that points at the Data sources page", async () => {
    render(<SessionsPage navigate={vi.fn()} runtimeMode="local_real" transport={transportWith([])} />);
    expect(await screen.findByText("No sessions captured yet")).toBeInTheDocument();
    expect(screen.getByText(/Data sources page/)).toBeInTheDocument();
  });

  it("keeps the partial-search warning visible with no matches and loads the next bounded page", async () => {
    const rows = Array.from({ length: 1001 }, (_, index) => ({ ...ROWS[0], session_id: index.toString(16).padStart(64, "0"), session_display_name: index === 1000 ? "Example beyond first batch" : `Example session ${index}` }));
    const listCodexSessions = vi.fn(async (limit: number, offset: number) => ({ sessions: rows.slice(offset, offset + limit), limit, offset }));
    render(<SessionsPage navigate={vi.fn()} transport={{ listCodexSessions }} />);
    fireEvent.change(screen.getByLabelText("Search sessions by project or title"), { target: { value: "beyond first batch" } });
    expect(await screen.findByText(/Partial catalog: search covers only the 1000 loaded sessions/)).toBeVisible();
    expect(screen.getByText("No sessions match")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load next 100 sessions" }));
    expect(await screen.findByText("Example beyond first batch")).toBeVisible();
    expect(listCodexSessions).toHaveBeenCalledTimes(11);
    expect(listCodexSessions.mock.calls[10].slice(0, 2)).toEqual([100, 1000]);
    expect(screen.queryByText(/Partial catalog:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load next 100 sessions" })).not.toBeInTheDocument();
  });

  it("keeps a thousand loaded sessions on fixed render pages", async () => {
    const rows = Array.from({ length: 1000 }, (_, index) => ({
      ...ROWS[0],
      session_id: (index + 1).toString(16).padStart(64, "0"),
      session_display_name: `Synthetic session ${index.toString().padStart(4, "0")}`,
      started_at: new Date(Date.parse("2040-01-01T00:00:00Z") + index * 1000).toISOString(),
    }));
    const listCodexSessions = vi.fn(async (limit: number, offset: number) => ({
      sessions: rows.slice(offset, offset + limit),
      limit,
      offset,
    }));
    render(<SessionsPage navigate={vi.fn()} transport={{ listCodexSessions }} />);

    const pager = await screen.findByRole("navigation", { name: "Stored session pages" }, { timeout: 5_000 });
    expect(within(pager).getByText("Showing 1–50 of 1,000")).toBeVisible();
    expect(screen.getAllByRole("listitem")).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing 51–100 of 1,000")).toBeVisible();
    expect(screen.queryByText("Synthetic session 0999")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic session 0949")).toBeVisible();
  });

  it("does not point an empty synthetic preview at an unavailable source page", async () => {
    render(<SessionsPage navigate={vi.fn()} runtimeMode="synthetic_demo" transport={transportWith([])} />);
    expect(await screen.findByText(/This synthetic preview has no session fixtures/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open Data sources" })).not.toBeInTheDocument();
  });

  it("keeps contradictory duration unknown instead of reporting a zero-second session", () => {
    expect(durationLabel("2040-01-02T00:00:00Z", "2040-01-01T00:00:00Z")).toBe("Duration unavailable");
  });
});
