import { describe, expect, it } from "vitest";

import {
  AgentMcpConnectionPayloadError,
  parseAgentControllerOwnership,
  parseAgentControllerOwnershipReleaseReceipt,
  parseAgentMcpClientSetup,
  parseAgentMcpConnection,
  parseAgentMcpConnectionCredential,
  parseAgentMcpConnectionList,
} from "./agentMcpConnectionContract";

const CONNECTION_ID = "a".repeat(32);
const PROJECT_ID = "b".repeat(32);
const SESSION_ID = "c".repeat(32);
const TOKEN = `pemcp2.${CONNECTION_ID}.1.${"A".repeat(43)}`;
const ENDPOINT = "http://127.0.0.1:8765/mcp/agent";
const TOKEN_ENV = "PROMPT_ENHANCER_AGENT_MCP_TOKEN";

function connection(overrides: Record<string, unknown> = {}) {
  return {
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
    ...overrides,
  };
}

function credential(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-mcp-connection.v4",
    connection: connection(),
    endpoint_url: ENDPOINT,
    bearer_token: TOKEN,
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
    idempotent_replay: false,
    secret_stored_by_server: false,
    starts_process: false,
    starts_terminal: false,
    ...overrides,
  };
}

function ownership(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-controller-ownership.v1",
    project_id: PROJECT_ID,
    project_name: "Synthetic project",
    session_id: SESSION_ID,
    session_title: "Synthetic controlled chat",
    owner_connection_id: CONNECTION_ID,
    owner_label: "Synthetic Codex connection",
    owner_client_kind: "codex",
    operation: "turn",
    state: "reconnecting",
    cursor: 4,
    last_seq: 5,
    approval_pending: false,
    ownership_started_at: "2026-08-28T12:00:00+00:00",
    owner_since: "2026-08-28T12:00:00+00:00",
    updated_at: "2026-08-28T12:01:00+00:00",
    revision: 2,
    handoff: null,
    native_approval_inherited: false,
    ...overrides,
  };
}

function ownershipList(values: unknown[] = []) {
  return {
    contract_version: "agent-controller-ownership-list.v1",
    ownerships: values,
    active_count: values.length,
  };
}

function connectionList(values: unknown[] = [connection()], activeCount = 1) {
  const typedValues = values as Array<Record<string, unknown>>;
  return {
    contract_version: "agent-mcp-management.v2",
    activity_epoch: "f".repeat(32),
    connections: values,
    active_count: activeCount,
    controller_ownerships: ownershipList(),
    tool_activity_sequences: typedValues.map((item) => ({
      contract_version: "agent-mcp-tool-activity-sequence.v1",
      connection_id: item.connection_id,
      credential_revision: item.credential_revision,
      sequence: 0,
      tool_name: null,
      tool_source: null,
      started_at: null,
      completed_at: null,
      outcome: null,
    })),
  };
}

function clientSetup(overrides: Record<string, unknown> = {}) {
  return {
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
    codex_add_command: `codex mcp add prompt-enhancer-agent --url ${ENDPOINT} --bearer-token-env-var ${TOKEN_ENV}`,
    claude_add_command: `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${${TOKEN_ENV}}' prompt-enhancer-agent ${ENDPOINT}`,
    credential_included: false,
    connection_authority_granted: false,
    native_connection_required: true,
    starts_process: false,
    starts_terminal: false,
    provider_configuration_changed: false,
    ...overrides,
  };
}

describe("Agent MCP connection contract", () => {
  it("accepts bounded metadata and a one-time private credential", () => {
    expect(parseAgentMcpConnection(connection())).toMatchObject({
      connection_id: CONNECTION_ID,
      state: "active",
    });
    expect(parseAgentMcpConnectionList(connectionList()).active_count).toBe(1);
    expect(parseAgentMcpConnectionList({
      ...connectionList(),
      tool_activity_sequences: [{
        contract_version: "agent-mcp-tool-activity-sequence.v1",
        connection_id: CONNECTION_ID,
        credential_revision: 1,
        sequence: 1,
        tool_name: "agent_turn",
        tool_source: "external_client",
        started_at: "2026-08-28T12:05:00+00:00",
        completed_at: null,
        outcome: null,
      }],
    }).tool_activity_sequences[0].completed_at).toBeNull();
    expect(parseAgentMcpConnectionCredential(credential())).toMatchObject({
      bearer_token: TOKEN,
      starts_process: false,
      starts_terminal: false,
    });
    expect(parseAgentMcpConnection(connection({
      state: "scope_missing",
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
    })).state).toBe("scope_missing");
  });

  it("accepts exact durable ownership, handoff, and release evidence", () => {
    const offered = ownership({
      handoff: {
        target_connection_id: "d".repeat(32),
        target_label: "Synthetic Claude recipient",
        target_client_kind: "claude",
        offered_at: "2026-08-28T12:01:00+00:00",
        expires_at: "2026-08-28T12:11:00+00:00",
      },
    });
    expect(parseAgentControllerOwnership(offered)).toMatchObject({
      session_id: SESSION_ID,
      state: "reconnecting",
      native_approval_inherited: false,
    });
    expect(parseAgentMcpConnectionList({
      ...connectionList(),
      controller_ownerships: ownershipList([offered]),
    }).controller_ownerships.active_count).toBe(1);
    expect(parseAgentControllerOwnershipReleaseReceipt({
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      released_connection_id: CONNECTION_ID,
      released_revision: 3,
      released_at: "2026-08-28T12:02:00+00:00",
      released_by: "native",
      session_settled: true,
      native_approval_inherited: false,
    })).toMatchObject({ released_by: "native", session_settled: true });
  });

  it("accepts only exact token-free, non-authorizing client setup previews", () => {
    expect(parseAgentMcpClientSetup(clientSetup())).toMatchObject({
      endpoint_url: ENDPOINT,
      credential_included: false,
      connection_authority_granted: false,
      starts_process: false,
      starts_terminal: false,
      provider_configuration_changed: false,
    });

    for (const payload of [
      clientSetup({ endpoint_url: "http://example.invalid/mcp/agent" }),
      clientSetup({ codex_add_command: "codex mcp add unsafe" }),
      clientSetup({ connection_authority_granted: true }),
      clientSetup({ provider_configuration_changed: true }),
      clientSetup({ extra: "rejected" }),
      clientSetup({ claude_json: `${clientSetup().claude_json}${TOKEN}` }),
    ]) {
      expect(() => parseAgentMcpClientSetup(payload)).toThrow(
        AgentMcpConnectionPayloadError,
      );
    }
  });

  it.each([
    connection({ state: "revoked", revoked_at: null }),
    connection({ extra: "rejected" }),
    connection({ connection_id: "../unsafe" }),
    connection({ updated_at: "not-a-time" }),
    connection({ last_tool_at: "2026-08-28T12:05:00+00:00", last_tool_name: null, last_tool_outcome: null }),
    connection({ last_used_at: null, last_tool_at: "2026-08-28T12:05:00+00:00", last_tool_name: "agent_open", last_tool_outcome: "succeeded", last_tool_source: "external_client" }),
    connection({ last_used_at: "2026-08-28T12:05:00+00:00", last_tool_at: "2026-08-28T12:05:00+00:00", last_tool_name: "unsafe/tool", last_tool_outcome: "succeeded", last_tool_source: "external_client" }),
    connection({ last_used_at: "2026-08-28T12:05:00+00:00", last_tool_at: "2026-08-28T12:05:00+00:00", last_tool_name: "agent_open", last_tool_outcome: "unknown", last_tool_source: "external_client" }),
    connection({ last_used_at: "2026-08-28T12:05:00+00:00", last_tool_at: "2026-08-28T12:05:00+00:00", last_tool_name: "agent_open", last_tool_outcome: "succeeded", last_tool_source: "untrusted" }),
    connection({ last_auth_rejected_at: "2026-08-27T12:00:00+00:00" }),
    connection({ scope: { ...(connection().scope as object), native_approval_inherited: true } }),
    connection({ scope: { ...(connection().scope as object), state: "missing" } }),
    connection({ state: "scope_missing" }),
  ])("rejects malformed connection metadata", (payload) => {
    expect(() => parseAgentMcpConnection(payload)).toThrow(
      AgentMcpConnectionPayloadError,
    );
  });

  it("rejects inconsistent counts and private values not bound to the endpoint and token environment", () => {
    expect(() => parseAgentMcpConnectionList(connectionList([connection()], 0)))
      .toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionCredential(credential({
      codex_toml: `url = "${ENDPOINT}"`,
    }))).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionCredential(credential({
      claude_json: JSON.stringify({
        mcpServers: {
          "prompt-enhancer-agent": {
            type: "http",
            url: ENDPOINT,
            headers: { Authorization: `Bearer ${TOKEN}` },
          },
        },
      }),
    }))).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionCredential(credential({
      endpoint_url: "http://example.com/mcp/agent",
    }))).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionCredential(credential({
      bearer_token: `pemcp2.${"c".repeat(32)}.1.${"A".repeat(43)}`,
    }))).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionCredential(credential({
      bearer_token: `pemcp2.${CONNECTION_ID}.2.${"A".repeat(43)}`,
    }))).toThrow(AgentMcpConnectionPayloadError);
  });

  it("requires one exact content-free activity cursor for every credential revision", () => {
    expect(() => parseAgentMcpConnectionList({
      ...connectionList(),
      activity_epoch: "not-an-epoch",
    })).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionList({
      ...connectionList(),
      tool_activity_sequences: [],
    })).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionList({
      ...connectionList(),
      tool_activity_sequences: [{
        contract_version: "agent-mcp-tool-activity-sequence.v1",
        connection_id: CONNECTION_ID,
        credential_revision: 2,
        sequence: 1,
        tool_name: "agent_discover",
        tool_source: "external_client",
        started_at: "2026-08-28T12:05:00+00:00",
        completed_at: null,
        outcome: null,
      }],
    })).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentMcpConnectionList({
      ...connectionList(),
      tool_activity_sequences: [{
        contract_version: "agent-mcp-tool-activity-sequence.v1",
        connection_id: CONNECTION_ID,
        credential_revision: 1,
        sequence: -1,
        tool_name: null,
        tool_source: null,
        started_at: null,
        completed_at: null,
        outcome: null,
      }],
    })).toThrow(AgentMcpConnectionPayloadError);
  });

  it.each([
    ownership({ extra: "rejected" }),
    ownership({ cursor: 6, last_seq: 5 }),
    ownership({ state: "waiting_native_approval", approval_pending: false }),
    ownership({ state: "running", approval_pending: true }),
    ownership({ state: "revoked", handoff: {
      target_connection_id: "d".repeat(32),
      target_label: "Synthetic recipient",
      target_client_kind: "claude",
      offered_at: "2026-08-28T12:01:00+00:00",
      expires_at: "2026-08-28T12:11:00+00:00",
    } }),
    ownership({ owner_since: "2026-08-28T12:02:00+00:00", updated_at: "2026-08-28T12:01:00+00:00" }),
    ownership({ native_approval_inherited: true }),
  ])("rejects malformed ownership evidence", (payload) => {
    expect(() => parseAgentControllerOwnership(payload)).toThrow(
      AgentMcpConnectionPayloadError,
    );
  });

  it("rejects duplicate ownership identities and unproven release receipts", () => {
    expect(() => parseAgentMcpConnectionList({
      ...connectionList(),
      controller_ownerships: ownershipList([ownership(), ownership()]),
    })).toThrow(AgentMcpConnectionPayloadError);
    expect(() => parseAgentControllerOwnershipReleaseReceipt({
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      released_connection_id: CONNECTION_ID,
      released_revision: 3,
      released_at: "2026-08-28T12:02:00+00:00",
      released_by: "native",
      session_settled: false,
      native_approval_inherited: false,
    })).toThrow(AgentMcpConnectionPayloadError);
  });
});
