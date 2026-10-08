import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { McpManagedHostStatus, McpManagedProjectBinding } from "../../shared/api/contracts";
import {
  syntheticMcpManagedHostBinding,
  syntheticMcpManagedHostStartPreview,
  syntheticMcpManagedHostStatus,
  syntheticMcpManagedProjectRuntime,
  syntheticReadyMcpManagedHostStatus,
} from "../../shared/api/mcpManagedRuntime.test-support";
import { syntheticMcpManagedServer } from "../../shared/api/mcpManagedServer.test-support";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentMcpManagedRuntimePanel } from "./AgentMcpManagedRuntimePanel";

const projectId = "f".repeat(32);
const managementId = "9".repeat(32);
const toolSnapshotId = "3".repeat(32);

function projectBinding(overrides: Partial<McpManagedProjectBinding> = {}): McpManagedProjectBinding {
  return {
    project_id: projectId,
    project_name: "Synthetic project",
    enabled: true,
    required_permissions: ["network_egress"],
    granted_permissions: ["network_egress"],
    admitted_tool_ids: ["1".repeat(32), "2".repeat(32)],
    tool_snapshot_id: toolSnapshotId,
    admission_state: "admitted",
    effective_state: "inactive_host_unavailable",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    ...overrides,
  };
}

const server = syntheticMcpManagedServer({
  management_id: managementId,
  revision: 4,
  option_kind: "remote_server",
  transport: "streamable-http",
  installation_state: "installed",
  installation_kind: "remote_activation",
  project_bindings: [projectBinding()],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("AgentMcpManagedRuntimePanel", () => {
  it("keeps reads inert, starts the exact admitted host, exposes routed aliases, and stops it", async () => {
    const preview = syntheticMcpManagedHostStartPreview();
    const ready = syntheticReadyMcpManagedHostStatus();
    const stopped = syntheticMcpManagedHostStatus();
    const settled = syntheticMcpManagedHostStatus({
      reason: "stopped_by_owner",
      stopped_at: "2040-01-01T10:02:00Z",
      last_transition_at: "2040-01-01T10:02:00Z",
      cleanup_state: "verified",
    });
    let current: McpManagedHostStatus = stopped;
    const getMcpManagedHostStatus = vi.fn().mockImplementation(async () => current);
    const getMcpManagedHostStartPreview = vi.fn().mockResolvedValue(preview);
    const getMcpManagedProjectRuntime = vi.fn().mockImplementation(async () => (
      current.state === "ready" ? syntheticMcpManagedProjectRuntime() : syntheticMcpManagedProjectRuntime({
        ready_host_count: 0,
        ready_tool_count: 0,
        tools: [],
      })
    ));
    const startMcpManagedHost = vi.fn().mockImplementation(async () => {
      current = ready;
      return ready;
    });
    const stopMcpManagedHost = vi.fn().mockImplementation(async () => {
      current = settled;
      return settled;
    });
    const onRuntimeChange = vi.fn();
    const onAcceptanceEvidence = vi.fn();

    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      onAcceptanceEvidence={onAcceptanceEvidence}
      onRuntimeChange={onRuntimeChange}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus,
        getMcpManagedHostStartPreview,
        getMcpManagedProjectRuntime,
        startMcpManagedHost,
        stopMcpManagedHost,
      }}
      userPresenceAvailable
    />);

    expect(await screen.findByText("Stopped")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Start for this app run" })).toBeEnabled();
    expect(startMcpManagedHost).not.toHaveBeenCalled();
    expect(onAcceptanceEvidence).not.toHaveBeenCalled();
    expect(screen.getByText(/This opens the reviewed remote endpoint/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Start for this app run" }));
    expect(await screen.findByText("Project scoped")).toBeVisible();
    expect(await screen.findByText("mcp_99999999_synthetic_read")).toBeVisible();
    expect(screen.getByText("Fresh confirmation on every call")).toBeVisible();
    expect(startMcpManagedHost).toHaveBeenCalledWith(
      managementId,
      projectId,
      expect.objectContaining({
        expected_server_revision: 4,
        expected_project_binding_revision: 2,
        expected_tool_snapshot_id: toolSnapshotId,
        preview_digest: preview.preview_digest,
      }),
    );
    expect(onAcceptanceEvidence).toHaveBeenNthCalledWith(1, { eventFloor: 0, kind: "host_started", status: ready });

    fireEvent.click(screen.getByRole("button", { name: "Stop host" }));
    await waitFor(() => expect(screen.getByText("Stopped")).toBeVisible());
    expect(stopMcpManagedHost).toHaveBeenCalledWith(
      managementId,
      projectId,
      expect.objectContaining({ expected_instance_id: ready.instance_id }),
    );
    expect(await screen.findByText(/connection and tool-routing authority were removed/)).toBeVisible();
    expect(onAcceptanceEvidence).toHaveBeenNthCalledWith(2, { kind: "host_stopped", status: settled });
    expect(onRuntimeChange).toHaveBeenCalledTimes(2);
  });

  it("does not touch runtime routes before a reviewed project admission exists", () => {
    const getMcpManagedHostStatus = vi.fn();
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding({ enabled: false, admission_state: "disabled", admitted_tool_ids: [], tool_snapshot_id: null })}
      projectId={projectId}
      server={server}
      transport={{ getMcpManagedHostStatus }}
      userPresenceAvailable
    />);
    expect(screen.getByText(/Save at least one reviewed tool/)).toBeVisible();
    expect(getMcpManagedHostStatus).not.toHaveBeenCalled();
  });

  it("reports an unavailable read without claiming a host was started", async () => {
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockRejectedValue(new Error("synthetic failure")),
        getMcpManagedHostStartPreview: vi.fn().mockRejectedValue(new Error("synthetic failure")),
        getMcpManagedProjectRuntime: vi.fn().mockRejectedValue(new Error("synthetic failure")),
      }}
      userPresenceAvailable
    />);
    expect(await screen.findByText("Host status is unavailable. No host was started by this read.")).toBeVisible();
  });

  it("rejects host status returned for a different project", async () => {
    const startMcpManagedHost = vi.fn();
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticMcpManagedHostStatus({
          project_id: "e".repeat(32),
        })),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview()),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime()),
        startMcpManagedHost,
      }}
      userPresenceAvailable
    />);

    expect(await screen.findByText("Host status is unavailable. No host was started by this read.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start for this app run" })).toBeNull();
    expect(startMcpManagedHost).not.toHaveBeenCalled();
  });

  it("rejects a start preview that does not match the exact admission", async () => {
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticMcpManagedHostStatus()),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview({
          binding: syntheticMcpManagedHostBinding({ project_id: "e".repeat(32) }),
        })),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
          ready_host_count: 0,
          ready_tool_count: 0,
          tools: [],
        })),
        startMcpManagedHost: vi.fn(),
      }}
      userPresenceAvailable
    />);

    expect(await screen.findByText(/Start is unavailable for this exact plan/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start for this app run" })).toBeNull();
  });

  it("hides routed aliases when the runtime projection contradicts its project", async () => {
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticReadyMcpManagedHostStatus()),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview()),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
          project_id: "e".repeat(32),
        })),
      }}
      userPresenceAvailable
    />);

    expect(await screen.findByText(/routed-tool projection is unavailable/)).toBeVisible();
    expect(screen.queryByText("mcp_99999999_synthetic_read")).toBeNull();
    expect(screen.queryByText(/tools? from this server are available/)).toBeNull();
  });

  it("does not let a late start response overwrite a newly selected project", async () => {
    const oldStart = deferred<McpManagedHostStatus>();
    const projectBeta = "e".repeat(32);
    const betaBinding = projectBinding({ project_id: projectBeta, project_name: "Synthetic beta" });
    const runtimeFor = (id: string) => syntheticMcpManagedProjectRuntime({
      project_id: id,
      ready_host_count: 0,
      ready_tool_count: 0,
      tools: [],
    });
    const previewFor = (id: string) => syntheticMcpManagedHostStartPreview({
      binding: syntheticMcpManagedHostBinding({
        project_id: id,
        project_binding_revision: 2,
      }),
    });
    const onRuntimeChange = vi.fn();
    const transport = {
      getMcpManagedHostStatus: vi.fn().mockImplementation(async (_managementId: string, id: string) => (
        syntheticMcpManagedHostStatus({ project_id: id })
      )),
      getMcpManagedHostStartPreview: vi.fn().mockImplementation(async (_managementId: string, id: string) => previewFor(id)),
      getMcpManagedProjectRuntime: vi.fn().mockImplementation(async (id: string) => runtimeFor(id)),
      startMcpManagedHost: vi.fn().mockReturnValue(oldStart.promise),
    };
    const { rerender } = render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      onRuntimeChange={onRuntimeChange}
      projectId={projectId}
      server={server}
      transport={transport}
      userPresenceAvailable
    />);
    fireEvent.click(await screen.findByRole("button", { name: "Start for this app run" }));

    rerender(<AgentMcpManagedRuntimePanel
      binding={betaBinding}
      onRuntimeChange={onRuntimeChange}
      projectId={projectBeta}
      server={syntheticMcpManagedServer({ ...server, project_bindings: [betaBinding] })}
      transport={transport}
      userPresenceAvailable
    />);
    expect(await screen.findByText("Stopped")).toBeVisible();

    oldStart.resolve(syntheticReadyMcpManagedHostStatus());
    await waitFor(() => expect(onRuntimeChange).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Stopped")).toBeVisible();
    expect(screen.queryByText(/Host ready\. Only the admitted project tools/)).toBeNull();
  });

  it("reports unhealthy and cleanup-required hosts without offering an unsafe start", async () => {
    const { rerender } = render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticReadyMcpManagedHostStatus({
          state: "unhealthy",
          reason: "health_timeout",
          error_code: "mcp_managed_host_health_failed",
          tool_calls_available: false,
          tool_routing_state: "inactive",
        })),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview()),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
          ready_host_count: 0,
          ready_tool_count: 0,
          tools: [],
        })),
        stopMcpManagedHost: vi.fn(),
      }}
      userPresenceAvailable
    />);
    expect(await screen.findByText("Unhealthy")).toBeVisible();
    expect(screen.getByText(/failed a bounded runtime check/)).toBeVisible();
    expect(screen.queryByText("mcp_managed_host_health_failed")).toBeNull();
    expect(screen.getByRole("button", { name: "Stop host" })).toBeEnabled();

    rerender(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={{ ...server, revision: server.revision + 1 }}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticMcpManagedHostStatus({
          state: "cleanup_required",
          reason: "cleanup_unconfirmed",
          cleanup_state: "unconfirmed",
          error_code: "mcp_host_cleanup_unconfirmed",
        })),
      }}
      userPresenceAvailable
    />);
    expect(await screen.findByText("Cleanup required")).toBeVisible();
    expect(screen.getByText(/Starting is blocked/)).toBeVisible();
    expect(screen.getByText(/Cleanup verification failed/)).toBeVisible();
    expect(screen.queryByText("mcp_host_cleanup_unconfirmed")).toBeNull();
    expect(screen.queryByRole("button", { name: "Start for this app run" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop host" })).toBeNull();
  });

  it("reports a local output-limit start failure without rendering private process output", async () => {
    const onAcceptanceEvidence = vi.fn();
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      onAcceptanceEvidence={onAcceptanceEvidence}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticMcpManagedHostStatus()),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview()),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime({
          ready_host_count: 0,
          ready_tool_count: 0,
          tools: [],
        })),
        startMcpManagedHost: vi.fn().mockRejectedValue(new TransportError(
          "EXAMPLE_PRIVATE_PROCESS_OUTPUT_CANARY",
          503,
          "mcp_host_process_output_limit",
        )),
      }}
      userPresenceAvailable
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Start for this app run" }));
    expect(await screen.findByText(/owned tree was stopped/)).toBeVisible();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_PROCESS_OUTPUT_CANARY/)).toBeNull();
    expect(onAcceptanceEvidence).not.toHaveBeenCalled();
  });

  it("never renders a hostile status code even when a component transport is bypassed", async () => {
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticReadyMcpManagedHostStatus({
          state: "unhealthy",
          reason: "transport_failed",
          host_lease_active: false,
          error_code: "example_private_failure_canary",
          tool_calls_available: false,
          tool_routing_state: "inactive",
        })),
      }}
      userPresenceAvailable
    />);

    expect(await screen.findByText("Unhealthy")).toBeVisible();
    expect(screen.getByText(/failed a bounded runtime check/)).toBeVisible();
    expect(screen.queryByText(/example_private_failure_canary/)).toBeNull();
  });

  it("keeps routing removed when stop cleanup cannot be verified", async () => {
    render(<AgentMcpManagedRuntimePanel
      binding={projectBinding()}
      projectId={projectId}
      server={server}
      transport={{
        getMcpManagedHostStatus: vi.fn().mockResolvedValue(syntheticReadyMcpManagedHostStatus()),
        getMcpManagedHostStartPreview: vi.fn().mockResolvedValue(syntheticMcpManagedHostStartPreview()),
        getMcpManagedProjectRuntime: vi.fn().mockResolvedValue(syntheticMcpManagedProjectRuntime()),
        stopMcpManagedHost: vi.fn().mockRejectedValue(new TransportError(
          "EXAMPLE_PRIVATE_CLEANUP_CANARY",
          503,
          "mcp_host_cleanup_unconfirmed",
        )),
      }}
      userPresenceAvailable
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Stop host" }));
    expect(await screen.findByText(/removed from tool routing/)).toBeVisible();
    expect(screen.queryByText(/EXAMPLE_PRIVATE_CLEANUP_CANARY/)).toBeNull();
  });
});
