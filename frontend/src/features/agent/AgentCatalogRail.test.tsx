import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCatalogPageQuery,
  AgentCatalogQuery,
  AgentCatalogSession,
  AgentCatalogSessionPage,
  AgentCatalogSessionPageQuery,
  AgentProject,
  AgentProjectPage,
  AgentSessionView,
  CreateAgentProject,
  UpdateAgentCatalogSession,
  UpdateAgentProject,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentCatalogRail } from "./AgentCatalogRail";

const PROJECT_ID = "1".repeat(32);
const SESSION_ID = "2".repeat(32);
const SECOND_PROJECT_ID = "3".repeat(32);
const SNAPSHOT = "a".repeat(64);

const project = (overrides: Partial<AgentProject> = {}): AgentProject => ({
  contract_version: "agent-catalog.v2",
  project_id: PROJECT_ID,
  name: "Example project",
  created_at: "2040-01-01T10:00:00Z",
  updated_at: "2040-01-01T10:01:00Z",
  revision: 2,
  pinned: false,
  archived_at: null,
  session_count: 1,
  is_default: false,
  ...overrides,
});

const catalogSession = (
  overrides: Partial<AgentCatalogSession> = {},
): AgentCatalogSession => ({
  contract_version: "agent-catalog.v2",
  session_id: SESSION_ID,
  project_id: PROJECT_ID,
  title: "Example chat",
  workspace: "D:\\example\\workspace",
  model_alias: "example-model",
  created_at: "2040-01-01T10:00:00Z",
  updated_at: "2040-01-01T10:01:00Z",
  last_opened_at: "2040-01-01T10:00:00Z",
  revision: 2,
  pinned: false,
  archived_at: null,
  history_state: "memory_only",
  retention_policy: "metadata_only",
  history_revision: 0,
  last_event_seq: 0,
  turn_count: 0,
  conversation_available: false,
  lineage: null,
  ...overrides,
});

const liveSession = (): AgentSessionView => ({
  contract_version: "local-agent.v9",
  session_id: SESSION_ID,
  settings: {
    workspace: "D:\\example\\workspace",
    project_id: PROJECT_ID,
    model_alias: "example-model",
    title: "Example chat",
    parameters: {
      temperature: 0.2,
      top_p: 0.95,
      max_tokens: 1400,
      enable_thinking: false,
    },
    instructions: null,
    allow_writes: false,
    allow_commands: false,
    allow_web: false,
    max_steps: 10,
    command_timeout_seconds: 120,
    retention_policy: "metadata_only",
  },
  created_at: "2040-01-01T10:00:00Z",
  running: false,
  closing: false,
  stopping: false,
  cleanup_unconfirmed: false,
  last_seq: 0,
  pending_approval_id: null,
  model_alias: "example-model",
  turns: 3,
  history_revision: 0,
  recovered: false,
  authority_revalidated: true,
  history_write_failed: false,
  recovery_state: "current",
});

function transport(session = catalogSession()) {
  return {
    listAgentProjects: vi.fn(async (_query?: AgentCatalogQuery, _signal?: AbortSignal) => ({
      contract_version: "agent-catalog.v2" as const,
      projects: [project()],
    })),
    createAgentProject: vi.fn(async ({ name }: CreateAgentProject) => project({ name })),
    updateAgentProject: vi.fn(async (_id: string, request: UpdateAgentProject) => project({
      name: request.name || "Example project",
      pinned: request.pinned ?? false,
      archived_at: request.archived ? "2040-01-01T10:02:00Z" : null,
      revision: 3,
    })),
    deleteAgentProject: vi.fn(async () => undefined),
    listAgentCatalogSessions: vi.fn(async () => ({
      contract_version: "agent-catalog.v2" as const,
      sessions: [session],
    })),
    updateAgentCatalogSession: vi.fn(async (_id: string, request: UpdateAgentCatalogSession) => ({
      ...session,
      project_id: request.project_id ?? session.project_id,
      title: request.title || session.title,
      pinned: request.pinned ?? session.pinned,
      archived_at: request.archived === undefined
        ? session.archived_at
        : request.archived ? "2040-01-01T10:02:00Z" : null,
      revision: 3,
    })),
    deleteAgentCatalogSession: vi.fn(async () => undefined),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function projectPage(
  projects: AgentProject[],
  total = projects.length,
  offset = 0,
): AgentProjectPage {
  const nextOffset = offset + projects.length < total ? offset + projects.length : null;
  return {
    contract_version: "agent-catalog-page.v1",
    snapshot: SNAPSHOT,
    limit: 100,
    offset,
    total,
    next_offset: nextOffset,
    complete: nextOffset === null,
    projects,
  };
}

function sessionPage(
  sessions: AgentCatalogSession[],
  total = sessions.length,
  offset = 0,
): AgentCatalogSessionPage {
  const nextOffset = offset + sessions.length < total ? offset + sessions.length : null;
  return {
    contract_version: "agent-catalog-page.v1",
    snapshot: SNAPSHOT,
    limit: 100,
    offset,
    total,
    next_offset: nextOffset,
    complete: nextOffset === null,
    sessions,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentCatalogRail", () => {
  it("loads snapshot-bound project and chat continuations without unbounding rendered rows", async () => {
    const projects = Array.from({ length: 120 }, (_, index) => project({
      project_id: (index + 1).toString(16).padStart(32, "0"),
      name: `Paged project ${index.toString().padStart(3, "0")}`,
      session_count: 130,
    }));
    const sessions = Array.from({ length: 130 }, (_, index) => catalogSession({
      session_id: (index + 1000).toString(16).padStart(32, "0"),
      title: `Paged chat ${index.toString().padStart(3, "0")}`,
    }));
    const pageAgentProjects = vi.fn(async (query: AgentCatalogPageQuery) => (
      query.offset === 0 ? projectPage(projects.slice(0, 100), 120) : projectPage(projects.slice(100), 120, 100)
    ));
    const pageAgentCatalogSessions = vi.fn(async (query: AgentCatalogSessionPageQuery) => (
      query.offset === 0 ? sessionPage(sessions.slice(0, 100), 130) : sessionPage(sessions.slice(100), 130, 100)
    ));
    const api = { ...transport(), pageAgentProjects, pageAgentCatalogSessions };
    render(<AgentCatalogRail
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={PROJECT_ID}
      transport={api}
    />);

    expect(await screen.findByText("100 of 120 projects available")).toBeVisible();
    expect(await screen.findByText("100 of 130 chats available")).toBeVisible();
    const rail = screen.getByRole("navigation", { name: "Agent projects and chats" });
    expect(rail.querySelectorAll(".agent-rail__project")).toHaveLength(40);
    expect(rail.querySelectorAll(".agent-rail__sessions > li")).toHaveLength(40);

    fireEvent.click(screen.getByRole("button", { name: "Load more projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Load more chats" }));
    expect(await screen.findByText("120 of 120 projects available")).toBeVisible();
    expect(await screen.findByText("130 of 130 chats available")).toBeVisible();
    expect(pageAgentProjects).toHaveBeenLastCalledWith({
      includeArchived: false,
      limit: 100,
      offset: 100,
      snapshot: SNAPSHOT,
    }, expect.any(AbortSignal));
    expect(pageAgentCatalogSessions).toHaveBeenLastCalledWith({
      projectId: PROJECT_ID,
      includeArchived: false,
      limit: 100,
      offset: 100,
      snapshot: SNAPSHOT,
    }, expect.any(AbortSignal));
    expect(rail.querySelectorAll(".agent-rail__project")).toHaveLength(40);
    expect(rail.querySelectorAll(".agent-rail__sessions > li")).toHaveLength(40);
  });

  it("keeps exact selected project and chat records visible outside the loaded prefix", async () => {
    const selectedProjectId = "f".repeat(32);
    const selectedSessionId = "e".repeat(32);
    const projects = Array.from({ length: 100 }, (_, index) => project({
      project_id: (index + 1).toString(16).padStart(32, "0"),
      name: `Prefix project ${index.toString().padStart(3, "0")}`,
    }));
    const sessions = Array.from({ length: 100 }, (_, index) => catalogSession({
      session_id: (index + 1000).toString(16).padStart(32, "0"),
      project_id: selectedProjectId,
      title: `Prefix chat ${index.toString().padStart(3, "0")}`,
    }));
    const selectedProject = project({
      project_id: selectedProjectId,
      name: "Selected project outside prefix",
      session_count: 150,
    });
    const selectedSession = catalogSession({
      session_id: selectedSessionId,
      project_id: selectedProjectId,
      title: "Selected chat outside prefix",
    });
    const getAgentProject = vi.fn(async () => selectedProject);
    const getAgentCatalogSession = vi.fn(async () => selectedSession);
    const api = {
      ...transport(),
      pageAgentProjects: vi.fn(async () => projectPage(projects, 150)),
      pageAgentCatalogSessions: vi.fn(async () => sessionPage(sessions, 150)),
      getAgentProject,
      getAgentCatalogSession,
    };
    render(<AgentCatalogRail
      currentSessionId={selectedSessionId}
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={selectedProjectId}
      transport={api}
    />);

    expect(await screen.findByText("Selected project outside prefix")).toBeVisible();
    expect(await screen.findByRole("button", { name: /^Selected chat outside prefix ·/u })).toBeVisible();
    expect(screen.getByText("101 of 150 projects available")).toBeVisible();
    expect(screen.getByText("101 of 150 chats available")).toBeVisible();
    expect(getAgentProject).toHaveBeenCalledWith(selectedProjectId, expect.any(AbortSignal));
    expect(getAgentCatalogSession).toHaveBeenCalledWith(selectedSessionId, expect.any(AbortSignal));
  });

  it("refuses a repeated continuation and preserves the already loaded project prefix", async () => {
    const projects = Array.from({ length: 100 }, (_, index) => project({
      project_id: (index + 1).toString(16).padStart(32, "0"),
      name: `Stable project ${index.toString().padStart(3, "0")}`,
    }));
    const pageAgentProjects = vi.fn(async (query: AgentCatalogPageQuery) => (
      query.offset === 0
        ? projectPage(projects, 101)
        : projectPage([projects[0]], 101, 100)
    ));
    const api = {
      ...transport(),
      pageAgentProjects,
      pageAgentCatalogSessions: vi.fn(async () => sessionPage([catalogSession()])),
    };
    render(<AgentCatalogRail
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={PROJECT_ID}
      transport={api}
    />);

    await screen.findByText("100 of 101 projects available");
    fireEvent.click(screen.getByRole("button", { name: "Load more projects" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A repeated project page was refused",
    );
    expect(screen.getByText("100 of 101 projects available")).toBeVisible();
    expect(screen.getByText("Stable project 000")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reload projects" })).toBeVisible();
  });

  it("keeps a loaded chat prefix when a stale snapshot continuation is refused", async () => {
    const pageAgentCatalogSessions = vi.fn()
      .mockResolvedValueOnce(sessionPage([catalogSession()], 2))
      .mockRejectedValueOnce(new TransportError(
        "Synthetic snapshot conflict",
        409,
        "agent_catalog_page_snapshot_conflict",
      ));
    const api = {
      ...transport(),
      pageAgentProjects: vi.fn(async () => projectPage([project()])),
      pageAgentCatalogSessions,
    };
    render(<AgentCatalogRail
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={PROJECT_ID}
      transport={api}
    />);

    await screen.findByText("1 of 2 chats available");
    fireEvent.click(screen.getByRole("button", { name: "Load more chats" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The chats changed while another page was loading",
    );
    expect(screen.getByRole("button", { name: /^Example chat ·/u })).toBeVisible();
    expect(screen.getByText("1 of 2 chats available")).toBeVisible();
  });

  it("ignores an initial project page that resolves after its search scope was replaced", async () => {
    const pending = deferred<AgentProjectPage>();
    const fresh = project({ name: "Fresh scoped project" });
    const pageAgentProjects = vi.fn()
      .mockImplementationOnce((_query: AgentCatalogPageQuery, _signal?: AbortSignal) => pending.promise)
      .mockResolvedValueOnce(projectPage([fresh]));
    const api = {
      ...transport(),
      pageAgentProjects,
      pageAgentCatalogSessions: vi.fn(async () => sessionPage([])),
    };
    render(<AgentCatalogRail
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={PROJECT_ID}
      transport={api}
    />);

    await waitFor(() => expect(pageAgentProjects).toHaveBeenCalledTimes(1));
    const firstSignal = pageAgentProjects.mock.calls[0][1];
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "fresh" } });
    expect(await screen.findByText("Fresh scoped project")).toBeVisible();
    expect(firstSignal?.aborted).toBe(true);
    pending.resolve(projectPage([project({ name: "Stale initial project" })]));
    await Promise.resolve();
    expect(screen.queryByText("Stale initial project")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh scoped project")).toBeVisible();
  });

  it("aborts delayed project and chat continuations and refuses their late records after search replacement", async () => {
    const projects = Array.from({ length: 100 }, (_, index) => project({
      project_id: (index + 1).toString(16).padStart(32, "0"),
      name: `Prefix project ${index.toString().padStart(3, "0")}`,
    }));
    const sessions = Array.from({ length: 100 }, (_, index) => catalogSession({
      session_id: (index + 1000).toString(16).padStart(32, "0"),
      title: `Prefix chat ${index.toString().padStart(3, "0")}`,
    }));
    const delayedProjects = deferred<AgentProjectPage>();
    const delayedSessions = deferred<AgentCatalogSessionPage>();
    const freshProject = project({ name: "Fresh search project" });
    const freshSession = catalogSession({ title: "Fresh search chat" });
    const staleProject = project({
      project_id: "d".repeat(32),
      name: "Late foreign project",
    });
    const staleSession = catalogSession({
      session_id: "e".repeat(32),
      title: "Late foreign chat",
    });
    const pageAgentProjects = vi.fn((query: AgentCatalogPageQuery, _signal?: AbortSignal) => {
      if (query.offset === 100) return delayedProjects.promise;
      return Promise.resolve(query.search === "fresh"
        ? projectPage([freshProject])
        : projectPage(projects, 101));
    });
    const pageAgentCatalogSessions = vi.fn((query: AgentCatalogSessionPageQuery, _signal?: AbortSignal) => {
      if (query.offset === 100) return delayedSessions.promise;
      return Promise.resolve(query.search === "fresh"
        ? sessionPage([freshSession])
        : sessionPage(sessions, 101));
    });
    const api = { ...transport(), pageAgentProjects, pageAgentCatalogSessions };
    render(<AgentCatalogRail
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={PROJECT_ID}
      transport={api}
    />);

    await screen.findByText("100 of 101 projects available");
    await screen.findByText("100 of 101 chats available");
    fireEvent.click(screen.getByRole("button", { name: "Load more projects" }));
    fireEvent.click(screen.getByRole("button", { name: "Load more chats" }));
    await waitFor(() => {
      expect(pageAgentProjects).toHaveBeenCalledTimes(2);
      expect(pageAgentCatalogSessions).toHaveBeenCalledTimes(2);
    });
    const delayedProjectSignal = pageAgentProjects.mock.calls[1][1];
    const delayedSessionSignal = pageAgentCatalogSessions.mock.calls[1][1];

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "fresh" } });
    expect(await screen.findByText("Fresh search project")).toBeVisible();
    expect(await screen.findByRole("button", { name: /^Fresh search chat ·/u })).toBeVisible();
    expect(delayedProjectSignal?.aborted).toBe(true);
    expect(delayedSessionSignal?.aborted).toBe(true);

    delayedProjects.resolve(projectPage([staleProject], 101, 100));
    delayedSessions.resolve(sessionPage([staleSession], 101, 100));
    await Promise.all([delayedProjects.promise, delayedSessions.promise]);
    await Promise.resolve();
    expect(screen.queryByText("Late foreign project")).not.toBeInTheDocument();
    expect(screen.queryByText("Late foreign chat")).not.toBeInTheDocument();
    expect(screen.getByText("Fresh search project")).toBeVisible();
  });

  it("bounds maximum returned project and chat collections while keeping current selections visible", async () => {
    const projects = Array.from({ length: 120 }, (_, index) => project({
      project_id: (index + 10).toString(16).padStart(32, "0"),
      name: `Synthetic project ${index.toString().padStart(3, "0")}`,
      session_count: 120,
    }));
    const selectedProject = projects[70];
    const sessions = Array.from({ length: 120 }, (_, index) => catalogSession({
      session_id: (index + 1000).toString(16).padStart(32, "0"),
      project_id: selectedProject.project_id,
      title: `Synthetic chat ${index.toString().padStart(3, "0")}`,
    }));
    const api = transport();
    api.listAgentProjects.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      projects,
    });
    api.listAgentCatalogSessions.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      sessions,
    });
    render(<AgentCatalogRail
      currentSessionId={sessions[95].session_id}
      liveSessions={[]}
      onCloseLiveSession={vi.fn()}
      onNewChat={vi.fn()}
      onOpenLiveSession={vi.fn()}
      onOpenUnavailableSession={vi.fn()}
      onProjectChange={vi.fn()}
      selectedProjectId={selectedProject.project_id}
      transport={api}
    />);

    const rail = await screen.findByRole("navigation", { name: "Agent projects and chats" });
    await screen.findByText("Synthetic project 070");
    expect(rail.querySelectorAll(".agent-rail__project")).toHaveLength(40);
    expect(rail.querySelectorAll(".agent-rail__sessions > li")).toHaveLength(40);
    expect(screen.getByText("Showing 41–80 of 120")).toBeVisible();
    expect(screen.getByText("Showing 81–120 of 120")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Synthetic chat 095 ·/u }).closest("li")).toHaveAttribute("data-current", "true");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Agent project pages" })).getByRole("button", { name: "Later" }));
    expect(screen.getByText("Synthetic project 080")).toBeVisible();
    expect(screen.queryByText("Synthetic project 040")).not.toBeInTheDocument();
  });

  it("marks only chats with an in-window draft without exposing draft content", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        draftSessionIds={new Set([SESSION_ID])}
        liveSessions={[liveSession()]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );

    await screen.findByText("Example project");
    expect(screen.getByRole("button", { name: /Example chat.*draft in this window/ })).toBeVisible();
    expect(document.body.textContent).not.toContain("synthetic private draft content");
  });

  it("collapses to bounded navigation controls without losing the selected project", async () => {
    const api = transport();
    const toggle = vi.fn();
    render(
      <AgentCatalogRail
        collapsed
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        onToggleCollapsed={toggle}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );

    expect(screen.getByRole("navigation", { name: "Agent projects and chats (collapsed)" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Expand projects and chats" }));
    expect(toggle).toHaveBeenCalledOnce();
    expect(await screen.findByLabelText("Current project: Example project")).toBeVisible();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("filters navigation without clearing the active project or its collapsed identity", async () => {
    const api = transport();
    const onProjectChange = vi.fn();
    const props = {
      currentSessionId: SESSION_ID,
      liveSessions: [liveSession()],
      onCloseLiveSession: vi.fn(),
      onNewChat: vi.fn(),
      onOpenLiveSession: vi.fn(),
      onOpenUnavailableSession: vi.fn(),
      onProjectChange,
      selectedProjectId: PROJECT_ID,
      transport: api,
    };
    const rendered = render(<AgentCatalogRail {...props} />);
    await screen.findByRole("button", { name: /^Example chat ·/ });
    onProjectChange.mockClear();
    api.listAgentProjects.mockResolvedValueOnce({
      contract_version: "agent-catalog.v2",
      projects: [],
    });
    api.listAgentCatalogSessions.mockResolvedValueOnce({
      contract_version: "agent-catalog.v2",
      sessions: [],
    });

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "no matching navigation entry" },
    });

    expect(await screen.findByText("No project matches this view. Create one, or start a chat to use Personal workspace.")).toBeVisible();
    expect(await screen.findByText("No chat matches your search.")).toBeVisible();
    expect(screen.queryByText("Select or create a project.")).toBeNull();
    expect(onProjectChange).not.toHaveBeenCalled();

    rendered.rerender(<AgentCatalogRail {...props} collapsed />);
    expect(await screen.findByLabelText("Current project: Example project")).toBeVisible();
  });

  it("loads the durable hierarchy and distinguishes a live chat from unavailable history", async () => {
    const api = transport();
    const openLive = vi.fn();
    const openUnavailable = vi.fn();
    const rendered = render(
      <AgentCatalogRail
        currentSessionId={undefined}
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={openLive}
        onOpenUnavailableSession={openUnavailable}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );

    await screen.findByText("Example project");
    const chat = await screen.findByRole("button", { name: /^Example chat ·/ });
    expect(screen.getByText("Metadata only · history unavailable · example-model")).toBeTruthy();
    fireEvent.click(chat);
    expect(openUnavailable).toHaveBeenCalledWith(expect.objectContaining({ session_id: SESSION_ID }));
    expect(openLive).not.toHaveBeenCalled();

    rendered.rerender(
      <AgentCatalogRail
        currentSessionId={SESSION_ID}
        liveSessions={[liveSession()]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={openLive}
        onOpenUnavailableSession={openUnavailable}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("3 turns · live · metadata only · example-model");
    fireEvent.click(screen.getByRole("button", { name: /^Example chat ·/ }));
    expect(openLive).toHaveBeenCalledWith(expect.objectContaining({ session_id: SESSION_ID }));
  });

  it("creates and renames through bounded dialogs instead of browser prompts", async () => {
    const api = transport();
    const onProjectChange = vi.fn();
    const onSessionUpdated = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        onSessionUpdated={onSessionUpdated}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");

    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    const createDialog = screen.getByRole("dialog", { name: "Create project" });
    fireEvent.change(within(createDialog).getByLabelText("Project name"), {
      target: { value: "Second project" },
    });
    fireEvent.click(within(createDialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.createAgentProject).toHaveBeenCalledWith(
      { name: "Second project" },
      expect.any(AbortSignal),
    ));
    expect(onProjectChange).toHaveBeenCalledWith(PROJECT_ID);

    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    const chatActions = screen.getByRole("dialog", { name: "Chat actions for Example chat" });
    fireEvent.click(within(chatActions).getByRole("button", { name: "Rename" }));
    const renameDialog = screen.getByRole("dialog", { name: "Rename chat" });
    fireEvent.change(within(renameDialog).getByLabelText("Chat name"), {
      target: { value: "Renamed chat" },
    });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateAgentCatalogSession).toHaveBeenCalledWith(
      SESSION_ID,
      { expected_revision: 2, title: "Renamed chat" },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(onSessionUpdated).toHaveBeenCalledWith(expect.objectContaining({
      session_id: SESSION_ID,
      title: "Renamed chat",
      revision: 3,
    })));
  });

  it.each([
    ["Pin", catalogSession(), { expected_revision: 2, pinned: true }, { pinned: true }],
    ["Archive", catalogSession(), { expected_revision: 2, archived: true }, { archived_at: "2040-01-01T10:02:00Z" }],
    ["Restore", catalogSession({ archived_at: "2040-01-01T10:00:30Z" }), { expected_revision: 2, archived: false }, { archived_at: null }],
  ] as const)("publishes the canonical session after %s succeeds", async (
    action,
    session,
    command,
    expectedRecord,
  ) => {
    const api = transport(session);
    const onSessionUpdated = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        onSessionUpdated={onSessionUpdated}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: action }));

    await waitFor(() => expect(api.updateAgentCatalogSession).toHaveBeenCalledWith(
      SESSION_ID,
      command,
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(onSessionUpdated).toHaveBeenCalledWith(expect.objectContaining({
      session_id: SESSION_ID,
      revision: 3,
      ...expectedRecord,
    })));
  });

  it("keeps live-chat closure distinct from permanent metadata deletion", async () => {
    const api = transport(catalogSession({ conversation_available: true }));
    const closeLive = vi.fn();
    render(
      <AgentCatalogRail
        currentSessionId={SESSION_ID}
        liveSessions={[liveSession()]}
        onCloseLiveSession={closeLive}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("3 turns · live · metadata only · example-model");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    const actions = within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }));
    expect(actions.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(actions.getByRole("button", { name: "Close live chat" }));
    expect(closeLive).toHaveBeenCalledWith(expect.objectContaining({ session_id: SESSION_ID }));
    expect(api.deleteAgentCatalogSession).not.toHaveBeenCalled();
  });

  it("purges an owning-window draft only after permanent chat deletion succeeds", async () => {
    const api = transport();
    api.deleteAgentCatalogSession
      .mockRejectedValueOnce(new TransportError(
        "Synthetic migration refusal",
        503,
        "agent_catalog_migration_checksum_mismatch",
      ))
      .mockResolvedValueOnce(undefined);
    const onSessionDeleted = vi.fn();
    render(
      <AgentCatalogRail
        draftSessionIds={new Set([SESSION_ID])}
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        onSessionDeleted={onSessionDeleted}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");

    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" })).getByRole("button", { name: "Delete" }));
    const deleteDialog = screen.getByRole("dialog", { name: "Delete chat" });
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(api.deleteAgentCatalogSession).toHaveBeenCalledTimes(1));
    expect(api.deleteAgentCatalogSession).toHaveBeenNthCalledWith(
      1,
      SESSION_ID,
      { expected_catalog_revision: 2, expected_history_revision: 0 },
      expect.any(AbortSignal),
    );
    await screen.findByText(
      "The private Agent catalog migration history is inconsistent. No data was changed.",
    );
    expect(onSessionDeleted).not.toHaveBeenCalled();

    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteAgentCatalogSession).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(onSessionDeleted).toHaveBeenCalledOnce());
    expect(onSessionDeleted).toHaveBeenCalledWith(SESSION_ID);
  });

  it("moves a chat to another active project through the catalog revision contract", async () => {
    const api = transport();
    api.listAgentProjects.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      projects: [
        project(),
        project({
          project_id: SECOND_PROJECT_ID,
          name: "Second project",
          session_count: 0,
        }),
      ],
    });
    const onSessionUpdated = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        onSessionUpdated={onSessionUpdated}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Second project");

    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    const actions = screen.getByRole("dialog", { name: "Chat actions for Example chat" });
    fireEvent.click(within(actions).getByRole("button", { name: "Move to project" }));
    const dialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(dialog).findByLabelText("Destination project")).toHaveValue(SECOND_PROJECT_ID);
    expect(api.listAgentProjects).toHaveBeenLastCalledWith(
      { includeArchived: false, limit: 200 },
      expect.any(AbortSignal),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.updateAgentCatalogSession).toHaveBeenCalledWith(
      SESSION_ID,
      { expected_revision: 2, project_id: SECOND_PROJECT_ID },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(onSessionUpdated).toHaveBeenCalledWith(expect.objectContaining({
      session_id: SESSION_ID,
      project_id: SECOND_PROJECT_ID,
      revision: 3,
    })));
  });

  it("does not publish a moved-session callback when the revision-bound update fails", async () => {
    const api = transport();
    api.listAgentProjects.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      projects: [
        project(),
        project({
          project_id: SECOND_PROJECT_ID,
          name: "Second project",
          session_count: 0,
        }),
      ],
    });
    api.updateAgentCatalogSession.mockRejectedValueOnce(new Error("synthetic move failure"));
    const onSessionUpdated = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        onSessionUpdated={onSessionUpdated}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Second project");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Move to project" }));
    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByLabelText("Destination project")).toHaveValue(
      SECOND_PROJECT_ID,
    );
    fireEvent.click(within(moveDialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.updateAgentCatalogSession).toHaveBeenCalledOnce());
    await screen.findByText("The Agent catalog could not be updated.");
    expect(onSessionUpdated).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Move chat" })).toBeVisible();
  });

  it("loads complete move destinations independently from a filtered global search", async () => {
    const secondProject = project({
      project_id: SECOND_PROJECT_ID,
      name: "Second project",
      session_count: 0,
    });
    const api = transport();
    api.listAgentProjects.mockImplementation(async (query?: AgentCatalogQuery) => ({
      contract_version: "agent-catalog.v2" as const,
      projects: query?.search ? [project()] : [project(), secondProject],
    }));
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Second project");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Example chat" } });
    await waitFor(() => expect(api.listAgentProjects).toHaveBeenLastCalledWith(
      { search: "Example chat", includeArchived: false, limit: 200 },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(screen.queryByText("Second project")).not.toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Move to project" }));
    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByRole("option", { name: "Second project" })).toHaveValue(
      SECOND_PROJECT_ID,
    );
    expect(api.listAgentProjects).toHaveBeenLastCalledWith(
      { includeArchived: false, limit: 200 },
      expect.any(AbortSignal),
    );
  });

  it("keeps the move action blocked during a failed destination read and retries safely", async () => {
    const secondProject = project({
      project_id: SECOND_PROJECT_ID,
      name: "Recovered project",
      session_count: 0,
    });
    const api = transport();
    api.listAgentProjects
      .mockResolvedValueOnce({
        contract_version: "agent-catalog.v2",
        projects: [project()],
      })
      .mockRejectedValueOnce(new Error("synthetic read failure"))
      .mockResolvedValueOnce({
        contract_version: "agent-catalog.v2",
        projects: [project(), secondProject],
      });
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Move to project" }));

    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByRole("alert")).toHaveTextContent(
      "Active projects could not be loaded",
    );
    expect(within(moveDialog).getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(within(moveDialog).getByRole("button", { name: "Retry projects" }));

    expect(await within(moveDialog).findByRole("option", { name: "Recovered project" })).toHaveValue(
      SECOND_PROJECT_ID,
    );
    expect(within(moveDialog).getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("explains when a chat has no other active project instead of hiding the move action", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Move to project" }));

    const moveDialog = screen.getByRole("dialog", { name: "Move chat" });
    expect(await within(moveDialog).findByRole("status")).toHaveTextContent(
      "There is no other active project",
    );
    expect(within(moveDialog).getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("creates a retained-history branch through an explicit bounded dialog", async () => {
    const retained = catalogSession({
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 4,
      last_event_seq: 4,
      turn_count: 1,
      conversation_available: true,
    });
    const api = transport(retained);
    const onFork = vi.fn(async () => undefined);
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onForkSession={onFork}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("1 turn · saved locally · example-model");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    const actions = screen.getByRole("dialog", { name: "Chat actions for Example chat" });
    fireEvent.click(within(actions).getByRole("button", {
      name: "Fork latest completed turn",
    }));
    const dialog = screen.getByRole("dialog", { name: "Fork chat" });
    expect(within(dialog).getByLabelText("Chat name")).toHaveValue(
      "Example chat (branch)",
    );
    expect(within(dialog).getByText(/receives no approvals/)).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Create branch" }));
    await waitFor(() => expect(onFork).toHaveBeenCalledWith(
      retained,
      "Example chat (branch)",
      expect.any(AbortSignal),
    ));
  });

  it("coalesces synchronous duplicate catalog submissions into one owned request", async () => {
    const api = transport();
    const pending = deferred<AgentProject>();
    api.createAgentProject.mockImplementationOnce(() => pending.promise);
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    fireEvent.change(within(dialog).getByLabelText("Project name"), {
      target: { value: "One request" },
    });
    const form = dialog.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    fireEvent.submit(form!);
    expect(api.createAgentProject).toHaveBeenCalledTimes(1);
    pending.resolve(project({ name: "One request" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create project" })).toBeNull());
  });

  it("aborts a mutation owned by a replaced transport and ignores its late result", async () => {
    const first = transport();
    const second = transport();
    const pending = deferred<AgentProject>();
    first.createAgentProject.mockImplementationOnce(() => pending.promise);
    const onProjectChange = vi.fn();
    const rendered = render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        selectedProjectId={PROJECT_ID}
        transport={first}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    fireEvent.change(within(dialog).getByLabelText("Project name"), {
      target: { value: "Old transport" },
    });
    fireEvent.submit(dialog.querySelector("form")!);
    const signal = (
      first.createAgentProject.mock.calls[0] as unknown as [CreateAgentProject, AbortSignal]
    )[1];
    expect(signal).toBeInstanceOf(AbortSignal);

    rendered.rerender(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        selectedProjectId={PROJECT_ID}
        transport={second}
      />,
    );
    await waitFor(() => expect(signal?.aborted).toBe(true));
    pending.resolve(project({ name: "Late result" }));
    await Promise.resolve();
    expect(onProjectChange).not.toHaveBeenCalled();
  });

  it("fails catalog mutations closed while disconnected or cleanup-blocked", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        disabled
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
    expect(screen.getByLabelText("Project actions for Example project")).toBeDisabled();
    expect(screen.getByLabelText("Chat actions for Example chat")).toBeDisabled();
    expect(api.createAgentProject).not.toHaveBeenCalled();
    expect(api.updateAgentCatalogSession).not.toHaveBeenCalled();
  });

  it("dismisses a bounded catalog dialog with Escape and restores its trigger", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Create project" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    expect(dialog).toBeVisible();
    expect(document.body.style.overflow).toBe("hidden");
    const input = within(dialog).getByLabelText("Project name");
    await waitFor(() => expect(input).toHaveFocus());
    fireEvent.change(input, { target: { value: "Example focus trap" } });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const save = within(dialog).getByRole("button", { name: "Save" });
    expect(save).toBeEnabled();
    expect([...dialog.querySelectorAll("input:not(:disabled), button:not(:disabled)")]).toEqual([input, cancel, save]);
    input.focus();
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(save).toHaveFocus();
    fireEvent.keyDown(save, { key: "Tab" });
    expect(input).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create project" })).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps every action outside clipped rail scrollers and restores trigger focus on Escape", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");

    const trigger = screen.getByLabelText("Project actions for Example project");
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Project actions for Example project" });
    expect(dialog).toBeVisible();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(document.body.style.overflow).toBe("hidden");
    const close = within(dialog).getByRole("button", { name: "Close actions" });
    const archive = within(dialog).getByRole("button", { name: "Archive" });
    archive.focus();
    fireEvent.keyDown(archive, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(archive).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Project actions for Example project" })).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  });

  it("reports the newest chat from the initial selected-project load once", async () => {
    const saved = catalogSession({
      history_state: "durable_local",
      retention_policy: "local_history",
      conversation_available: true,
    });
    const api = transport(saved);
    const onInitialCatalogLoad = vi.fn();
    const rendered = render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onInitialCatalogLoad={onInitialCatalogLoad}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );

    await waitFor(() => expect(onInitialCatalogLoad).toHaveBeenCalledTimes(1));
    expect(onInitialCatalogLoad).toHaveBeenCalledWith(saved);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "later" } });
    await waitFor(() => expect(api.listAgentCatalogSessions).toHaveBeenCalledTimes(2));
    expect(onInitialCatalogLoad).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    await waitFor(() => expect(api.listAgentCatalogSessions).toHaveBeenCalledTimes(3));
    const replacementSaved = catalogSession({
      history_state: "durable_local",
      retention_policy: "local_history",
      conversation_available: true,
      title: "Replacement chat",
    });
    const replacement = transport(replacementSaved);
    rendered.rerender(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onInitialCatalogLoad={onInitialCatalogLoad}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={replacement}
      />,
    );
    await waitFor(() => expect(onInitialCatalogLoad).toHaveBeenCalledTimes(2));
    expect(onInitialCatalogLoad).toHaveBeenLastCalledWith(replacementSaved);
  });

  it("passes search and archived filters only to bounded catalog reads", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "example" } });
    fireEvent.click(screen.getByLabelText("Show archived"));
    await waitFor(() => expect(api.listAgentProjects).toHaveBeenLastCalledWith(
      { search: "example", includeArchived: true, limit: 200 },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(api.listAgentCatalogSessions).toHaveBeenLastCalledWith(
      { projectId: undefined, search: "example", includeArchived: true, limit: 200 },
      expect.any(AbortSignal),
    ));
  });

  it("searches chats across projects and selects the owning project before opening", async () => {
    const otherProject = project({
      project_id: SECOND_PROJECT_ID,
      name: "Second project",
    });
    const otherSession = catalogSession({
      session_id: "4".repeat(32),
      project_id: SECOND_PROJECT_ID,
      title: "Cross-project result",
    });
    const api = transport();
    const onProjectChange = vi.fn();
    const onOpenUnavailableSession = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={onOpenUnavailableSession}
        onProjectChange={onProjectChange}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    api.listAgentProjects.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      projects: [otherProject],
    });
    api.listAgentCatalogSessions.mockResolvedValue({
      contract_version: "agent-catalog.v2",
      sessions: [otherSession],
    });

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "cross-project" },
    });

    expect(await screen.findByRole("heading", { name: "Matching chats" })).toBeVisible();
    const result = await screen.findByRole("button", {
      name: /Cross-project result · Second project ·/,
    });
    expect(result).toHaveTextContent("Second project · Metadata only");
    expect(api.listAgentCatalogSessions).toHaveBeenLastCalledWith(
      {
        projectId: undefined,
        search: "cross-project",
        includeArchived: false,
        limit: 200,
      },
      expect.any(AbortSignal),
    );

    fireEvent.click(result);
    expect(onProjectChange).toHaveBeenCalledWith(SECOND_PROJECT_ID);
    expect(onOpenUnavailableSession).toHaveBeenCalledWith(otherSession);
  });

  it("restores the active chat row after a non-matching search is cleared", async () => {
    const api = transport();
    const onProjectChange = vi.fn();
    render(
      <AgentCatalogRail
        currentSessionId={SESSION_ID}
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    expect((await screen.findByRole("button", { name: /^Example chat ·/u })).closest("li"))
      .toHaveAttribute("data-current", "true");
    onProjectChange.mockClear();
    api.listAgentCatalogSessions.mockResolvedValueOnce({
      contract_version: "agent-catalog.v2",
      sessions: [],
    });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "unmatched chat" } });
    expect(await screen.findByText("No chat matches your search.")).toBeVisible();

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    const restored = await screen.findByRole("button", { name: /^Example chat ·/u });
    expect(restored.closest("li")).toHaveAttribute("data-current", "true");
    expect(onProjectChange).not.toHaveBeenCalled();
  });

  it("keeps the selected project when its exact record read fails transiently", async () => {
    const api = {
      ...transport(),
      getAgentProject: vi.fn(async (
        _projectId: string,
        _signal?: AbortSignal,
      ): Promise<AgentProject> => {
        throw new TransportError(
          "Synthetic catalog storage failure",
          503,
          "agent_catalog_storage_unavailable",
        );
      }),
    };
    const onProjectChange = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        selectedProjectId={SECOND_PROJECT_ID}
        transport={api}
      />,
    );

    expect(await screen.findByText(
      "The selected project could not be reloaded. It stays selected; retry this read.",
    )).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry project" })).toBeVisible();
    expect(api.getAgentProject).toHaveBeenCalledWith(
      SECOND_PROJECT_ID,
      expect.any(AbortSignal),
    );
    expect(onProjectChange).not.toHaveBeenCalled();
  });

  it("retargets the rail only when the selected project is authoritatively absent", async () => {
    const api = {
      ...transport(),
      getAgentProject: vi.fn(async (
        _projectId: string,
        _signal?: AbortSignal,
      ): Promise<AgentProject> => {
        throw new TransportError(
          "Synthetic missing project",
          404,
          "agent_project_not_found",
        );
      }),
    };
    const onProjectChange = vi.fn();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={onProjectChange}
        selectedProjectId={SECOND_PROJECT_ID}
        transport={api}
      />,
    );

    await waitFor(() => expect(onProjectChange).toHaveBeenCalledWith(PROJECT_ID));
    expect(screen.queryByText(/could not be reloaded/u)).toBeNull();
  });

  it("focuses the delete dialog itself instead of a destructive default action", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    fireEvent.click(screen.getByLabelText("Chat actions for Example chat"));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Delete" }));

    const deleteDialog = screen.getByRole("dialog", { name: "Delete chat" });
    const form = deleteDialog.querySelector("form");
    expect(form).not.toBeNull();
    await waitFor(() => expect(form!).toHaveFocus());
    const cancel = within(deleteDialog).getByRole("button", { name: "Cancel" });
    const confirm = within(deleteDialog).getByRole("button", { name: "Delete" });
    expect(confirm).not.toHaveFocus();

    fireEvent.keyDown(form!, { key: "Tab" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
    expect(api.deleteAgentCatalogSession).not.toHaveBeenCalled();
  });

  it("returns focus to a stable originating control after a completed mutation", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    const trigger = screen.getByRole("button", { name: "Create project" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    fireEvent.change(within(dialog).getByLabelText("Project name"), {
      target: { value: "Focused project" },
    });
    fireEvent.submit(dialog.querySelector("form")!);

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create project" })).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("re-homes focus into the rail when a completed action removed its trigger row", async () => {
    const api = transport();
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    const trigger = screen.getByLabelText("Chat actions for Example chat");
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Chat actions for Example chat" }))
      .getByRole("button", { name: "Pin" }));

    await waitFor(() => expect(api.updateAgentCatalogSession).toHaveBeenCalledWith(
      SESSION_ID,
      { expected_revision: 2, pinned: true },
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(screen.getByRole("button", { name: "New chat" })).toHaveFocus());
    expect(document.body).not.toHaveFocus();
  });

  it("does not steal focus the user moved while a catalog mutation was pending", async () => {
    const api = transport();
    const pending = deferred<AgentProject>();
    api.createAgentProject.mockImplementationOnce(() => pending.promise);
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    await screen.findByText("Example project");
    const trigger = screen.getByRole("button", { name: "Create project" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Create project" });
    fireEvent.change(within(dialog).getByLabelText("Project name"), {
      target: { value: "Background project" },
    });
    fireEvent.submit(dialog.querySelector("form")!);

    const searchBox = screen.getByRole("searchbox");
    searchBox.focus();
    pending.resolve(project({ name: "Background project" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Create project" })).toBeNull());
    await new Promise((resolve) => { window.setTimeout(resolve, 0); });
    expect(searchBox).toHaveFocus();
    expect(trigger).not.toHaveFocus();
  });

  it("opens retained-message search without a model and restores its trigger on Escape", async () => {
    const api = {
      ...transport(),
      searchAgentSavedMessages: vi.fn(),
      getAgentCatalogSession: vi.fn(),
    };
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onOpenSavedMessage={vi.fn()}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Search saved messages" });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Search saved messages" });
    expect(within(dialog).getByRole("searchbox")).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(api.searchAgentSavedMessages).not.toHaveBeenCalled();
  });

  it("refuses a search hit whose retained history changed before navigation", async () => {
    const retained = catalogSession({
      retention_policy: "local_history", history_revision: 4, last_event_seq: 8,
    });
    const api = {
      ...transport(retained),
      searchAgentSavedMessages: vi.fn(async () => ({
        contract_version: "agent-message-search.v1" as const,
        snapshot: SNAPSHOT, limit: 20, offset: 0, total: 1, next_offset: null, complete: true,
        matches: [{
          session_id: SESSION_ID, project_id: PROJECT_ID, project_name: "Example project",
          title: "Example chat", match_event_seq: 7, history_revision: 3,
          role: "user" as const, excerpt: "Synthetic retained request",
        }],
      })),
      getAgentCatalogSession: vi.fn(async () => retained),
    };
    const onOpenSavedMessage = vi.fn(async () => true);
    render(
      <AgentCatalogRail
        liveSessions={[]}
        onCloseLiveSession={vi.fn()}
        onNewChat={vi.fn()}
        onOpenLiveSession={vi.fn()}
        onOpenUnavailableSession={vi.fn()}
        onOpenSavedMessage={onOpenSavedMessage}
        onProjectChange={vi.fn()}
        selectedProjectId={PROJECT_ID}
        transport={api}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Search saved messages" }));
    const dialog = screen.getByRole("dialog", { name: "Search saved messages" });
    fireEvent.change(within(dialog).getByRole("searchbox"), { target: { value: "retained" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Search saved messages" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: /Open matching saved message/u }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("may have changed or been deleted");
    expect(onOpenSavedMessage).not.toHaveBeenCalled();
  });
});
