import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  McpManagedProjectBinding,
  McpManagedProjectRuntime,
  McpManagedServerList,
} from "../../shared/api/contracts";
import { syntheticMcpManagedProjectRuntime } from "../../shared/api/mcpManagedRuntime.test-support";
import {
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedToolSnapshot,
} from "../../shared/api/mcpManagedServer.test-support";
import { AgentMcpProjectToolsPanel } from "./AgentMcpProjectToolsPanel";

const projectA = "f".repeat(32);
const projectB = "e".repeat(32);
const managementId = "9".repeat(32);
const snapshot = syntheticMcpManagedToolSnapshot();

function binding(projectId: string, overrides: Partial<McpManagedProjectBinding> = {}): McpManagedProjectBinding {
  return {
    project_id: projectId,
    project_name: projectId === projectA ? "Synthetic alpha" : "Synthetic beta",
    enabled: true,
    required_permissions: ["network_egress"],
    granted_permissions: ["network_egress"],
    admitted_tool_ids: ["1".repeat(32)],
    tool_snapshot_id: snapshot.snapshot_id,
    admission_state: "admitted",
    effective_state: "inactive_host_unavailable",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    ...overrides,
  };
}

function managed(bindings: McpManagedProjectBinding[] = [binding(projectA)]): McpManagedServerList {
  return syntheticMcpManagedServerList([syntheticMcpManagedServer({
    management_id: managementId,
    project_bindings: bindings,
    tool_review_state: "reviewable",
    tool_snapshot: snapshot,
  })]);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("AgentMcpProjectToolsPanel", () => {
  it("keeps MCP reads inert when the live chat has no durable project", () => {
    const listMcpManagedServers = vi.fn();
    const getMcpManagedProjectRuntime = vi.fn();
    render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={null}
      transport={{ getMcpManagedProjectRuntime, listMcpManagedServers }}
    />);

    expect(screen.getByText("No project scope")).toBeVisible();
    expect(listMcpManagedServers).not.toHaveBeenCalled();
    expect(getMcpManagedProjectRuntime).not.toHaveBeenCalled();
  });

  it("shows only exact admitted tools from the active project runtime", async () => {
    const listMcpManagedServers = vi.fn().mockResolvedValue(managed());
    const getMcpManagedProjectRuntime = vi.fn().mockResolvedValue(
      syntheticMcpManagedProjectRuntime({ project_id: projectA }),
    );
    render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectA}
      transport={{ getMcpManagedProjectRuntime, listMcpManagedServers }}
    />);

    expect(await screen.findByText("1 ready")).toBeVisible();
    fireEvent.click(screen.getByText("Project tools"));
    expect(screen.getByText("Synthetic read")).toBeVisible();
    expect(screen.getByText("mcp_99999999_synthetic_read")).toBeVisible();
    expect(getMcpManagedProjectRuntime).toHaveBeenCalledWith(projectA, expect.any(AbortSignal));
    expect(listMcpManagedServers).toHaveBeenCalledWith(expect.any(AbortSignal));
  });

  it("distinguishes durable admission from a stopped app-run host", async () => {
    render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectA}
      transport={{
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
          project_id: projectA,
          ready_host_count: 0,
          ready_tool_count: 0,
          tools: [],
        })),
        listMcpManagedServers: vi.fn().mockResolvedValue(managed()),
      }}
    />);

    expect(await screen.findByText("1 admitted · stopped")).toBeVisible();
    fireEvent.click(screen.getByText("Project tools"));
    expect(screen.getByText("Stopped plans").nextSibling).toHaveTextContent("1");
    expect(screen.getByText(/Stopped hosts never auto-start/)).toBeVisible();
  });

  it("hides runtime tools when project scope or exact authority disagrees", async () => {
    const runtime = syntheticMcpManagedProjectRuntime({ project_id: projectA });
    runtime.tools = runtime.tools.map((tool) => ({ ...tool, project_id: projectB }));
    render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectA}
      transport={{
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(runtime),
        listMcpManagedServers: vi.fn().mockResolvedValue(managed()),
      }}
    />);

    expect(await screen.findByText("Refresh required")).toBeVisible();
    fireEvent.click(screen.getByText("Project tools"));
    expect(screen.getByRole("alert")).toHaveTextContent(/Ready tools are hidden/);
    expect(screen.queryByText("mcp_99999999_synthetic_read")).toBeNull();
  });

  it("ignores a late response from the previously active project", async () => {
    const oldManaged = deferred<McpManagedServerList>();
    const oldRuntime = deferred<McpManagedProjectRuntime>();
    const runtimeB = syntheticMcpManagedProjectRuntime({
      project_id: projectB,
      tools: syntheticMcpManagedProjectRuntime({ project_id: projectB }).tools.map((tool) => ({
        ...tool,
        title: "Synthetic beta tool",
      })),
    });
    const listMcpManagedServers = vi.fn()
      .mockReturnValueOnce(oldManaged.promise)
      .mockResolvedValueOnce(managed([binding(projectA), binding(projectB)]));
    const getMcpManagedProjectRuntime = vi.fn((projectId: string) => (
      projectId === projectA ? oldRuntime.promise : Promise.resolve(runtimeB)
    ));
    const { rerender } = render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectA}
      transport={{ getMcpManagedProjectRuntime, listMcpManagedServers }}
    />);

    rerender(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectB}
      transport={{ getMcpManagedProjectRuntime, listMcpManagedServers }}
    />);
    expect(await screen.findByText("1 ready")).toBeVisible();
    fireEvent.click(screen.getByText("Project tools"));
    expect(screen.getByText("Synthetic beta tool")).toBeVisible();

    oldManaged.resolve(managed([binding(projectA), binding(projectB)]));
    oldRuntime.resolve(syntheticMcpManagedProjectRuntime({ project_id: projectA }));
    await waitFor(() => expect(screen.getByText("Synthetic beta tool")).toBeVisible());
    expect(screen.queryByText("Synthetic read")).toBeNull();
  });

  it("recovers an unavailable projection only after an explicit retry", async () => {
    const listMcpManagedServers = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic unavailable"))
      .mockResolvedValueOnce(managed());
    const getMcpManagedProjectRuntime = vi.fn().mockResolvedValue(
      syntheticMcpManagedProjectRuntime({ project_id: projectA }),
    );
    render(<AgentMcpProjectToolsPanel
      onOpenStore={vi.fn()}
      projectId={projectA}
      transport={{ getMcpManagedProjectRuntime, listMcpManagedServers }}
    />);

    expect(await screen.findByText("Status unavailable")).toBeVisible();
    fireEvent.click(screen.getByText("Project tools"));
    expect(screen.getByRole("alert")).toHaveTextContent(/No ready tool authority/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh project tools" }));
    expect(await screen.findByText("1 ready")).toBeVisible();
    expect(listMcpManagedServers).toHaveBeenCalledTimes(2);
  });
});
