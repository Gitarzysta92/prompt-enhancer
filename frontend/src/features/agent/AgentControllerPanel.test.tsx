import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { exampleAgentOrchestrationManifest } from "../../shared/api/agentOrchestrationFixtures.test-support";
import type { AgentHardeningSnapshot } from "../../shared/api/contracts";
import { AgentControllerPanel } from "./AgentControllerPanel";

const cleanHardeningSnapshot: AgentHardeningSnapshot = {
  contract_version: "agent-hardening.v1",
  generated_on_demand: true,
  contains_content: false,
  recovery_state: "clean",
  recovery_actions: [],
  catalog: {
    state: "ready",
    reason_code: null,
    schema_version: 30,
    quick_check_passed: true,
    foreign_key_violations_observed: 0,
    foreign_key_scan_truncated: false,
    projection_violations: 0,
    counts: {
      projects: 2,
      archived_projects: 0,
      sessions: 5,
      archived_sessions: 1,
      metadata_only_sessions: 2,
      retained_sessions: 3,
      history_events: 18,
      interrupted_retained_sessions: 0,
      artifacts: 2,
      artifact_versions: 3,
      staged_attachments: 0,
      attached_attachments: 1,
    },
  },
  live: {
    state: "ready",
    reason_code: null,
    counts: {
      sessions: 1,
      running_turns: 0,
      closing_sessions: 0,
      pending_approvals: 0,
      cleanup_unconfirmed: 0,
      command_cleanup_quarantined: false,
      recovered_read_only: 0,
      history_write_failures: 0,
      shutting_down: false,
    },
  },
};

describe("AgentControllerPanel", () => {
  it("shows a verified complete controller surface without exposing a token", async () => {
    const getAgentOrchestration = vi.fn().mockResolvedValue(
      exampleAgentOrchestrationManifest(),
    );

    render(<AgentControllerPanel transport={{ getAgentOrchestration }} userPresenceAvailable={false} />);

    expect(screen.getByText("Checking")).toBeInTheDocument();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("local-agent-orchestration.v22")).toBeInTheDocument();
    expect(screen.getByText("GET /v1/agent/orchestration")).toBeInTheDocument();
    expect(screen.getByText(/Applying workspace changes/)).toBeInTheDocument();
    expect(screen.queryByText("synthetic-secret")).not.toBeInTheDocument();
    expect(getAgentOrchestration).toHaveBeenCalledTimes(1);

    expect(screen.getByText("Direct app connections")).toBeInTheDocument();
    expect(screen.getByText(/starts no terminal, subprocess, model, or agent/)).toBeInTheDocument();
    expect(screen.getByText("prompt-enhancer agent-mcp-config")).toBeInTheDocument();
    expect(screen.getByText("prompt-enhancer agent-mcp-config --transport stdio")).toBeInTheDocument();
    expect(screen.getByText("prompt-enhancer agent-mcp-config --transport stdio --with-model-lifecycle")).toBeInTheDocument();
    expect(screen.queryByText("prompt-enhancer agent-controller-config")).not.toBeVisible();
    fireEvent.click(screen.getByText("Advanced: templates, stdio fallback, and scripts"));
    expect(screen.getByText("prompt-enhancer agent-controller-config")).toBeInTheDocument();
    expect(screen.getByText("prompt-enhancer agent-controller discover")).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller invoke/)).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller open/)).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller runtime/)).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller turn/)).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller wait/)).toBeInTheDocument();
    expect(screen.getByText(/prompt-enhancer agent-controller close/)).toBeInTheDocument();
    expect(screen.getByText(/never retried after ambiguity/)).toBeInTheDocument();
    expect(screen.getByText(/runtime and live-close mutate at most once, close retains/)).toBeInTheDocument();
    expect(screen.getByText(/task authorization and a completed redaction preview/)).toBeInTheDocument();
    expect(screen.getByText(/starts no bridge process/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy token-free direct http template command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy headless stdio fallback command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy stdio fallback with model control command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy controller cli contract command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy verify connection command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy invoke one declared operation command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy open project and chat command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy prepare or stop model command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy send and observe one turn command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy continue after native review command" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy close live chat and retain history command" })).toBeInTheDocument();
    expect(screen.getByText(/Private connection values appear only/)).toBeInTheDocument();
  });

  it("fails closed and can retry without disrupting Agent chat", async () => {
    const getAgentOrchestration = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic unavailable"))
      .mockResolvedValueOnce(exampleAgentOrchestrationManifest());

    render(<AgentControllerPanel transport={{ getAgentOrchestration }} userPresenceAvailable={false} />);

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Agent chat remains usable/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
    expect(getAgentOrchestration).toHaveBeenCalledTimes(2);
  });

  it("states that the capability is absent when the transport cannot discover it", async () => {
    render(<AgentControllerPanel transport={{}} userPresenceAvailable={false} />);

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("runs the content-free project and chat health check only when requested", async () => {
    const getAgentHardening = vi.fn().mockResolvedValue(cleanHardeningSnapshot);
    render(
      <AgentControllerPanel
        transport={{
          getAgentOrchestration: vi.fn().mockResolvedValue(
            exampleAgentOrchestrationManifest(),
          ),
          getAgentHardening,
        }}
        userPresenceAvailable={false}
      />,
    );

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(getAgentHardening).not.toHaveBeenCalled();
    expect(screen.getByText(/never reads or returns names/)).toBeInTheDocument();
    const health = screen.getByRole("region", { name: "Projects & chats health" });
    expect(health).toHaveAttribute("aria-busy", "false");
    expect(screen.getByText("Project and chat health has not been checked.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run health check" }));

    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Saved histories")).toBeInTheDocument();
    expect(screen.getByText("Catalog: ready · schema 30 · 0 projection issues")).toBeInTheDocument();
    expect(screen.getByText("Project and chat health check complete: Healthy. 0 safe actions reported.")).toBeInTheDocument();
    expect(getAgentHardening).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("SYNTHETIC_PRIVATE_PROMPT_CANARY")).not.toBeInTheDocument();
  });

  it("explains migration inconsistency without exposing database detail", async () => {
    const getAgentHardening = vi.fn().mockResolvedValue({
      ...cleanHardeningSnapshot,
      recovery_state: "unknown",
      recovery_actions: [],
      catalog: {
        state: "unavailable",
        reason_code: "catalog_migration_invalid",
        schema_version: null,
        quick_check_passed: null,
        foreign_key_violations_observed: null,
        foreign_key_scan_truncated: false,
        projection_violations: null,
        counts: null,
      },
    } satisfies AgentHardeningSnapshot);
    render(
      <AgentControllerPanel
        transport={{
          getAgentOrchestration: vi.fn().mockResolvedValue(
            exampleAgentOrchestrationManifest(),
          ),
          getAgentHardening,
        }}
        userPresenceAvailable={false}
      />,
    );

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run health check" }));

    expect(await screen.findByText(
      "The local catalog migration history is inconsistent. No data was changed.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/checksum mismatch/u)).not.toBeInTheDocument();
  });

  it("announces checking and keeps catalog facts useful when live state is unavailable", async () => {
    let resolveHealth!: (value: AgentHardeningSnapshot) => void;
    const getAgentHardening = vi.fn(() => new Promise<AgentHardeningSnapshot>((resolve) => {
      resolveHealth = resolve;
    }));
    render(
      <AgentControllerPanel
        transport={{
          getAgentOrchestration: vi.fn().mockResolvedValue(
            exampleAgentOrchestrationManifest(),
          ),
          getAgentHardening,
        }}
        userPresenceAvailable={false}
      />,
    );

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    const health = screen.getByRole("region", { name: "Projects & chats health" });
    fireEvent.click(screen.getByRole("button", { name: "Run health check" }));

    expect(health).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Checking project and chat health.")).toBeInTheDocument();

    resolveHealth({
      ...cleanHardeningSnapshot,
      recovery_state: "attention_required",
      recovery_actions: ["verify_live_state"],
      live: {
        state: "unavailable",
        reason_code: "live_state_unavailable",
        counts: null,
      },
    });

    expect(await screen.findByText("Review needed")).toBeInTheDocument();
    expect(health).toHaveAttribute("aria-busy", "false");
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Live cleanup state could not be verified.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Next safe actions" })).toHaveTextContent(
      "Retry the live Agent state check.",
    );
    expect(screen.getByText("Project and chat health check complete: Review needed. 1 safe action reported.")).toBeInTheDocument();
  });
});
