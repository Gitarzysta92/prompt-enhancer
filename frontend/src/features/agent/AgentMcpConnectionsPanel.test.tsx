import { useCallback, useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentControllerOwnership,
  AgentMcpClientSetup,
  AgentMcpConnection,
  AgentMcpConnectionCredential,
  AgentMcpConnectionList,
} from "../../shared/api/contracts";
import { AGENT_MCP_CORE_TOOL_NAMES } from "../../shared/api/agentMcpEndpointSelfTest";
import {
  AGENT_ORCHESTRATION_STARTER,
  AgentMcpConnectionsPanel,
  agentMcpClientRegistrationCommand,
  agentMcpClientVerificationCommand,
} from "./AgentMcpConnectionsPanel";
import {
  observeExternalControllerAcceptance,
  type ExternalControllerAcceptanceRun,
} from "./externalControllerAcceptance";

const CONNECTION_ID = "a".repeat(32);
const PROJECT_ID = "b".repeat(32);
const SESSION_ID = "c".repeat(32);
const TOKEN = `pemcp2.${CONNECTION_ID}.1.${"A".repeat(43)}`;
const ENDPOINT = "http://127.0.0.1:8765/mcp/agent";
const TOKEN_ENV = "PROMPT_ENHANCER_AGENT_MCP_TOKEN";

const activeConnection: AgentMcpConnection = {
  contract_version: "agent-mcp-connection.v4",
  connection_id: CONNECTION_ID,
  label: "Synthetic Codex connection",
  client_kind: "codex",
  created_at: "2026-08-28T12:00:00+00:00",
  updated_at: "2026-08-28T12:00:00+00:00",
  expires_at: "2026-11-26T12:00:00+00:00",
  last_used_at: null,
  last_tool_at: null,
  last_tool_name: null,
  last_tool_outcome: null,
  last_tool_source: null,
  last_auth_rejected_at: null,
  revoked_at: null,
  revision: 1,
  credential_revision: 1,
  allow_model_lifecycle: false,
  scope: {
    contract_version: "agent-mcp-scope.v1",
    state: "bound",
    project_id: PROJECT_ID,
    project_name: "Synthetic project",
    catalog_access: "project_only",
    chat_access: "project_only",
    workspace_access: "project_only",
    native_approval_inherited: false,
  },
  state: "active",
};

const privateCredential: AgentMcpConnectionCredential = {
  contract_version: "agent-mcp-connection.v4",
  connection: activeConnection,
  endpoint_url: ENDPOINT,
  bearer_token: TOKEN,
  codex_toml: `url = "${ENDPOINT}"\nbearer_token_env_var = "${TOKEN_ENV}"`,
  claude_json: JSON.stringify({ url: ENDPOINT, Authorization: `Bearer \${${TOKEN_ENV}}` }),
  idempotent_replay: false,
  secret_stored_by_server: false,
  starts_process: false,
  starts_terminal: false,
};

const clientSetup: AgentMcpClientSetup = {
  contract_version: "agent-mcp-client-setup.v1",
  endpoint_url: ENDPOINT,
  bearer_token_env_var: TOKEN_ENV,
  codex_toml: [
    "[mcp_servers.prompt-enhancer-agent]",
    `url = "${ENDPOINT}"`,
    `bearer_token_env_var = "${TOKEN_ENV}"`,
    "tool_timeout_sec = 330",
    'default_tools_approval_mode = "prompt"',
  ].join("\n"),
  claude_json: JSON.stringify({
    mcpServers: {
      "prompt-enhancer-agent": {
        type: "http",
        url: ENDPOINT,
        headers: { Authorization: `Bearer \${${TOKEN_ENV}}` },
      },
    },
  }),
  codex_add_command: agentMcpClientRegistrationCommand("codex", ENDPOINT),
  claude_add_command: agentMcpClientRegistrationCommand("claude", ENDPOINT),
  credential_included: false,
  connection_authority_granted: false,
  native_connection_required: true,
  starts_process: false,
  starts_terminal: false,
  provider_configuration_changed: false,
};

function list(
  connections: AgentMcpConnection[] = [],
  ownerships: AgentControllerOwnership[] = [],
  sequences?: number[],
): AgentMcpConnectionList {
  return {
    contract_version: "agent-mcp-management.v2",
    activity_epoch: "f".repeat(32),
    connections,
    active_count: connections.filter((item) => item.state === "active").length,
    controller_ownerships: {
      contract_version: "agent-controller-ownership-list.v1",
      ownerships,
      active_count: ownerships.length,
    },
    tool_activity_sequences: connections.map((item, index) => {
      const sequence = sequences?.[index] ?? (item.last_tool_at === null ? 0 : 1);
      return {
      contract_version: "agent-mcp-tool-activity-sequence.v1",
      connection_id: item.connection_id,
      credential_revision: item.credential_revision,
      sequence,
      tool_name: sequence === 0 ? null : item.last_tool_name,
      tool_source: sequence === 0 ? null : item.last_tool_source,
      started_at: sequence === 0 ? null : item.last_tool_at,
      completed_at: sequence === 0 ? null : item.last_tool_at,
      outcome: sequence === 0 ? null : item.last_tool_outcome,
    };
    }),
  };
}

function selfTestJson(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: {
      "Cache-Control": "no-store, private",
      "Content-Type": "application/json",
      "MCP-Protocol-Version": "2025-06-18",
    },
  });
}

function endpointSelfTestFetch() {
  return vi.fn()
    .mockResolvedValueOnce(selfTestJson({
      jsonrpc: "2.0",
      id: "self-test-initialize",
      result: {
        protocolVersion: "2025-06-18",
        serverInfo: { name: "prompt-enhancer-agent", version: "synthetic" },
        instructions: [
          "Start with agent_discover; agent_open, agent_context, agent_turn, agent_wait, agent_stop.",
          "Read: agent_workspace, agent_artifacts.",
          "agent_propose/agent_propose_transaction; agent_propose_lifecycle.",
          "native review; verified receipt; verified output artifact; agent_control.",
          "egress receipt; agent_runtime is opt-in; agent_close retains history.",
        ].join(" "),
      },
    }))
    .mockResolvedValueOnce(new Response(null, {
      status: 202,
      headers: {
        "Cache-Control": "no-store, private",
        "MCP-Protocol-Version": "2025-06-18",
      },
    }))
    .mockResolvedValueOnce(selfTestJson({
      jsonrpc: "2.0",
      id: "self-test-tools",
      result: {
        tools: AGENT_MCP_CORE_TOOL_NAMES.map((name) => ({
          name,
          description: `Synthetic ${name}`,
          inputSchema: { type: "object" },
        })),
      },
    }))
    .mockResolvedValueOnce(selfTestJson({
      jsonrpc: "2.0",
      id: "self-test-discover",
      result: {
        isError: false,
        structuredContent: {
          contract_version: "prompt-enhancer-agent-mcp.v24",
          tool: "agent_discover",
          result: { contract_version: "local-agent-orchestration.v22" },
        },
      },
    }));
}

describe("AgentMcpConnectionsPanel", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("provides bounded read-only verification commands for both clients", () => {
    expect(agentMcpClientVerificationCommand("codex")).toBe(
      "codex mcp get prompt-enhancer-agent",
    );
    expect(agentMcpClientVerificationCommand("claude")).toBe(
      "claude mcp get prompt-enhancer-agent",
    );
    for (const client of ["codex", "claude"] as const) {
      const command = agentMcpClientVerificationCommand(client);
      expect(command).not.toContain(TOKEN);
      expect(command).not.toMatch(/[;&|]/u);
      expect(command).not.toMatch(/\b(add|remove|login|logout)\b/u);
    }
  });

  it("generates current token-free install commands for both clients", () => {
    expect(agentMcpClientRegistrationCommand("codex", ENDPOINT)).toBe(
      `codex mcp add prompt-enhancer-agent --url ${ENDPOINT} --bearer-token-env-var ${TOKEN_ENV}`,
    );
    expect(agentMcpClientRegistrationCommand("claude", ENDPOINT)).toBe(
      `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${${TOKEN_ENV}}' prompt-enhancer-agent ${ENDPOINT}`,
    );
    for (const client of ["codex", "claude"] as const) {
      const command = agentMcpClientRegistrationCommand(client, ENDPOINT);
      expect(command).not.toContain(TOKEN);
      expect(command).not.toContain("<paste");
    }
  });

  it("keeps native mutations disabled when owner-presence proof is unavailable", async () => {
    const createAgentMcpConnection = vi.fn();
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          getAgentMcpClientSetup: vi.fn().mockResolvedValue(clientSetup),
          listAgentMcpConnections: vi.fn().mockResolvedValue(list()),
          createAgentMcpConnection,
        }}
        userPresenceAvailable={false}
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeInTheDocument();
    const previewTitle = await screen.findByText("Exact client setup");
    const preview = previewTitle.closest("section");
    expect(preview).not.toBeNull();
    expect(within(preview!).getByText("Disconnected · no credential")).toBeVisible();
    expect(within(preview!).getByText(ENDPOINT)).toBeVisible();
    expect(within(preview!).getByText(/cannot authenticate, start a process/)).toBeVisible();
    expect(within(preview!).queryByText(TOKEN)).not.toBeInTheDocument();
    fireEvent.click(within(preview!).getByRole("button", { name: "Copy preview install command" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(clientSetup.codex_add_command);
    });
    fireEvent.click(within(preview!).getByRole("button", { name: "Claude Code" }));
    fireEvent.click(within(preview!).getByRole("button", { name: "Copy preview config" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(clientSetup.claude_json);
    });
    fireEvent.click(within(preview!).getByRole("button", { name: "Other MCP client" }));
    expect(within(preview!).getByText(/intentionally contains no token/)).toBeVisible();
    expect(within(preview!).queryByRole("button", { name: "Copy preview config" })).not.toBeInTheDocument();
    expect(screen.getByText(/Nineteen project-scoped tools cover the bound project/)).toBeVisible();
    expect(screen.getByText(/Live-close retains the durable chat/)).toBeVisible();
    expect(screen.getByText("POST /mcp/agent")).toBeVisible();
    fireEvent.click(screen.getByText("Connect an orchestrator and delegate one task"));
    expect(screen.getByText(/begin with/)).toHaveTextContent(
      "agent_discover → agent_open → agent_context",
    );
    expect(screen.getByText(/last-request timestamp proves/)).toBeVisible();
    expect(screen.getByText("preview_capture").closest("li")).toHaveTextContent(
      "path, type, size, and digest before adding it in the native Agent UI",
    );
    const outputGuidance = screen.getByText(/verified create\/edit receipt becomes a durable output card/);
    expect(outputGuidance).toHaveTextContent(
      "verified file move advances a matching card under the same identity",
    );
    expect(outputGuidance).toHaveTextContent(
      "Directory moves do not yet advance artifact cards",
    );
    expect(outputGuidance).toHaveTextContent(
      "Proposal content and approval data are not retained",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy orchestration starter" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        AGENT_ORCHESTRATION_STARTER,
      );
    });
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_open");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_turn");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_propose");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_propose_transaction");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_propose_lifecycle");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("agent_wait");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("durable artifact lineage");
    expect(AGENT_ORCHESTRATION_STARTER).toContain("proposal content and approval data do not");
    expect(AGENT_ORCHESTRATION_STARTER).not.toContain(TOKEN);
    expect(AGENT_ORCHESTRATION_STARTER).not.toMatch(/[A-Z]:\\/u);
    fireEvent.click(screen.getByText("Connected-agent tools · 19 project-scoped"));
    const advertisedTools = Array.from(
      document.querySelectorAll(".agent-mcp-connections__capabilities code"),
      (element) => element.textContent,
    );
    expect(advertisedTools).toEqual([
      "agent_discover", "agent_context",
      "agent_open", "agent_catalog", "agent_history", "agent_resume",
      "agent_fork", "agent_export", "agent_close",
      "agent_turn", "agent_stop", "agent_wait",
      "agent_control",
      "agent_workspace", "agent_propose", "agent_propose_transaction", "agent_propose_lifecycle", "agent_artifacts", "agent_stage_attachment",
    ]);
    expect(screen.getByText(/Export is exact-revision and path-free/)).toBeVisible();
    expect(screen.getByText(/artifacts return lineage or capture-candidate metadata rather than bytes/)).toBeVisible();
    expect(screen.getByText(/only the native Agent UI can complete a capture/)).toBeVisible();
    expect(screen.getByText(/session-and-turn-bound usage evidence/)).toBeVisible();
    expect(screen.getByText(/remain explicitly unmeasured until preflight/)).toBeVisible();
    expect(screen.getByText(/paths, standing instructions, process IDs/)).toBeVisible();
    expect(screen.queryByText(/Neither tool exports history/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create direct connection" })).toBeDisabled();
    expect(screen.getByText(/Open the owned native app window/)).toBeInTheDocument();
    expect(createAgentMcpConnection).not.toHaveBeenCalled();
  });

  it("creates a process-free connection and exposes secrets only to explicit copy actions", async () => {
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(list([activeConnection]));
    const createAgentMcpConnection = vi.fn().mockResolvedValue(privateCredential);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const { unmount } = render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{ listAgentMcpConnections, createAgentMcpConnection }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));

    expect(await screen.findByText("One-time private setup")).toBeInTheDocument();
    expect(createAgentMcpConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        label: "My coding agent",
        client_kind: "codex",
        project_id: PROJECT_ID,
        allow_model_lifecycle: false,
        expires_in_days: 90,
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
      }),
    );
    expect(document.body).not.toHaveTextContent(TOKEN);
    expect(document.body).not.toHaveTextContent(privateCredential.codex_toml);
    expect(screen.getAllByText(TOKEN_ENV)).toHaveLength(2);
    expect(screen.getByText(ENDPOINT)).toBeVisible();
    expect(screen.getByText("Schema checked")).toBeVisible();
    expect(screen.getByText(/No request observed/)).toBeVisible();
    expect(screen.getByText(/Not checked/)).toBeVisible();
    expect(screen.getByRole("tab", { name: "Codex" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Codex" })).toBeVisible();
    expect(storage).not.toHaveBeenCalled();

    const privateSetupSection = screen.getByText("One-time private setup").closest("section");
    expect(privateSetupSection).not.toBeNull();
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy Codex config" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        privateCredential.codex_toml,
      );
    });
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy install command" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        agentMcpClientRegistrationCommand("codex", ENDPOINT),
      );
    });
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy verify command" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        agentMcpClientVerificationCommand("codex"),
      );
    });
    fireEvent.click(within(privateSetupSection!).getByRole("tab", { name: "Claude Code" }));
    expect(screen.getByRole("tab", { name: "Claude Code" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Claude Code" })).toBeVisible();
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy install command" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        agentMcpClientRegistrationCommand("claude", ENDPOINT),
      );
    });
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy Claude Code config" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        privateCredential.claude_json,
      );
    });
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy endpoint" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(ENDPOINT);
    });
    fireEvent.click(within(privateSetupSection!).getByRole("button", { name: "Copy orchestration starter" }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        AGENT_ORCHESTRATION_STARTER,
      );
    });
    expect(document.body).not.toHaveTextContent(TOKEN);

    fireEvent.click(screen.getByRole("button", { name: "Clear private setup" }));
    expect(screen.queryByText("One-time private setup")).not.toBeInTheDocument();
    unmount();
    expect(document.body).not.toHaveTextContent(TOKEN);
    storage.mockRestore();
  });

  it("binds creation to the explicitly selected active project", async () => {
    const secondProjectId = "c".repeat(32);
    const listAgentProjects = vi.fn().mockResolvedValue({
      contract_version: "agent-catalog.v2",
      projects: [
        {
          contract_version: "agent-catalog.v2",
          project_id: PROJECT_ID,
          name: "Synthetic project A",
          created_at: "2026-08-28T12:00:00+00:00",
          updated_at: "2026-08-28T12:00:00+00:00",
          revision: 1,
          pinned: false,
          archived_at: null,
          session_count: 0,
          is_default: false,
        },
        {
          contract_version: "agent-catalog.v2",
          project_id: secondProjectId,
          name: "Synthetic project B",
          created_at: "2026-08-28T12:00:00+00:00",
          updated_at: "2026-08-28T12:00:00+00:00",
          revision: 1,
          pinned: false,
          archived_at: null,
          session_count: 0,
          is_default: false,
        },
      ],
    });
    const createAgentMcpConnection = vi.fn().mockResolvedValue(privateCredential);
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          createAgentMcpConnection,
          listAgentMcpConnections: vi.fn().mockResolvedValue(list()),
          listAgentProjects,
        }}
        userPresenceAvailable
      />,
    );

    const selector = await screen.findByLabelText("Project scope");
    expect(selector).toHaveValue(PROJECT_ID);
    fireEvent.change(selector, { target: { value: secondProjectId } });
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));

    await waitFor(() => expect(createAgentMcpConnection).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: secondProjectId }),
    ));
    expect(screen.getByText(/Native approvals are never inherited/)).toBeVisible();
    expect(listAgentProjects).toHaveBeenCalledWith(
      { includeArchived: false, limit: 200 },
      expect.any(AbortSignal),
    );
  });

  it("keeps an Other MCP client connection in a generic private setup instead of falling back to Codex", async () => {
    const otherConnection: AgentMcpConnection = {
      ...activeConnection,
      client_kind: "other",
      label: "Synthetic generic client",
    };
    const otherCredential: AgentMcpConnectionCredential = {
      ...privateCredential,
      connection: otherConnection,
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(list([otherConnection]));
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          createAgentMcpConnection: vi.fn().mockResolvedValue(otherCredential),
        }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "other" } });
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));

    const title = await screen.findByText("One-time private setup");
    const privateSetup = title.closest("section");
    expect(privateSetup).not.toBeNull();
    expect(within(privateSetup!).getByRole("tab", { name: "Other MCP client" }))
      .toHaveAttribute("aria-selected", "true");
    expect(within(privateSetup!).getByText("Register the Streamable HTTP server")).toBeVisible();
    expect(within(privateSetup!).getByText(/Do not put the token in/)).toHaveTextContent(
      "Do not put the token in the URL",
    );
    expect(within(privateSetup!).queryByRole("button", { name: "Copy install command" }))
      .not.toBeInTheDocument();
    expect(within(privateSetup!).queryByRole("button", { name: "Copy verify command" }))
      .not.toBeInTheDocument();
    fireEvent.click(within(privateSetup!).getByRole("button", { name: "Copy token" }));
    fireEvent.click(within(privateSetup!).getAllByRole("button", { name: "Copy endpoint" })[0]);
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(TOKEN);
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(ENDPOINT);
    });
    expect(document.body).not.toHaveTextContent(TOKEN);
  });

  it("defaults the guide to the chosen client and promotes live connection proof after refresh", async () => {
    const claudeConnection: AgentMcpConnection = {
      ...activeConnection,
      client_kind: "claude",
      label: "Synthetic Claude connection",
    };
    const claudeCredential: AgentMcpConnectionCredential = {
      ...privateCredential,
      connection: claudeConnection,
    };
    const observedConnection: AgentMcpConnection = {
      ...claudeConnection,
      last_used_at: "2026-08-28T12:05:00+00:00",
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(list([claudeConnection]))
      .mockResolvedValueOnce(list([observedConnection]));
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          createAgentMcpConnection: vi.fn().mockResolvedValue(claudeCredential),
        }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "claude" } });
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));

    expect(await screen.findByText("One-time private setup")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Claude Code" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText(/No request observed/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh connection status" }));
    expect(await screen.findByText(/Authenticated request observed/)).toBeVisible();
    expect(document.body).not.toHaveTextContent(TOKEN);
  });

  it("runs a bounded local MCP handshake without exposing the token or claiming an external client", async () => {
    const localEndpoint = `${window.location.origin}/mcp/agent`;
    const credential: AgentMcpConnectionCredential = {
      ...privateCredential,
      endpoint_url: localEndpoint,
      codex_toml: `url = "${localEndpoint}"\nbearer_token_env_var = "${TOKEN_ENV}"`,
      claude_json: JSON.stringify({
        url: localEndpoint,
        Authorization: `Bearer \${${TOKEN_ENV}}`,
      }),
    };
    const observedConnection: AgentMcpConnection = {
      ...activeConnection,
      last_used_at: "2026-08-28T12:05:00+00:00",
      last_tool_at: "2026-08-28T12:05:01+00:00",
      last_tool_name: "agent_discover",
      last_tool_outcome: "succeeded",
      last_tool_source: "native_self_test",
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(list([activeConnection]))
      .mockResolvedValueOnce(list([observedConnection]));
    const fetchImpl = endpointSelfTestFetch();
    vi.stubGlobal("fetch", fetchImpl);
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          createAgentMcpConnection: vi.fn().mockResolvedValue(credential),
        }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));
    expect(await screen.findByRole("button", { name: "Run local self-test" })).toBeVisible();
    expect(screen.getByText(/A pass does not prove/)).toHaveTextContent(
      "A pass does not prove that Codex is configured.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Run local self-test" }));
    expect(await screen.findByText(/Protocol 2025-06-18/)).toHaveTextContent(
      "19 core tools · model control absent",
    );
    expect(screen.getByText(/Handshake \+ workflow passed/)).toBeVisible();
    expect(screen.getByText(/Local endpoint self-test passed/)).toHaveTextContent(
      "not that an external Codex or Claude client connected",
    );
    expect(screen.getByText(/Authenticated request observed/)).toBeVisible();
    expect(screen.getByText(/Last tool/)).toHaveTextContent("agent_discover · succeeded");
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(document.body).not.toHaveTextContent(TOKEN);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("turns rejected self-test authority into content-free recovery guidance", async () => {
    const localEndpoint = `${window.location.origin}/mcp/agent`;
    const credential: AgentMcpConnectionCredential = {
      ...privateCredential,
      endpoint_url: localEndpoint,
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list())
      .mockResolvedValueOnce(list([activeConnection]));
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchImpl);
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          createAgentMcpConnection: vi.fn().mockResolvedValue(credential),
        }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("No direct connections yet.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Create direct connection" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run local self-test" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "If the connection is active, rotate it and update the client token",
    );
    expect(screen.getByText(/Local endpoint self-test failed closed/)).toHaveTextContent(
      "No model, process, terminal, project, chat, or workspace action was started",
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent(TOKEN);
  });

  it("rotates and revokes with the latest revision while never rendering credentials", async () => {
    const rotatedConnection = {
      ...activeConnection,
      revision: 2,
      credential_revision: 2,
    };
    const rotatedCredential = {
      ...privateCredential,
      connection: rotatedConnection,
      bearer_token: `pemcp2.${CONNECTION_ID}.2.${"B".repeat(43)}`,
    };
    rotatedCredential.codex_toml = `url = "${ENDPOINT}"\nbearer_token_env_var = "${TOKEN_ENV}"`;
    rotatedCredential.claude_json = JSON.stringify({ url: ENDPOINT, Authorization: `Bearer \${${TOKEN_ENV}}` });
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list([activeConnection]))
      .mockResolvedValueOnce(list([rotatedConnection]))
      .mockResolvedValueOnce(list([{ ...rotatedConnection, state: "revoked", revoked_at: "2026-08-29T12:00:00+00:00", revision: 3 }]));
    const rotateAgentMcpConnection = vi.fn().mockResolvedValue(rotatedCredential);
    const revokeAgentMcpConnection = vi.fn().mockResolvedValue({
      ...rotatedConnection,
      state: "revoked",
      revoked_at: "2026-08-29T12:00:00+00:00",
      revision: 3,
    });
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          rotateAgentMcpConnection,
          revokeAgentMcpConnection,
        }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("Synthetic Codex connection")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rotate" }));
    expect(await screen.findByText(/previous credential stopped working immediately/)).toBeInTheDocument();
    expect(rotateAgentMcpConnection).toHaveBeenCalledWith(
      CONNECTION_ID,
      expect.objectContaining({
        expected_revision: 1,
        expires_in_days: 90,
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
      }),
    );
    expect(document.body).not.toHaveTextContent(rotatedCredential.bearer_token);

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    expect(await screen.findByText(/credential no longer works/)).toBeInTheDocument();
    expect(revokeAgentMcpConnection).toHaveBeenCalledWith(
      CONNECTION_ID,
      { expected_revision: 2 },
    );
  });

  it("shows truthful never-used state and refreshes authenticated connection evidence", async () => {
    const usedConnection: AgentMcpConnection = {
      ...activeConnection,
      last_used_at: "2026-08-28T12:05:00+00:00",
      last_tool_at: "2026-08-28T12:05:01+00:00",
      last_tool_name: "agent_open",
      last_tool_outcome: "succeeded",
      last_tool_source: "external_client",
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list([activeConnection]))
      .mockResolvedValueOnce(list([usedConnection]));
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{ listAgentMcpConnections }}
        userPresenceAvailable
      />,
    );

    expect(await screen.findByText("Never connected · no authenticated MCP request observed"))
      .toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh connection status" }));
    expect(await screen.findByText(/Last MCP request/)).toBeVisible();
    const toolActivity = screen.getByText(/Last tool/);
    expect(within(toolActivity).getByText("agent_open")).toBeVisible();
    expect(toolActivity).toHaveTextContent("succeeded");
    expect(screen.queryByText(/Never connected/)).not.toBeInTheDocument();
    expect(listAgentMcpConnections).toHaveBeenCalledTimes(2);
  });

  it("renders durable owner and incoming handoff status and releases only through native proof", async () => {
    const targetConnection: AgentMcpConnection = {
      ...activeConnection,
      connection_id: "d".repeat(32),
      label: "Synthetic Claude recipient",
      client_kind: "claude",
    };
    const ownership: AgentControllerOwnership = {
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      project_name: "Synthetic project",
      session_id: "c".repeat(32),
      session_title: "Synthetic controlled chat",
      owner_connection_id: CONNECTION_ID,
      owner_label: activeConnection.label,
      owner_client_kind: "codex",
      operation: "turn",
      state: "reconnecting",
      cursor: 7,
      last_seq: 8,
      approval_pending: false,
      ownership_started_at: "2026-08-28T12:00:00+00:00",
      owner_since: "2026-08-28T12:00:00+00:00",
      updated_at: "2026-08-28T12:05:00+00:00",
      revision: 4,
      handoff: {
        target_connection_id: targetConnection.connection_id,
        target_label: targetConnection.label,
        target_client_kind: "claude",
        offered_at: "2026-08-28T12:05:00+00:00",
        expires_at: "2026-08-28T12:15:00+00:00",
      },
      native_approval_inherited: false,
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list([activeConnection, targetConnection], [ownership]))
      .mockResolvedValue(list([activeConnection, targetConnection]));
    const releaseAgentControllerOwnership = vi.fn().mockResolvedValue({
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      session_id: ownership.session_id,
      released_connection_id: CONNECTION_ID,
      released_revision: ownership.revision,
      released_at: "2026-08-28T12:06:00+00:00",
      released_by: "native",
      session_settled: true,
      native_approval_inherited: false,
    });
    const onAcceptanceEvidence = vi.fn();
    render(
      <AgentMcpConnectionsPanel
        onAcceptanceEvidence={onAcceptanceEvidence}
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections,
          releaseAgentControllerOwnership,
        }}
        userPresenceAvailable
      />,
    );

    const ownerCard = await screen.findByLabelText(
      "External control for Synthetic controlled chat",
    );
    expect(ownerCard).toHaveTextContent("Reconnect required");
    expect(ownerCard).toHaveTextContent("Observed cursor7 / 8");
    expect(ownerCard).toHaveTextContent("Do not resend the original message");
    expect(ownerCard).toHaveTextContent("Handoff offered to Synthetic Claude recipient");
    const incoming = screen.getByLabelText(
      "Incoming control handoff for Synthetic controlled chat",
    );
    expect(incoming).toHaveTextContent("Accept it from this exact external client");
    expect(incoming).toHaveTextContent("No pending native approval");

    fireEvent.click(within(ownerCard).getByRole("button", {
      name: "Release settled control",
    }));
    await waitFor(() => expect(releaseAgentControllerOwnership).toHaveBeenCalledWith({
      session_id: ownership.session_id,
      expected_revision: ownership.revision,
    }));
    expect(onAcceptanceEvidence).toHaveBeenCalledWith({
      kind: "native_release",
      receipt: expect.objectContaining({
        session_id: ownership.session_id,
        released_connection_id: CONNECTION_ID,
      }),
    });
    expect(await screen.findByText(/Released settled external control/)).toHaveTextContent(
      "No chat, history, or native authority was deleted",
    );
    await waitFor(() => expect(screen.queryByLabelText(
      "External control for Synthetic controlled chat",
    )).not.toBeInTheDocument());
  });

  it("guides a page-owned external lifecycle proof and ignores the local self-test", async () => {
    const localReceipt: AgentMcpConnection = {
      ...activeConnection,
      last_used_at: "2026-08-28T12:05:00+00:00",
      last_tool_at: "2026-08-28T12:05:01+00:00",
      last_tool_name: "agent_discover",
      last_tool_outcome: "succeeded",
      last_tool_source: "native_self_test",
    };
    const externalReceipt: AgentMcpConnection = {
      ...localReceipt,
      last_tool_at: "2026-08-28T12:05:02+00:00",
      last_tool_source: "external_client",
    };
    const listAgentMcpConnections = vi.fn()
      .mockResolvedValueOnce(list([activeConnection]))
      .mockResolvedValueOnce(list([localReceipt]))
      .mockResolvedValueOnce(list([externalReceipt], [], [2]));

    function Harness() {
      const [run, setRun] = useState<ExternalControllerAcceptanceRun | null>(null);
      const observeAcceptance = useCallback((catalog: AgentMcpConnectionList) => {
        setRun((current) => observeExternalControllerAcceptance(current, catalog));
      }, []);
      return (
        <AgentMcpConnectionsPanel
          acceptanceRun={run}
          onAcceptanceObservation={observeAcceptance}
          onAcceptanceRunChange={setRun}
          selectedProjectId={PROJECT_ID}
          selectedSessionId={SESSION_ID}
          transport={{ listAgentMcpConnections }}
          userPresenceAvailable
        />
      );
    }

    render(<Harness />);

    await screen.findByText("Synthetic Codex connection");
    fireEvent.click(screen.getByRole("button", { name: "Begin external lifecycle proof" }));
    expect(screen.getByText(/call only agent_discover/)).toBeVisible();
    expect(screen.getByRole("region", { name: /External controller lifecycle/ })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Refresh proof evidence" }));
    expect(await screen.findByText(/call only agent_discover/)).toBeVisible();
    expect(screen.getByText(/Last tool/)).toHaveTextContent("local self-test");

    fireEvent.click(screen.getByRole("button", { name: "Refresh proof evidence" }));
    expect(await screen.findByText(/call agent_catalog list_chats/)).toBeVisible();
    expect(screen.getByText("External client connected").closest("li")).toHaveAttribute("data-state", "passed");
    expect(screen.getByText("Exact project and chat discovered").closest("li")).toHaveAttribute("data-state", "waiting");
    expect(listAgentMcpConnections).toHaveBeenCalledTimes(3);
  });

  it("explains active failures and prepares inactive replacements without mutating authority", async () => {
    const expiredConnection: AgentMcpConnection = {
      ...activeConnection,
      connection_id: "b".repeat(32),
      label: "Expired synthetic client",
      client_kind: "claude",
      allow_model_lifecycle: true,
      state: "expired",
    };
    const revokedConnection: AgentMcpConnection = {
      ...activeConnection,
      connection_id: "c".repeat(32),
      label: "Revoked synthetic client",
      revoked_at: "2026-08-29T12:00:00+00:00",
      state: "revoked",
    };
    const failedConnection: AgentMcpConnection = {
      ...activeConnection,
      connection_id: "d".repeat(32),
      label: "Failed synthetic tool",
      last_used_at: "2026-08-28T12:05:00+00:00",
      last_tool_at: "2026-08-28T12:05:01+00:00",
      last_tool_name: "agent_open",
      last_tool_outcome: "failed",
      last_tool_source: "external_client",
    };
    const missingScopeConnection: AgentMcpConnection = {
      ...activeConnection,
      connection_id: "e".repeat(32),
      label: "Legacy unscoped client",
      scope: {
        contract_version: "agent-mcp-scope.v1",
        state: "missing",
        project_id: null,
        project_name: null,
        catalog_access: "none",
        chat_access: "none",
        workspace_access: "none",
        native_approval_inherited: false,
      },
      state: "scope_missing",
    };
    const createAgentMcpConnection = vi.fn();
    render(
      <AgentMcpConnectionsPanel
        selectedProjectId={PROJECT_ID}
        transport={{
          listAgentMcpConnections: vi.fn().mockResolvedValue(list([
            expiredConnection,
            revokedConnection,
            failedConnection,
            missingScopeConnection,
          ])),
          createAgentMcpConnection,
        }}
        userPresenceAvailable
      />,
    );

    const expiredCard = (await screen.findByText("Expired synthetic client")).closest("article");
    const revokedCard = screen.getByText("Revoked synthetic client").closest("article");
    const failedCard = screen.getByText("Failed synthetic tool").closest("article");
    const missingScopeCard = screen.getByText("Legacy unscoped client").closest("article");
    expect(expiredCard).not.toBeNull();
    expect(revokedCard).not.toBeNull();
    expect(failedCard).not.toBeNull();
    expect(missingScopeCard).not.toBeNull();
    expect(within(expiredCard!).getByText(/cannot be reactivated/)).toBeVisible();
    expect(within(revokedCard!).getByText(/rejected permanently/)).toBeVisible();
    expect(within(failedCard!).getByText(/last tool call failed/)).toHaveTextContent(
      "no task outcome is proven",
    );
    expect(within(missingScopeCard!).getByText(/has no usable scope/)).toHaveTextContent(
      "Revoke it, then prepare a replacement",
    );
    expect(within(missingScopeCard!).getByText(/Project scope missing/)).toHaveTextContent(
      "Native approvals never inherited",
    );

    fireEvent.click(within(expiredCard!).getByRole("button", { name: "Prepare replacement" }));
    expect(screen.getByLabelText("Connection name")).toHaveValue(
      "Expired synthetic client replacement",
    );
    expect(screen.getByLabelText("Connection name")).toHaveFocus();
    expect(screen.getByLabelText("Client")).toHaveValue("claude");
    expect(screen.getByLabelText(/Permit explicit model load/)).toBeChecked();
    expect(screen.getByText(/Replacement draft prepared/)).toHaveTextContent(
      "then create it through native confirmation",
    );
    expect(createAgentMcpConnection).not.toHaveBeenCalled();
  });
});
