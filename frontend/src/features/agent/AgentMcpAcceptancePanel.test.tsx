import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { syntheticMcpManagedServer } from "../../shared/api/mcpManagedServer.test-support";
import { AgentMcpAcceptancePanel } from "./AgentMcpAcceptancePanel";
import type { TrustedMcpAcceptanceRun } from "./trustedMcpAcceptance";

const PROJECT = "f".repeat(32);
const SESSION = "e".repeat(32);

function readyPlan() {
  return syntheticMcpManagedServer({
    option_label: "MCPB release",
    registry_type: "mcpb",
    package_identifier: "https://example.invalid/synthetic.mcpb",
    runtime_hint: "node",
    requirements: [],
    revision: 2,
    install_action: "available_native_confirmation_required",
  });
}

describe("AgentMcpAcceptancePanel", () => {
  it("explains why proof cannot begin without a live project chat", () => {
    const onRunChange = vi.fn();
    render(<AgentMcpAcceptancePanel
      activeProjectId={PROJECT}
      activeSessionId={null}
      eventHead={4}
      onRunChange={onRunChange}
      run={null}
      server={readyPlan()}
    />);

    expect(screen.getByRole("button", { name: "Begin trusted MCP proof" })).toBeDisabled();
    expect(screen.getByText(/Open one live Agent chat/)).toBeVisible();
    expect(onRunChange).not.toHaveBeenCalled();
  });

  it("creates a content-free, revision-bound receipt at the current event head", () => {
    const onRunChange = vi.fn();
    const server = readyPlan();
    render(<AgentMcpAcceptancePanel
      activeProjectId={PROJECT}
      activeSessionId={SESSION}
      eventHead={17}
      onRunChange={onRunChange}
      run={null}
      server={server}
    />);

    fireEvent.click(screen.getByRole("button", { name: "Begin trusted MCP proof" }));
    expect(onRunChange).toHaveBeenCalledWith(expect.objectContaining({
      managementId: server.management_id,
      projectId: PROJECT,
      sessionId: SESSION,
      eventFloor: 17,
      phase: "install",
      completedSteps: ["baseline"],
    }));
  });

  it("keeps the page-owned receipt when the Store view unmounts and mounts again", () => {
    const server = readyPlan();
    function Harness() {
      const [run, setRun] = useState<TrustedMcpAcceptanceRun | null>(null);
      const [shown, setShown] = useState(true);
      return (
        <>
          <button onClick={() => setShown((value) => !value)} type="button">Toggle Store</button>
          {shown && <AgentMcpAcceptancePanel
            activeProjectId={PROJECT}
            activeSessionId={SESSION}
            eventHead={8}
            onRunChange={setRun}
            run={run}
            server={server}
          />}
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Begin trusted MCP proof" }));
    expect(screen.getByText("In progress")).toBeVisible();
    expect(screen.getByText(/normal Install control/)).toBeVisible();
    expect(screen.getByText("Retained rollback generation removed")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Toggle Store" }));
    expect(screen.queryByRole("region", { name: "Trusted MCP lifecycle acceptance" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle Store" }));
    expect(screen.getByText("In progress")).toBeVisible();
    expect(screen.getByText("Clean reviewed MCPB plan").parentElement).toHaveAttribute("data-state", "passed");
  });
});
