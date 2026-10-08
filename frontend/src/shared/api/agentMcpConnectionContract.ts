import type {
  AgentControllerOwnership,
  AgentControllerOwnershipList,
  AgentControllerOwnershipReleaseReceipt,
  AgentMcpClientSetup,
  AgentMcpConnection,
  AgentMcpConnectionCredential,
  AgentMcpConnectionList,
  AgentMcpToolActivitySequence,
} from "./contracts";

export class AgentMcpConnectionPayloadError extends Error {
  constructor() {
    super("Agent MCP connection response was invalid");
    this.name = "AgentMcpConnectionPayloadError";
  }
}

const AGENT_MCP_BEARER_ENV = "PROMPT_ENHANCER_AGENT_MCP_TOKEN";

function expectedCodexConfig(endpointUrl: string): string {
  return [
    "[mcp_servers.prompt-enhancer-agent]",
    `url = ${JSON.stringify(endpointUrl)}`,
    `bearer_token_env_var = ${JSON.stringify(AGENT_MCP_BEARER_ENV)}`,
    "tool_timeout_sec = 330",
    'default_tools_approval_mode = "prompt"',
  ].join("\n");
}

function validClaudeConfig(value: string, endpointUrl: string): boolean {
  try {
    const root = record(JSON.parse(value));
    exactKeys(root, ["mcpServers"]);
    const servers = record(root.mcpServers);
    exactKeys(servers, ["prompt-enhancer-agent"]);
    const server = record(servers["prompt-enhancer-agent"]);
    exactKeys(server, ["type", "url", "headers"]);
    const headers = record(server.headers);
    exactKeys(headers, ["Authorization"]);
    return server.type === "http"
      && server.url === endpointUrl
      && headers.Authorization === `Bearer \${${AGENT_MCP_BEARER_ENV}}`;
  } catch {
    return false;
  }
}

function expectedCodexAddCommand(endpointUrl: string): string {
  return `codex mcp add prompt-enhancer-agent --url ${endpointUrl} --bearer-token-env-var ${AGENT_MCP_BEARER_ENV}`;
}

function expectedClaudeAddCommand(endpointUrl: string): string {
  return `claude mcp add --transport http --scope local --header 'Authorization: Bearer \${${AGENT_MCP_BEARER_ENV}}' prompt-enhancer-agent ${endpointUrl}`;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentMcpConnectionPayloadError();
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (
    actual.length !== required.length
    || actual.some((key, index) => key !== required[index])
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
}

function utcTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/u.test(value)
    && Number.isFinite(Date.parse(value));
}

function optionalUtcTimestamp(value: unknown): value is string | null {
  return value === null || utcTimestamp(value);
}

function identifier(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{32}$/u.test(value);
}

function boundedLabel(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.trim() === value
    && value.length >= 1
    && value.length <= maximum;
}

function endpoint(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 256) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:"
      && ["127.0.0.1", "localhost", "[::1]", "::1"].includes(parsed.hostname)
      && parsed.username === ""
      && parsed.password === ""
      && parsed.pathname === "/mcp/agent"
      && parsed.search === ""
      && parsed.hash === "";
  } catch {
    return false;
  }
}

function parseScope(value: unknown): AgentMcpConnection["scope"] {
  const scope = record(value);
  exactKeys(scope, [
    "contract_version",
    "state",
    "project_id",
    "project_name",
    "catalog_access",
    "chat_access",
    "workspace_access",
    "native_approval_inherited",
  ]);
  const bound = scope.state === "bound";
  const projectValid = typeof scope.project_id === "string"
    && /^[0-9a-f]{32}$/u.test(scope.project_id)
    && typeof scope.project_name === "string"
    && scope.project_name.length >= 1
    && scope.project_name.length <= 120;
  if (
    scope.contract_version !== "agent-mcp-scope.v1"
    || !["bound", "missing"].includes(String(scope.state))
    || (bound ? !projectValid : scope.project_id !== null || scope.project_name !== null)
    || scope.catalog_access !== (bound ? "project_only" : "none")
    || scope.chat_access !== (bound ? "project_only" : "none")
    || scope.workspace_access !== (bound ? "project_only" : "none")
    || scope.native_approval_inherited !== false
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return scope as unknown as AgentMcpConnection["scope"];
}

export function parseAgentMcpConnection(value: unknown): AgentMcpConnection {
  const item = record(value);
  exactKeys(item, [
    "contract_version",
    "connection_id",
    "label",
    "client_kind",
    "created_at",
    "updated_at",
    "expires_at",
    "last_used_at",
    "last_tool_at",
    "last_tool_name",
    "last_tool_outcome",
    "last_tool_source",
    "last_auth_rejected_at",
    "revoked_at",
    "revision",
    "credential_revision",
    "allow_model_lifecycle",
    "scope",
    "state",
  ]);
  const scope = parseScope(item.scope);
  if (
    item.contract_version !== "agent-mcp-connection.v4"
    || typeof item.connection_id !== "string"
    || !/^[0-9a-f]{32}$/u.test(item.connection_id)
    || typeof item.label !== "string"
    || item.label.trim() !== item.label
    || item.label.length < 1
    || item.label.length > 80
    || !["codex", "claude", "other"].includes(String(item.client_kind))
    || !utcTimestamp(item.created_at)
    || !utcTimestamp(item.updated_at)
    || !utcTimestamp(item.expires_at)
    || !optionalUtcTimestamp(item.last_used_at)
    || !optionalUtcTimestamp(item.last_tool_at)
    || !(item.last_tool_name === null || (
      typeof item.last_tool_name === "string"
      && /^(?:agent_[a-z][a-z0-9_]{0,47}|unknown_tool)$/u.test(item.last_tool_name)
    ))
    || !(item.last_tool_outcome === null || ["succeeded", "failed"].includes(String(item.last_tool_outcome)))
    || !(item.last_tool_source === null || ["external_client", "native_self_test"].includes(String(item.last_tool_source)))
    || !optionalUtcTimestamp(item.last_auth_rejected_at)
    || !optionalUtcTimestamp(item.revoked_at)
    || !Number.isSafeInteger(item.revision)
    || Number(item.revision) < 1
    || !Number.isSafeInteger(item.credential_revision)
    || Number(item.credential_revision) < 1
    || typeof item.allow_model_lifecycle !== "boolean"
    || !["active", "expired", "revoked", "scope_missing"].includes(String(item.state))
    || (item.state === "revoked") !== (item.revoked_at !== null)
    || (scope.state === "missing" && !["scope_missing", "revoked"].includes(String(item.state)))
    || (scope.state === "bound" && item.state === "scope_missing")
    || !([item.last_tool_at, item.last_tool_name, item.last_tool_outcome, item.last_tool_source]
      .every((entry) => entry === null)
      || [item.last_tool_at, item.last_tool_name, item.last_tool_outcome, item.last_tool_source]
        .every((entry) => entry !== null))
    || (item.last_tool_at !== null && item.last_used_at === null)
    || (item.last_auth_rejected_at !== null
      && Date.parse(String(item.last_auth_rejected_at)) < Date.parse(String(item.created_at)))
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return item as unknown as AgentMcpConnection;
}

function parseControllerHandoff(
  value: unknown,
): AgentControllerOwnership["handoff"] {
  if (value === null) return null;
  const handoff = record(value);
  exactKeys(handoff, [
    "target_connection_id",
    "target_label",
    "target_client_kind",
    "offered_at",
    "expires_at",
  ]);
  if (
    !identifier(handoff.target_connection_id)
    || !boundedLabel(handoff.target_label, 80)
    || !["codex", "claude", "other"].includes(String(handoff.target_client_kind))
    || !utcTimestamp(handoff.offered_at)
    || !utcTimestamp(handoff.expires_at)
    || Date.parse(handoff.expires_at) <= Date.parse(handoff.offered_at)
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return handoff as unknown as AgentControllerOwnership["handoff"];
}

export function parseAgentControllerOwnership(
  value: unknown,
): AgentControllerOwnership {
  const item = record(value);
  exactKeys(item, [
    "contract_version",
    "project_id",
    "project_name",
    "session_id",
    "session_title",
    "owner_connection_id",
    "owner_label",
    "owner_client_kind",
    "operation",
    "state",
    "cursor",
    "last_seq",
    "approval_pending",
    "ownership_started_at",
    "owner_since",
    "updated_at",
    "revision",
    "handoff",
    "native_approval_inherited",
  ]);
  const handoff = parseControllerHandoff(item.handoff);
  const state = String(item.state);
  const startedAt = typeof item.ownership_started_at === "string"
    ? Date.parse(item.ownership_started_at)
    : Number.NaN;
  const ownerSince = typeof item.owner_since === "string"
    ? Date.parse(item.owner_since)
    : Number.NaN;
  const updatedAt = typeof item.updated_at === "string"
    ? Date.parse(item.updated_at)
    : Number.NaN;
  if (
    item.contract_version !== "agent-controller-ownership.v1"
    || !identifier(item.project_id)
    || !boundedLabel(item.project_name, 120)
    || !identifier(item.session_id)
    || !boundedLabel(item.session_title, 120)
    || !identifier(item.owner_connection_id)
    || !boundedLabel(item.owner_label, 80)
    || !["codex", "claude", "other"].includes(String(item.owner_client_kind))
    || ![
      "turn",
      "write_proposal",
      "transaction_proposal",
      "lifecycle_proposal",
    ].includes(String(item.operation))
    || ![
      "claimed",
      "running",
      "waiting_native_approval",
      "reconnecting",
      "submission_uncertain",
      "stopping",
      "stop_uncertain",
      "cleanup_unconfirmed",
      "revoked",
    ].includes(state)
    || !Number.isSafeInteger(item.cursor)
    || Number(item.cursor) < 0
    || !Number.isSafeInteger(item.last_seq)
    || Number(item.last_seq) < Number(item.cursor)
    || typeof item.approval_pending !== "boolean"
    || !utcTimestamp(item.ownership_started_at)
    || !utcTimestamp(item.owner_since)
    || !utcTimestamp(item.updated_at)
    || startedAt > ownerSince
    || ownerSince > updatedAt
    || !Number.isSafeInteger(item.revision)
    || Number(item.revision) < 1
    || item.native_approval_inherited !== false
    || (state === "waiting_native_approval" && item.approval_pending !== true)
    || (["claimed", "running"].includes(state) && item.approval_pending !== false)
    || (state === "revoked" && handoff !== null)
    || (handoff !== null && (
      handoff.target_connection_id === item.owner_connection_id
      || Date.parse(handoff.offered_at) < ownerSince
    ))
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return { ...item, handoff } as unknown as AgentControllerOwnership;
}

export function parseAgentControllerOwnershipList(
  value: unknown,
): AgentControllerOwnershipList {
  const payload = record(value);
  exactKeys(payload, ["contract_version", "ownerships", "active_count"]);
  if (
    payload.contract_version !== "agent-controller-ownership-list.v1"
    || !Array.isArray(payload.ownerships)
    || payload.ownerships.length > 128
    || !Number.isSafeInteger(payload.active_count)
    || Number(payload.active_count) !== payload.ownerships.length
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  const ownerships = payload.ownerships.map(parseAgentControllerOwnership);
  if (new Set(ownerships.map((item) => item.session_id)).size !== ownerships.length) {
    throw new AgentMcpConnectionPayloadError();
  }
  return {
    contract_version: "agent-controller-ownership-list.v1",
    ownerships,
    active_count: Number(payload.active_count),
  };
}

export function parseAgentMcpConnectionList(value: unknown): AgentMcpConnectionList {
  const payload = record(value);
  exactKeys(payload, [
    "contract_version",
    "activity_epoch",
    "connections",
    "active_count",
    "controller_ownerships",
    "tool_activity_sequences",
  ]);
  if (
    payload.contract_version !== "agent-mcp-management.v2"
    || !identifier(payload.activity_epoch)
    || !Array.isArray(payload.connections)
    || payload.connections.length > 32
    || !Array.isArray(payload.tool_activity_sequences)
    || payload.tool_activity_sequences.length !== payload.connections.length
    || !Number.isSafeInteger(payload.active_count)
    || Number(payload.active_count) < 0
    || Number(payload.active_count) > 16
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  const connections = payload.connections.map(parseAgentMcpConnection);
  const controllerOwnerships = parseAgentControllerOwnershipList(
    payload.controller_ownerships,
  );
  const toolActivitySequences = payload.tool_activity_sequences.map((value) => {
    const cursor = record(value);
    exactKeys(cursor, [
      "contract_version",
      "connection_id",
      "credential_revision",
      "sequence",
      "tool_name",
      "tool_source",
      "started_at",
      "completed_at",
      "outcome",
    ]);
    const sequence = Number(cursor.sequence);
    const toolName = cursor.tool_name;
    const toolSource = cursor.tool_source;
    const startedAt = cursor.started_at;
    const completedAt = cursor.completed_at;
    const outcome = cursor.outcome;
    if (
      cursor.contract_version !== "agent-mcp-tool-activity-sequence.v1"
      || !identifier(cursor.connection_id)
      || !Number.isSafeInteger(cursor.credential_revision)
      || Number(cursor.credential_revision) < 1
      || !Number.isSafeInteger(cursor.sequence)
      || sequence < 0
      || !(toolName === null || (
        typeof toolName === "string"
        && /^(?:agent_[a-z][a-z0-9_]{0,47}|unknown_tool)$/u.test(toolName)
      ))
      || !(toolSource === null || ["external_client", "native_self_test"].includes(String(toolSource)))
      || !optionalUtcTimestamp(startedAt)
      || !optionalUtcTimestamp(completedAt)
      || !(outcome === null || ["succeeded", "failed"].includes(String(outcome)))
      || (sequence === 0 && [toolName, toolSource, startedAt, completedAt, outcome].some(
        (item) => item !== null,
      ))
      || (sequence > 0 && [toolName, toolSource, startedAt].some((item) => item === null))
      || ((completedAt === null) !== (outcome === null))
      || (completedAt !== null && startedAt !== null && Date.parse(completedAt) < Date.parse(startedAt))
    ) throw new AgentMcpConnectionPayloadError();
    return {
      contract_version: "agent-mcp-tool-activity-sequence.v1",
      connection_id: String(cursor.connection_id),
      credential_revision: Number(cursor.credential_revision),
      sequence,
      tool_name: toolName as string | null,
      tool_source: toolSource as AgentMcpToolActivitySequence["tool_source"],
      started_at: startedAt as string | null,
      completed_at: completedAt as string | null,
      outcome: outcome as AgentMcpToolActivitySequence["outcome"],
    } satisfies AgentMcpToolActivitySequence;
  });
  const expectedSequenceKeys = new Set(connections.map(
    (item) => `${item.connection_id}:${item.credential_revision}`,
  ));
  const actualSequenceKeys = toolActivitySequences.map(
    (item) => `${item.connection_id}:${item.credential_revision}`,
  );
  if (connections.filter((item) => item.state === "active").length !== payload.active_count) {
    throw new AgentMcpConnectionPayloadError();
  }
  if (
    new Set(actualSequenceKeys).size !== actualSequenceKeys.length
    || actualSequenceKeys.some((key) => !expectedSequenceKeys.has(key))
  ) throw new AgentMcpConnectionPayloadError();
  return {
    contract_version: "agent-mcp-management.v2",
    activity_epoch: String(payload.activity_epoch),
    connections,
    active_count: Number(payload.active_count),
    controller_ownerships: controllerOwnerships,
    tool_activity_sequences: toolActivitySequences,
  };
}

export function parseAgentControllerOwnershipReleaseReceipt(
  value: unknown,
): AgentControllerOwnershipReleaseReceipt {
  const receipt = record(value);
  exactKeys(receipt, [
    "contract_version",
    "project_id",
    "session_id",
    "released_connection_id",
    "released_revision",
    "released_at",
    "released_by",
    "session_settled",
    "native_approval_inherited",
  ]);
  if (
    receipt.contract_version !== "agent-controller-ownership.v1"
    || !identifier(receipt.project_id)
    || !identifier(receipt.session_id)
    || !identifier(receipt.released_connection_id)
    || !Number.isSafeInteger(receipt.released_revision)
    || Number(receipt.released_revision) < 1
    || !utcTimestamp(receipt.released_at)
    || !["owner", "native"].includes(String(receipt.released_by))
    || receipt.session_settled !== true
    || receipt.native_approval_inherited !== false
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return receipt as unknown as AgentControllerOwnershipReleaseReceipt;
}

export function parseAgentMcpConnectionCredential(
  value: unknown,
): AgentMcpConnectionCredential {
  const payload = record(value);
  exactKeys(payload, [
    "contract_version",
    "connection",
    "endpoint_url",
    "bearer_token",
    "codex_toml",
    "claude_json",
    "idempotent_replay",
    "secret_stored_by_server",
    "starts_process",
    "starts_terminal",
  ]);
  const connection = parseAgentMcpConnection(payload.connection);
  const endpointUrl = typeof payload.endpoint_url === "string" ? payload.endpoint_url : "";
  const bearerToken = typeof payload.bearer_token === "string" ? payload.bearer_token : "";
  const tokenMatch = /^pemcp2\.([0-9a-f]{32})\.([1-9][0-9]{0,8})\.([A-Za-z0-9_-]{43})$/u.exec(bearerToken);
  if (
    payload.contract_version !== "agent-mcp-connection.v4"
    || !endpoint(payload.endpoint_url)
    || tokenMatch === null
    || tokenMatch[1] !== connection.connection_id
    || Number(tokenMatch[2]) !== connection.credential_revision
    || typeof payload.codex_toml !== "string"
    || payload.codex_toml.length < 1
    || payload.codex_toml.length > 4096
    || typeof payload.claude_json !== "string"
    || payload.claude_json.length < 1
    || payload.claude_json.length > 4096
    || payload.codex_toml !== expectedCodexConfig(endpointUrl)
    || !validClaudeConfig(payload.claude_json, endpointUrl)
    || payload.codex_toml.includes(bearerToken)
    || payload.claude_json.includes(bearerToken)
    || typeof payload.idempotent_replay !== "boolean"
    || payload.secret_stored_by_server !== false
    || payload.starts_process !== false
    || payload.starts_terminal !== false
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return {
    contract_version: "agent-mcp-connection.v4",
    connection,
    endpoint_url: payload.endpoint_url,
    bearer_token: bearerToken,
    codex_toml: payload.codex_toml,
    claude_json: payload.claude_json,
    idempotent_replay: payload.idempotent_replay,
    secret_stored_by_server: false,
    starts_process: false,
    starts_terminal: false,
  };
}

export function parseAgentMcpClientSetup(value: unknown): AgentMcpClientSetup {
  const payload = record(value);
  exactKeys(payload, [
    "contract_version",
    "endpoint_url",
    "bearer_token_env_var",
    "codex_toml",
    "claude_json",
    "codex_add_command",
    "claude_add_command",
    "credential_included",
    "connection_authority_granted",
    "native_connection_required",
    "starts_process",
    "starts_terminal",
    "provider_configuration_changed",
  ]);
  const endpointUrl = typeof payload.endpoint_url === "string" ? payload.endpoint_url : "";
  const textFields = [
    payload.codex_toml,
    payload.claude_json,
    payload.codex_add_command,
    payload.claude_add_command,
  ];
  if (
    payload.contract_version !== "agent-mcp-client-setup.v1"
    || !endpoint(payload.endpoint_url)
    || payload.bearer_token_env_var !== AGENT_MCP_BEARER_ENV
    || typeof payload.codex_toml !== "string"
    || payload.codex_toml !== expectedCodexConfig(endpointUrl)
    || typeof payload.claude_json !== "string"
    || !validClaudeConfig(payload.claude_json, endpointUrl)
    || payload.codex_add_command !== expectedCodexAddCommand(endpointUrl)
    || payload.claude_add_command !== expectedClaudeAddCommand(endpointUrl)
    || textFields.some((field) => typeof field !== "string" || field.length < 1 || field.length > 4096)
    || textFields.some((field) => typeof field === "string" && /pemcp[12]\./u.test(field))
    || payload.credential_included !== false
    || payload.connection_authority_granted !== false
    || payload.native_connection_required !== true
    || payload.starts_process !== false
    || payload.starts_terminal !== false
    || payload.provider_configuration_changed !== false
  ) {
    throw new AgentMcpConnectionPayloadError();
  }
  return payload as unknown as AgentMcpClientSetup;
}
