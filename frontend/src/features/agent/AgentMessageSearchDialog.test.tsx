import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentMessageSearchResult } from "../../shared/api/agentMessageSearchContract";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentMessageSearchDialog } from "./AgentMessageSearchDialog";

const PROJECT = "1".repeat(32);
const SESSION = "2".repeat(32);
const SNAPSHOT = "a".repeat(64);

function result(overrides: Partial<AgentMessageSearchResult> = {}): AgentMessageSearchResult {
  return {
    contract_version: "agent-message-search.v1",
    snapshot: SNAPSHOT,
    limit: 20,
    offset: 0,
    total: 1,
    next_offset: null,
    complete: true,
    matches: [{
      session_id: SESSION,
      project_id: PROJECT,
      project_name: "Fictional project",
      title: "Fictional saved chat",
      match_event_seq: 9,
      history_revision: 2,
      role: "assistant",
      excerpt: "Synthetic matching excerpt.",
    }],
    ...overrides,
  };
}

describe("AgentMessageSearchDialog", () => {
  it("submits an explicit trimmed local query and renders plaintext result text", async () => {
    const search = vi.fn().mockResolvedValue(result());
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  synthetic phrase  " } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await waitFor(() => expect(search).toHaveBeenCalledWith(expect.objectContaining({
      query: "synthetic phrase", projectId: PROJECT, includeArchived: false, offset: 0,
    }), expect.any(AbortSignal)));
    expect(await screen.findByText("Synthetic matching excerpt.")).toBeVisible();
    expect(screen.getByRole("dialog", { name: "Search saved messages" })).toBeVisible();
  });

  it("invalidates prior results when the local query changes and retries the exact failed page", async () => {
    const firstMatches = Array.from({ length: 20 }, (_, index) => ({
      ...result().matches[0], session_id: String(index).padStart(32, "0"),
    }));
    const search = vi.fn()
      .mockResolvedValueOnce(result({ next_offset: 20, complete: false, total: 21, matches: firstMatches }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(result({ offset: 20, total: 21, next_offset: null, complete: true, matches: [{ ...result().matches[0], session_id: "3".repeat(32) }] }));
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await screen.findAllByText("Synthetic matching excerpt.");
    fireEvent.click(screen.getByRole("button", { name: "Load more matches" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry search" }));
    await waitFor(() => expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20, snapshot: SNAPSHOT, query: "synthetic" }), expect.any(AbortSignal)));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "changed" } });
    expect(screen.queryByText("Synthetic matching excerpt.")).toBeNull();
  });

  it("retries a failed first page from its frozen request and keeps results through a parent rerender", async () => {
    const search = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(result());
    const onOpenMatch = vi.fn().mockResolvedValue(false);
    const view = render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={onOpenMatch} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry search" }));
    await waitFor(() => expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ query: "synthetic", offset: 0 }), expect.any(AbortSignal)));
    expect(await screen.findByText("Synthetic matching excerpt.")).toBeVisible();
    view.rerender(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={search} />);
    expect(screen.getByText("Synthetic matching excerpt.")).toBeVisible();
  });

  it("invalidates a pending response when the search transport changes", async () => {
    let resolveOld: (value: AgentMessageSearchResult) => void = () => undefined;
    const oldSearch = vi.fn().mockImplementation(() => new Promise<AgentMessageSearchResult>((resolve) => { resolveOld = resolve; }));
    const newSearch = vi.fn();
    const view = render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={oldSearch} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    view.rerender(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={newSearch} />);
    resolveOld(result());
    await waitFor(() => expect(screen.queryByText("Synthetic matching excerpt.")).toBeNull());
    expect(newSearch).not.toHaveBeenCalled();
  });

  it("requires a fresh first page after a snapshot conflict", async () => {
    const search = vi.fn()
      .mockResolvedValueOnce(result({ next_offset: 20, complete: false, total: 21 }))
      .mockRejectedValueOnce(new TransportError("synthetic conflict", 409))
      .mockResolvedValueOnce(result());
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await screen.findByRole("button", { name: "Load more matches" });
    fireEvent.click(screen.getByRole("button", { name: "Load more matches" }));
    expect(await screen.findByText(/results are stale/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Start search again" }));
    await waitFor(() => expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, snapshot: undefined, query: "synthetic" }), expect.any(AbortSignal)));
  });

  it.each([
    ["snapshot", result({ snapshot: "b".repeat(64), offset: 20, total: 21, next_offset: null })],
    ["total", result({ offset: 20, total: 22, next_offset: null })],
    ["limit", result({ offset: 20, limit: 19, total: 21, next_offset: null })],
    ["duplicate chat", result({ offset: 20, total: 21, next_offset: null })],
  ])("requires a new first page when a later page has %s drift", async (_kind, laterPage) => {
    const firstPage = result({ next_offset: 20, complete: false, total: 21 });
    const search = vi.fn().mockResolvedValueOnce(firstPage).mockResolvedValueOnce(laterPage).mockResolvedValueOnce(result());
    const onOpenMatch = vi.fn().mockResolvedValue(false);
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={onOpenMatch} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await screen.findByRole("button", { name: "Load more matches" });
    fireEvent.click(screen.getByRole("button", { name: "Load more matches" }));
    expect(await screen.findByText(/results are stale/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /Open matching saved message/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Load more matches" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Open matching saved message/i }));
    expect(onOpenMatch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start search again" }));
    await waitFor(() => expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, snapshot: undefined, query: "synthetic" }), expect.any(AbortSignal)));
  });

  it("disables loaded matches while another page is loading", async () => {
    let resolveLaterPage: (value: AgentMessageSearchResult) => void = () => undefined;
    const search = vi.fn()
      .mockResolvedValueOnce(result({ next_offset: 20, complete: false, total: 21 }))
      .mockImplementationOnce(() => new Promise<AgentMessageSearchResult>((resolve) => { resolveLaterPage = resolve; }));
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={vi.fn().mockResolvedValue(false)} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await screen.findByRole("button", { name: "Load more matches" });
    fireEvent.click(screen.getByRole("button", { name: "Load more matches" }));
    expect(screen.getByRole("button", { name: /Open matching saved message/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Searching…" })).toBeDisabled();
    resolveLaterPage(result({ offset: 20, total: 21, next_offset: null, matches: [{ ...result().matches[0], session_id: "3".repeat(32) }] }));
    await screen.findByText("2 of 21 matching chats loaded.");
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Open matching saved message/i }).every((button) => !button.hasAttribute("disabled"))).toBe(true));
  });

  it("cancels a delayed open when the phrase changes and permits the next search", async () => {
    let resolveOpen: (value: boolean) => void = () => undefined;
    const search = vi.fn().mockResolvedValue(result()).mockResolvedValue(result({ matches: [{ ...result().matches[0], excerpt: "Synthetic new phrase" }] }));
    const onOpenMatch = vi.fn().mockImplementation(() => new Promise<boolean>((resolve) => { resolveOpen = resolve; }));
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={vi.fn()} onOpenMatch={onOpenMatch} search={search} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    fireEvent.click(await screen.findByRole("button", { name: /Open matching saved message/i }));
    expect(screen.getByRole("button", { name: "Search saved messages" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Opening matching saved message/i })).toBeDisabled();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new phrase" } });
    expect(screen.getByRole("button", { name: "Search saved messages" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    await waitFor(() => expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ query: "new phrase", offset: 0 }), expect.any(AbortSignal)));
    resolveOpen(true);
    expect(onOpenMatch).toHaveBeenCalledTimes(1);
  });

  it("aborts on Escape and ignores a late successful open", async () => {
    let resolveOpen: (value: boolean) => void = () => undefined;
    const onClose = vi.fn();
    const onOpenMatch = vi.fn().mockImplementation(() => new Promise<boolean>((resolve) => { resolveOpen = resolve; }));
    render(<AgentMessageSearchDialog initialProjectId={PROJECT} onClose={onClose} onOpenMatch={onOpenMatch} search={vi.fn().mockResolvedValue(result())} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    fireEvent.click(await screen.findByRole("button", { name: /Open matching saved message/i }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    resolveOpen(true);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
