import { render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { AgentCatalogSession, AgentProject, AgentSessionView } from "../../shared/api/contracts";
import { AgentCatalogRail } from "./AgentCatalogRail";

const PROJECT_ID = "1".repeat(32);
const SESSION_ID = "2".repeat(32);
const FAILURE_COPY = "Close was not confirmed. Its draft was kept. Try closing this chat again.";

describe("Agent catalog rail close failures", () => {
  it("renders a row-local close failure in the fallback live-session rail", () => {
    const live = liveSession();
    render(<AgentCatalogRail {...commonProps()} closeFailureSessionIds={new Set([live.session_id])} liveSessions={[live]} transport={{}} />);

    const close = screen.getByRole("button", { name: "Close session Synthetic fallback chat" });
    const row = close.closest("li");
    expect(row).not.toBeNull();
    expect(within(row!).getByRole("alert")).toHaveTextContent(FAILURE_COPY);
  });

  it("renders a row-local close failure beside the durable catalog chat", async () => {
    const live = liveSession();
    render(
      <AgentCatalogRail
        {...commonProps()}
        closeFailureSessionIds={new Set([live.session_id])}
        liveSessions={[live]}
        transport={catalogTransport()}
      />,
    );

    const actions = await screen.findByRole("button", { name: "Chat actions for Synthetic fallback chat" });
    const row = actions.closest("li");
    expect(row).not.toBeNull();
    expect(within(row!).getByRole("alert")).toHaveTextContent(FAILURE_COPY);
  });

  it("does not show a close failure for an inactive durable catalog row", async () => {
    const inactiveId = "3".repeat(32);
    render(
      <AgentCatalogRail
        {...commonProps()}
        closeFailureSessionIds={new Set([inactiveId])}
        liveSessions={[]}
        transport={catalogTransport(inactiveId, "Inactive synthetic chat")}
      />,
    );

    const actions = await screen.findByRole("button", { name: "Chat actions for Inactive synthetic chat" });
    const row = actions.closest("li");
    expect(row).not.toBeNull();
    expect(within(row!).queryByRole("alert")).toBeNull();
  });
});

function commonProps(): Omit<ComponentProps<typeof AgentCatalogRail>, "closeFailureSessionIds" | "liveSessions" | "transport"> {
  return {
    currentSessionId: SESSION_ID,
    onNewChat: vi.fn(),
    onOpenLiveSession: vi.fn(),
    onOpenUnavailableSession: vi.fn(),
    onProjectChange: vi.fn(),
    onCloseLiveSession: vi.fn(),
    selectedProjectId: PROJECT_ID,
  };
}

function liveSession(): AgentSessionView {
  return {
    contract_version: "local-agent.v9",
    cleanup_unconfirmed: false,
    closing: false,
    stopping: false,
    session_id: SESSION_ID,
    running: false,
    pending_approval_id: null,
    last_seq: 0,
    turns: 0,
    history_revision: 0,
    model_alias: null,
    created_at: "2040-01-01T00:00:00Z",
    recovered: false,
    authority_revalidated: true,
    history_write_failed: false,
    recovery_state: "current",
    settings: {
      workspace: "D:/synthetic/project",
      project_id: PROJECT_ID,
      model_alias: null,
      parameters: { temperature: 0.2, top_p: 0.9, max_tokens: 100, enable_thinking: false },
      instructions: null,
      allow_writes: false,
      allow_commands: false,
      allow_web: false,
      max_steps: 1,
      command_timeout_seconds: 1,
      title: "Synthetic fallback chat",
      retention_policy: "metadata_only",
    },
  };
}

function catalogTransport(sessionId = SESSION_ID, title = "Synthetic fallback chat") {
  const project: AgentProject = {
    contract_version: "agent-catalog.v2",
    project_id: PROJECT_ID,
    name: "Synthetic project",
    created_at: "2040-01-01T00:00:00Z",
    updated_at: "2040-01-01T00:00:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    session_count: 1,
    is_default: false,
  };
  const session: AgentCatalogSession = {
    contract_version: "agent-catalog.v2",
    session_id: sessionId,
    project_id: PROJECT_ID,
    title,
    workspace: "D:/synthetic/project",
    model_alias: null,
    created_at: "2040-01-01T00:00:00Z",
    updated_at: "2040-01-01T00:00:00Z",
    last_opened_at: "2040-01-01T00:00:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    history_state: "memory_only",
    retention_policy: "metadata_only",
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: true,
    lineage: null,
  };
  return {
    listAgentProjects: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, projects: [project] })),
    createAgentProject: vi.fn(),
    updateAgentProject: vi.fn(),
    deleteAgentProject: vi.fn(),
    listAgentCatalogSessions: vi.fn(async () => ({ contract_version: "agent-catalog.v2" as const, sessions: [session] })),
    updateAgentCatalogSession: vi.fn(),
    deleteAgentCatalogSession: vi.fn(),
  };
}
