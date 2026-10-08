import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { McpManagedProjectBinding, PromptEnhancerTransport } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import {
  syntheticMcpManagedProbeReceipt,
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedServerReceipt,
  syntheticMcpManagedToolSnapshot,
} from "../../shared/api/mcpManagedServer.test-support";
import { AgentMcpManagedPlanView } from "./AgentMcpManagedPlanView";

const projectA = "f".repeat(32);
const projectB = "e".repeat(32);
const missingProject = "d".repeat(32);
const snapshot = syntheticMcpManagedToolSnapshot();
type ListAgentProjects = NonNullable<PromptEnhancerTransport["listAgentProjects"]>;
type GetManagedToolSnapshot = NonNullable<PromptEnhancerTransport["getMcpManagedToolSnapshot"]>;

function project(projectId: string, name: string) {
  return {
    contract_version: "agent-catalog.v2" as const,
    project_id: projectId,
    name,
    created_at: "2040-01-01T09:00:00Z",
    updated_at: "2040-01-01T09:00:00Z",
    revision: 1,
    pinned: false,
    archived_at: null,
    session_count: 0,
    is_default: false,
  };
}

const projects = {
  contract_version: "agent-catalog.v2" as const,
  projects: [project(projectA, "Synthetic alpha"), project(projectB, "Synthetic beta")],
};

function binding(overrides: Partial<McpManagedProjectBinding> = {}): McpManagedProjectBinding {
  const base = syntheticMcpManagedProbeReceipt().server;
  return {
    project_id: projectA,
    project_name: "Synthetic alpha",
    enabled: true,
    required_permissions: base.required_permissions,
    granted_permissions: base.required_permissions,
    admitted_tool_ids: snapshot.tools.map((tool) => tool.tool_id).sort(),
    tool_snapshot_id: snapshot.snapshot_id,
    admission_state: "admitted",
    effective_state: "inactive_install_required",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    ...overrides,
  };
}

function reviewedServer(projectBindings: McpManagedProjectBinding[] = []) {
  const probed = syntheticMcpManagedProbeReceipt().server;
  return syntheticMcpManagedServer({
    ...probed,
    project_bindings: projectBindings,
    tool_snapshot: snapshot,
    tool_review_state: "reviewable",
  });
}

function renderPlan({
  preferredProjectId = projectA,
  listAgentProjects = vi.fn<ListAgentProjects>().mockResolvedValue(projects),
  getMcpManagedToolSnapshot = vi.fn<GetManagedToolSnapshot>().mockResolvedValue(snapshot),
  server = reviewedServer(),
}: {
  preferredProjectId?: string | null;
  listAgentProjects?: ListAgentProjects;
  getMcpManagedToolSnapshot?: GetManagedToolSnapshot;
  server?: ReturnType<typeof reviewedServer>;
} = {}) {
  return render(<AgentMcpManagedPlanView
    onBack={vi.fn()}
    onServer={vi.fn()}
    preferredProjectId={preferredProjectId}
    secretVault={syntheticMcpManagedServerList().secret_vault}
    server={server}
    transport={{ getMcpManagedToolSnapshot, listAgentProjects }}
    userPresenceAvailable
  />);
}

describe("AgentMcpManagedPlanView project authority", () => {
  it("selects the exact active project, preserves current admission, and never falls back to another project", async () => {
    const currentServer = reviewedServer([binding()]);
    const { rerender } = renderPlan({ server: currentServer });

    const selector = await screen.findByRole("combobox", { name: "Agent project" });
    await waitFor(() => expect(selector).toHaveValue(projectA));
    expect(screen.getByText(/Editing the active chat project/)).toBeVisible();
    expect(await screen.findByRole(
      "button",
      { name: "Admission already current" },
      { timeout: 5_000 },
    )).toBeDisabled();

    rerender(<AgentMcpManagedPlanView
      onBack={vi.fn()}
      onServer={vi.fn()}
      preferredProjectId={missingProject}
      secretVault={syntheticMcpManagedServerList().secret_vault}
      server={currentServer}
      transport={{
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        listAgentProjects: vi.fn().mockResolvedValue(projects),
      }}
      userPresenceAvailable
    />);
    expect(await screen.findByRole("alert", { name: "" })).toHaveTextContent(/active chat project is not available/i);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Agent project" })).toHaveValue(""));
    expect(screen.getByRole("button", { name: "Select visible" })).toBeDisabled();
  });

  it("requires an explicit retry after the project list fails", async () => {
    const listAgentProjects = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic project failure"))
      .mockResolvedValueOnce(projects);
    renderPlan({ listAgentProjects });

    expect(await screen.findByText(/No grant was changed and no fallback project was selected/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry Agent projects" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Agent project" })).toHaveValue(projectA));
    expect(listAgentProjects).toHaveBeenCalledTimes(2);
  });

  it("requires an explicit retry after exact reviewed tools cannot be verified", async () => {
    const getMcpManagedToolSnapshot = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic tool failure"))
      .mockResolvedValueOnce(snapshot);
    renderPlan({ getMcpManagedToolSnapshot });

    expect(await screen.findByText(/reviewed tools could not be verified/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry reviewed tools" }));
    const toolGroup = await screen.findByRole("group", { name: "Allowed reviewed tools" });
    await waitFor(() => expect(within(toolGroup).getAllByRole("checkbox")).toHaveLength(snapshot.tools.length));
    expect(getMcpManagedToolSnapshot).toHaveBeenCalledTimes(2);
  });

  it("filters large tool sets and supports explicit visible selection and clearing", async () => {
    renderPlan();
    const filter = await screen.findByRole("searchbox", { name: "Filter reviewed tools" });
    await waitFor(() => expect(filter).toBeEnabled());
    fireEvent.change(filter, { target: { value: "tool 2" } });
    const toolGroup = screen.getByRole("group", { name: "Allowed reviewed tools" });
    expect(within(toolGroup).queryByText("Synthetic tool 1")).toBeNull();
    expect(within(toolGroup).getByText("Synthetic tool 2")).toBeVisible();
    expect(screen.getByText("0 selected · 1 shown")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Select visible" }));
    expect(screen.getByText("1 selected · 1 shown")).toBeVisible();
    expect(within(toolGroup).getByRole("checkbox")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Clear selected" }));
    expect(screen.getByText("0 selected · 1 shown")).toBeVisible();
    expect(screen.getByRole("button", { name: "Clear selected" })).toBeDisabled();
  });

  it("explains a bounded remote refusal and leaves an explicit keyboard retry", async () => {
    const probeMcpManagedServer = vi.fn().mockRejectedValue(
      new TransportError(
        "Remote compatibility request failed",
        503,
        "mcp_host_redirect_refused",
      ),
    );
    render(<AgentMcpManagedPlanView
      onBack={vi.fn()}
      onServer={vi.fn()}
      preferredProjectId={projectA}
      secretVault={syntheticMcpManagedServerList().secret_vault}
      server={reviewedServer()}
      transport={{
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        listAgentProjects: vi.fn().mockResolvedValue(projects),
        probeMcpManagedServer,
      }}
      userPresenceAvailable
    />);

    const retry = await screen.findByRole("button", { name: "Check again" });
    fireEvent.click(retry);

    expect(await screen.findByText(/origin, redirect, or TLS safety check/)).toBeVisible();
    await waitFor(() => expect(retry).toBeEnabled());
    retry.focus();
    expect(retry).toHaveFocus();
    expect(probeMcpManagedServer).toHaveBeenCalledTimes(1);
  });

  it("explains a local process-output refusal without exposing process content", async () => {
    const probeMcpManagedServer = vi.fn().mockRejectedValue(
      new TransportError(
        "EXAMPLE_PRIVATE_PROCESS_OUTPUT_CANARY",
        503,
        "mcp_host_process_output_limit",
      ),
    );
    render(<AgentMcpManagedPlanView
      onBack={vi.fn()}
      onServer={vi.fn()}
      preferredProjectId={projectA}
      secretVault={syntheticMcpManagedServerList().secret_vault}
      server={reviewedServer()}
      transport={{
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        listAgentProjects: vi.fn().mockResolvedValue(projects),
        probeMcpManagedServer,
      }}
      userPresenceAvailable
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    expect(await screen.findByText(/owned process tree was stopped/)).toBeVisible();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_PROCESS_OUTPUT_CANARY/)).toBeNull();
  });

  it("explains a recursive tool-schema refusal without exposing server content", async () => {
    const probeMcpManagedServer = vi.fn().mockRejectedValue(
      new TransportError(
        "EXAMPLE_PRIVATE_MCP_SCHEMA_CANARY",
        422,
        "mcp_host_tool_schema_recursive",
      ),
    );
    render(<AgentMcpManagedPlanView
      onBack={vi.fn()}
      onServer={vi.fn()}
      preferredProjectId={projectA}
      secretVault={syntheticMcpManagedServerList().secret_vault}
      server={reviewedServer()}
      transport={{
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        listAgentProjects: vi.fn().mockResolvedValue(projects),
        probeMcpManagedServer,
      }}
      userPresenceAvailable
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    expect(await screen.findByText(/tool schema was unsafe, unsupported, recursive, or over a safety limit/)).toBeVisible();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_MCP_SCHEMA_CANARY/)).toBeNull();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
  });

  it("emits project-admission evidence only after the exact mutation succeeds", async () => {
    const currentBinding = binding();
    const currentServer = reviewedServer([currentBinding]);
    const nextBinding = {
      ...currentBinding,
      admitted_tool_ids: [snapshot.tools[0].tool_id],
      revision: currentBinding.revision + 1,
    };
    const nextServer = {
      ...currentServer,
      project_bindings: [nextBinding],
      revision: currentServer.revision + 1,
    };
    const setMcpManagedProjectBinding = vi.fn().mockResolvedValue(
      syntheticMcpManagedServerReceipt(nextServer),
    );
    const onAcceptanceEvidence = vi.fn();
    render(<AgentMcpManagedPlanView
      onAcceptanceEvidence={onAcceptanceEvidence}
      onBack={vi.fn()}
      onServer={vi.fn()}
      preferredProjectId={projectA}
      secretVault={syntheticMcpManagedServerList().secret_vault}
      server={currentServer}
      transport={{
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        listAgentProjects: vi.fn().mockResolvedValue(projects),
        setMcpManagedProjectBinding,
      }}
      userPresenceAvailable
    />);

    const tools = await screen.findByRole("group", { name: "Allowed reviewed tools" });
    const choices = within(tools).getAllByRole("checkbox");
    expect(choices).toHaveLength(2);
    fireEvent.click(choices[1]);
    fireEvent.click(screen.getByRole("button", { name: "Save project admission" }));

    await waitFor(() => expect(onAcceptanceEvidence).toHaveBeenCalledWith({
      kind: "project_admission",
      projectId: projectA,
      server: nextServer,
      toolSnapshot: snapshot,
    }));
    expect(setMcpManagedProjectBinding).toHaveBeenCalledWith(
      currentServer.management_id,
      projectA,
      expect.objectContaining({
        expected_revision: currentServer.revision,
        admitted_tool_ids: [snapshot.tools[0].tool_id],
      }),
    );
  });
});
