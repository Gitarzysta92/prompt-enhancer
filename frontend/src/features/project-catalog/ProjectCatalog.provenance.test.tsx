import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CodexSession, PromptEnhancerTransport } from "../../shared/api/contracts";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { ProjectCatalog } from "./ProjectCatalog";

const projectA = "a".repeat(64);
const projectB = "b".repeat(64);

function session(input: {
  sessionId: string;
  projectId: string;
  projectName: string;
  provider: CodexSession["provider"];
  startedAt: string;
}): CodexSession {
  return {
    session_id: input.sessionId,
    installation_id: "1".repeat(64),
    project_id: input.projectId,
    project_display_name: input.projectName,
    session_display_name: null,
    provider: input.provider,
    project_display_name_origin: "provider",
    session_display_name_origin: "unknown",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "example-provider-1",
    adapter_version: "example-adapter-1",
    source_schema_version: "example-schema-1",
    started_at: input.startedAt,
    ended_at: null,
    terminal_state: null,
    events_complete: false,
  };
}

function transportWith(sessions: CodexSession[]): PromptEnhancerTransport {
  const synthetic = createSyntheticTransport();
  return {
    ...synthetic,
    listCodexSessions: vi.fn(async () => ({ sessions, limit: 100, offset: 0 })),
  };
}

describe("ProjectCatalog provenance", () => {
  it("keeps hook-captured Claude Code sessions instead of filtering them out", async () => {
    const transport = transportWith([
      session({ sessionId: "c".repeat(64), projectId: projectA, projectName: "Example Observatory", provider: "codex", startedAt: "2040-01-01T09:00:00Z" }),
      session({ sessionId: "d".repeat(64), projectId: projectA, projectName: "Example Observatory", provider: "claude_code", startedAt: "2040-01-02T09:00:00Z" }),
      session({ sessionId: "e".repeat(64), projectId: projectB, projectName: "Sample Workshop", provider: "claude_code", startedAt: "2040-01-03T09:00:00Z" }),
    ]);
    render(<ProjectCatalog coverageProvider="synthetic" navigate={vi.fn()} transport={transport} />);

    const openObservatory = await screen.findByRole("button", { name: "Open project Example Observatory" });
    const observatory = openObservatory.closest("article") as HTMLElement;
    // Both sessions counted; both sources named on the card.
    expect(within(observatory).getByText("2", { selector: "dd" })).toBeInTheDocument();
    const observatorySources = within(observatory).getByLabelText("Session sources");
    expect(within(observatorySources).getByLabelText("Source: Codex")).toBeInTheDocument();
    expect(within(observatorySources).getByLabelText("Source: Claude Code")).toBeInTheDocument();

    const workshop = screen.getByRole("button", { name: "Open project Sample Workshop" }).closest("article") as HTMLElement;
    const workshopSources = within(workshop).getByLabelText("Session sources");
    expect(within(workshopSources).getByLabelText("Source: Claude Code")).toBeInTheDocument();
    expect(within(workshopSources).queryByLabelText("Source: Codex")).toBeNull();
  });

  it("still fails closed on the whole response when any provider code is outside the local vocabulary", async () => {
    const stranger = session({ sessionId: "f".repeat(64), projectId: projectB, projectName: "Sample Workshop", provider: "codex", startedAt: "2040-01-03T09:00:00Z" });
    const transport = transportWith([
      { ...stranger, provider: "remote_mystery" as CodexSession["provider"] },
      session({ sessionId: "c".repeat(64), projectId: projectA, projectName: "Example Observatory", provider: "codex", startedAt: "2040-01-01T09:00:00Z" }),
    ]);
    render(<ProjectCatalog coverageProvider="synthetic" navigate={vi.fn()} transport={transport} />);
    // The catalog validates every row and withholds the entire response rather
    // than rendering a partial, unexplained subset.
    await waitFor(() => expect(screen.getByText("The locally indexed project catalog response was invalid.")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Open project Example Observatory" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open project Sample Workshop" })).toBeNull();
    expect(document.body.textContent).not.toContain("remote_mystery");
  });
});
