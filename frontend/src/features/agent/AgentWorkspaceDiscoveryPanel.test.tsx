import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentWorkspaceDiscovery, AgentWorkspaceSearchResult } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentWorkspaceDiscoveryPanel } from "./AgentWorkspaceDiscoveryPanel";

const SESSION = "a".repeat(32);

function discovery(overrides: Partial<AgentWorkspaceDiscovery> = {}): AgentWorkspaceDiscovery {
  return {
    contract_version: "local-agent-workspace-discovery.v1",
    session_id: SESSION,
    scope: "selected_workspace",
    inventory_coverage: "complete",
    inventory_reasons: [],
    scanned_entry_count: 3,
    observed_file_count: 3,
    files: [
      { path: "README.md", byte_size: 900, editable_candidate: true },
      { path: "src/example.ts", byte_size: 1_200, editable_candidate: true },
      { path: "src/util.ts", byte_size: 2_400, editable_candidate: true },
    ],
    git_state: "available",
    git_coverage: "complete",
    git_reasons: [],
    git_change_count: 2,
    git_changes: [
      { path: "src/example.ts", kind: "modified", staged: false, unstaged: true },
      { path: "src/new.ts", kind: "untracked", staged: false, unstaged: false },
    ],
    ...overrides,
  };
}

function searchResult(overrides: Partial<AgentWorkspaceSearchResult> = {}): AgentWorkspaceSearchResult {
  return {
    contract_version: "local-agent-workspace-search.v1",
    session_id: SESSION,
    scope: "application_readable_utf8_text",
    coverage: "complete",
    reasons: [],
    reason_code: null,
    scanned_entry_count: 8,
    inspected_byte_count: 3_600,
    skipped_entry_count: 1,
    match_count: 1,
    matches: [{ path: "src/example.ts", line_number: 7, preview: "const syntheticMatch = true;" }],
    ...overrides,
  };
}

describe("AgentWorkspaceDiscoveryPanel", () => {
  it("shows a content-free inventory and Git status, filters paths, and opens an editable file", async () => {
    const openFile = vi.fn();
    const transport = { getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery()) };
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      onOpenFile={openFile}
      refreshKey={1}
      sessionId={SESSION}
      transport={transport}
    />);

    expect(await screen.findByText("Complete application-readable inventory")).toBeVisible();
    expect(screen.getByText("3 files observed · 3 entries inspected")).toBeVisible();
    expect(screen.getByText("2 changes reported by bounded porcelain status.")).toBeVisible();
    expect(screen.getByText("Unstaged")).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter mapped files" }), { target: { value: "util" } });
    const files = screen.getByRole("list", { name: "Mapped workspace files" });
    expect(within(files).getByText("src/util.ts")).toBeVisible();
    expect(within(files).queryByText("README.md")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open src/util.ts" }));
    expect(openFile).toHaveBeenCalledExactlyOnceWith("src/util.ts");
    expect(screen.getByText(/exposes no branch, commit, remote, absolute path or file content/u)).toBeVisible();
  });

  it("states partial inventory and fail-closed Git reasons without inventing completeness", async () => {
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={{ getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery({
        inventory_coverage: "partial",
        inventory_reasons: ["display_limit", "excluded_directories"],
        scanned_entry_count: 10,
        observed_file_count: 8,
        files: [{ path: "example.txt", byte_size: 7, editable_candidate: true }],
        git_state: "unavailable",
        git_coverage: "unavailable",
        git_reasons: ["repository_layout_unsupported"],
        git_change_count: null,
        git_changes: [],
      })) }}
    />);

    expect(await screen.findByText("Partial application-readable inventory")).toBeVisible();
    expect(screen.getByText("More files exist than this card can display.")).toBeVisible();
    expect(screen.getByText("Protected or generated directories were excluded.")).toBeVisible();
    expect(screen.getByText(/repository layout can redirect outside the selected folder/u)).toBeVisible();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  it("searches bounded file contents with exact options and opens an editable result", async () => {
    const openFile = vi.fn();
    const search = vi.fn().mockResolvedValue(searchResult());
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      onOpenFile={openFile}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery()),
        getAgentWorkspaceSearch: search,
      }}
    />);

    await screen.findByText("Complete application-readable inventory");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search workspace contents" }), {
      target: { value: "syntheticMatch" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Workspace search file pattern" }), {
      target: { value: "src/**/*.ts" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Regular expression" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("1 match")).toBeVisible();
    expect(screen.getByText("8 entries scanned · 3.6 KB inspected · 1 skipped entry")).toBeVisible();
    expect(screen.getByText("src/example.ts:7")).toBeVisible();
    expect(screen.getByText("const syntheticMatch = true;")).toBeVisible();
    expect(search).toHaveBeenCalledExactlyOnceWith(SESSION, {
      query: "syntheticMatch",
      glob: "src/**/*.ts",
      regex: true,
    }, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Open search result src/example.ts line 7" }));
    expect(openFile).toHaveBeenCalledExactlyOnceWith("src/example.ts");
  });

  it("labels partial coverage and drops stale results after a closed search error", async () => {
    const search = vi.fn()
      .mockResolvedValueOnce(searchResult({
        coverage: "partial",
        reasons: ["match limit reached"],
        reason_code: "workspace_inspection_incomplete",
      }))
      .mockRejectedValueOnce(new TransportError("EXAMPLE_PRIVATE_REGEX", 422, "workspace_regex_invalid"));
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery()),
        getAgentWorkspaceSearch: search,
      }}
    />);
    await screen.findByText("Complete application-readable inventory");
    const input = screen.getByRole("searchbox", { name: "Search workspace contents" });
    fireEvent.change(input, { target: { value: "synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Partial search coverage")).toBeVisible();
    expect(screen.getByText("match limit reached")).toBeVisible();

    fireEvent.change(input, { target: { value: "[" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Regular expression" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("regular expression is invalid");
    expect(screen.queryByText("src/example.ts:7")).not.toBeInTheDocument();
    expect(screen.queryByText("EXAMPLE_PRIVATE_REGEX")).not.toBeInTheDocument();
  });

  it("drops stale data on refresh failure and recovers only after an explicit retry", async () => {
    const api = {
      getAgentWorkspaceDiscovery: vi.fn()
        .mockResolvedValueOnce(discovery())
        .mockRejectedValueOnce(new Error("EXAMPLE_PRIVATE_FAILURE"))
        .mockResolvedValueOnce(discovery({
          scanned_entry_count: 1,
          observed_file_count: 1,
          files: [{ path: "recovered.txt", byte_size: 9, editable_candidate: true }],
          git_state: "not_repository",
          git_coverage: "not_applicable",
          git_reasons: [],
          git_change_count: 0,
          git_changes: [],
        })),
    };
    const view = render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={api}
    />);
    expect(await screen.findByText("README.md")).toBeVisible();

    view.rerender(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={2}
      sessionId={SESSION}
      transport={api}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No previous result is presented as current");
    expect(screen.queryByText("README.md")).not.toBeInTheDocument();
    expect(screen.queryByText("EXAMPLE_PRIVATE_FAILURE")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("recovered.txt")).toBeVisible();
    expect(api.getAgentWorkspaceDiscovery).toHaveBeenCalledTimes(3);
  });

  it("aborts and ignores an old session response", async () => {
    let resolveOld!: (value: AgentWorkspaceDiscovery) => void;
    const old = new Promise<AgentWorkspaceDiscovery>((resolve) => { resolveOld = resolve; });
    const nextSession = "b".repeat(32);
    const api = {
      getAgentWorkspaceDiscovery: vi.fn()
        .mockReturnValueOnce(old)
        .mockResolvedValueOnce(discovery({
          session_id: nextSession,
          scanned_entry_count: 1,
          observed_file_count: 1,
          files: [{ path: "next.txt", byte_size: 4, editable_candidate: true }],
          git_state: "not_repository",
          git_coverage: "not_applicable",
          git_reasons: [],
          git_change_count: 0,
          git_changes: [],
        })),
    };
    const view = render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={SESSION}
      transport={api}
    />);
    await waitFor(() => expect(api.getAgentWorkspaceDiscovery).toHaveBeenCalledTimes(1));
    const oldSignal = api.getAgentWorkspaceDiscovery.mock.calls[0][1] as AbortSignal;
    view.rerender(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey={1}
      sessionId={nextSession}
      transport={api}
    />);
    expect(await screen.findByText("next.txt")).toBeVisible();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => resolveOld(discovery()));
    expect(screen.queryByText("README.md")).not.toBeInTheDocument();
  });

  it("never opens deleted or non-editable paths", async () => {
    const openFile = vi.fn();
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      onOpenFile={openFile}
      refreshKey={1}
      sessionId={SESSION}
      transport={{ getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery({
        scanned_entry_count: 1,
        observed_file_count: 1,
        files: [{ path: "large.bin", byte_size: 400_000, editable_candidate: false }],
        git_change_count: 1,
        git_changes: [{ path: "src/deleted.ts", kind: "deleted", staged: false, unstaged: true }],
      })) }}
    />);

    await screen.findByText("large.bin");
    expect(screen.getByRole("button", { name: "Open large.bin" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open Git change src/deleted.ts" })).toBeDisabled();
    expect(openFile).not.toHaveBeenCalled();
  });

  it("locks the parent workspace when discovery proves the root changed", async () => {
    const rootChanged = vi.fn();
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      onRootChanged={rootChanged}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentWorkspaceDiscovery: vi.fn().mockRejectedValue(
          new TransportError("EXAMPLE_PRIVATE_ROOT", 409, "workspace_root_changed"),
        ),
      }}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be refreshed");
    expect(rootChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("EXAMPLE_PRIVATE_ROOT")).not.toBeInTheDocument();
  });

  it("locks the parent workspace when content search proves the root changed", async () => {
    const rootChanged = vi.fn();
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      onRootChanged={rootChanged}
      refreshKey={1}
      sessionId={SESSION}
      transport={{
        getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery()),
        getAgentWorkspaceSearch: vi.fn().mockRejectedValue(
          new TransportError("EXAMPLE_PRIVATE_ROOT", 409, "workspace_root_changed"),
        ),
      }}
    />);
    await screen.findByText("Complete application-readable inventory");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search workspace contents" }), {
      target: { value: "synthetic" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not complete");
    expect(rootChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("EXAMPLE_PRIVATE_ROOT")).not.toBeInTheDocument();
  });

  it("keeps maximum discovery and Git payloads on bounded, independently navigable pages", async () => {
    const files = Array.from({ length: 400 }, (_, index) => ({
      path: `src/file-${index.toString().padStart(3, "0")}.ts`,
      byte_size: index + 1,
      editable_candidate: true,
    }));
    const changes = files.map((file) => ({
      path: file.path,
      kind: "modified" as const,
      staged: false,
      unstaged: true,
    }));
    render(<AgentWorkspaceDiscoveryPanel
      fileActionsDisabled={false}
      refreshKey="synthetic-large"
      sessionId={SESSION}
      transport={{ getAgentWorkspaceDiscovery: vi.fn().mockResolvedValue(discovery({
        scanned_entry_count: 400,
        observed_file_count: 400,
        files,
        git_change_count: 400,
        git_changes: changes,
      })) }}
    />);

    await screen.findByText("400 files observed · 400 entries inspected");
    expect(within(screen.getByRole("list", { name: "Mapped workspace files" })).getAllByRole("listitem")).toHaveLength(50);
    expect(within(screen.getByRole("list", { name: "Git changes" })).getAllByRole("listitem")).toHaveLength(50);
    expect(screen.getAllByText("Showing 1–50 of 400")).toHaveLength(2);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Mapped workspace file pages" })).getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing 51–100 of 400")).toBeVisible();
    expect(within(screen.getByRole("list", { name: "Mapped workspace files" })).getByText("src/file-050.ts")).toBeVisible();
    expect(within(screen.getByRole("list", { name: "Git changes" })).getByText("src/file-000.ts")).toBeVisible();
  });
});
