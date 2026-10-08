import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { exampleAgentOrchestrationManifest } from "../../shared/api/agentOrchestrationFixtures.test-support";
import { AgentReadinessPanel } from "./AgentReadinessPanel";
import {
  AGENT_LEGACY_PARITY,
  AGENT_PARITY_SUMMARY,
  AGENT_REQUESTED_CAPABILITIES,
} from "./agentReleaseParity";

describe("AgentReadinessPanel", () => {
  it("separates verified contracts, live loopback integration, and pending owner evidence", async () => {
    const getAgentOrchestration = vi.fn().mockResolvedValue(exampleAgentOrchestrationManifest());
    render(
      <AgentReadinessPanel
        onOpenConnections={vi.fn()}
        onOpenOwnerChecks={vi.fn()}
        transport={{ getAgentOrchestration }}
        userPresenceAvailable
      />,
    );

    expect(screen.getByRole("heading", { name: "Agent capability readiness" })).toBeVisible();
    expect(screen.getByLabelText("Requested Agent capabilities").children).toHaveLength(15);
    expect(screen.getByText("Checking live evidence")).toBeVisible();
    await waitFor(() => expect(screen.getByText("Loopback integrated", { selector: ".agent-readiness__state" })).toBeVisible());
    expect(screen.getAllByText(/owner check pending/u)).toHaveLength(10);
    expect(screen.getAllByText("Contract verified")).toHaveLength(1);
    expect(screen.queryByText("Not implemented")).toBeNull();
    expect(screen.getByText(/Provider-neutral controller and MCP endpoint/u)).toBeVisible();
    expect(screen.getByText(/Create, view, edit, move, trash, diff, and review workspace files/u)).toBeVisible();
    expect(screen.getByText(/Contract tests, this running loopback app, and owner-only checks are reported separately/u)).toBeVisible();
    expect(getAgentOrchestration).toHaveBeenCalledOnce();
  });

  it("fails closed when the current loopback contract cannot be verified and can retry", async () => {
    const getAgentOrchestration = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic unavailable"))
      .mockResolvedValueOnce(exampleAgentOrchestrationManifest());
    render(
      <AgentReadinessPanel
        onOpenConnections={vi.fn()}
        onOpenOwnerChecks={vi.fn()}
        transport={{ getAgentOrchestration }}
        userPresenceAvailable={false}
      />,
    );

    expect(await screen.findByText("Loopback unavailable")).toBeVisible();
    expect(screen.getAllByText("Blocked · loopback contract unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText("10 blocked here")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry live check" }));
    await waitFor(() => expect(screen.getByText("Owner checks blocked here")).toBeVisible());
    expect(screen.getAllByText("Blocked here · native owner check unavailable").length).toBeGreaterThan(0);
    expect(getAgentOrchestration).toHaveBeenCalledTimes(2);
  });

  it("keeps every requested row bound to a known parity group", () => {
    const parityKeys = new Set(AGENT_LEGACY_PARITY.map((item) => item.key));
    expect(AGENT_REQUESTED_CAPABILITIES.every((item) => (
      item.parityKeys.length > 0 && item.parityKeys.every((key) => parityKeys.has(key))
    ))).toBe(true);
    expect(AGENT_PARITY_SUMMARY).toMatchObject({
      complete: 16,
      missing: 0,
      ownerPending: 10,
      platformBlocked: 0,
      total: 16,
    });
  });

  it("routes to controller setup and guarded owner checks without starting either", () => {
    const openConnections = vi.fn();
    const openOwnerChecks = vi.fn();
    render(
      <AgentReadinessPanel
        onOpenConnections={openConnections}
        onOpenOwnerChecks={openOwnerChecks}
        transport={{}}
        userPresenceAvailable={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open connections" }));
    fireEvent.click(screen.getByRole("button", { name: "Open owner checks" }));
    expect(openConnections).toHaveBeenCalledOnce();
    expect(openOwnerChecks).toHaveBeenCalledOnce();
  });
});
