const MCP_PROTOCOL_VERSION = "2025-06-18";
const AGENT_MCP_SERVER_NAME = "prompt-enhancer-agent";
const AGENT_MCP_ENDPOINT_PATH = "/mcp/agent";
const AGENT_MCP_CONTRACT_VERSION = "prompt-enhancer-agent-mcp.v24";
const AGENT_ORCHESTRATION_CONTRACT_VERSION = "local-agent-orchestration.v22";
const TOKEN_PATTERN = /^pemcp2\.[0-9a-f]{32}\.[1-9][0-9]{0,8}\.[A-Za-z0-9_-]{43}$/u;
const AGENT_MCP_SELF_TEST_HEADER = "X-Prompt-Enhancer-MCP-Probe";
const AGENT_MCP_SELF_TEST_HEADER_VALUE = "native-endpoint-self-test.v1";

export const AGENT_MCP_SELF_TEST_TIMEOUT_MS = 8_000;

export const AGENT_MCP_CORE_TOOL_NAMES = [
  "agent_discover",
  "agent_open",
  "agent_resume",
  "agent_fork",
  "agent_export",
  "agent_close",
  "agent_catalog",
  "agent_history",
  "agent_artifacts",
  "agent_stage_attachment",
  "agent_context",
  "agent_workspace",
  "agent_propose",
  "agent_propose_transaction",
  "agent_propose_lifecycle",
  "agent_turn",
  "agent_stop",
  "agent_wait",
  "agent_control",
] as const;

export type AgentMcpEndpointSelfTestFailure =
  | "endpoint_invalid"
  | "endpoint_origin_mismatch"
  | "credential_invalid"
  | "credential_rejected"
  | "request_failed"
  | "protocol_invalid"
  | "instructions_invalid"
  | "tool_surface_invalid"
  | "discovery_invalid";

export type AgentMcpEndpointSelfTestResult = {
  contractVersion: "agent-mcp-endpoint-self-test.v1";
  coreToolCount: number;
  discoveryContractVersion: "local-agent-orchestration.v22";
  modelLifecycleAdvertised: boolean;
  protocolVersion: "2025-06-18";
  serverName: "prompt-enhancer-agent";
  startsModel: false;
  startsProcess: false;
  startsTerminal: false;
};

export class AgentMcpEndpointSelfTestError extends Error {
  readonly code: AgentMcpEndpointSelfTestFailure;

  constructor(code: AgentMcpEndpointSelfTestFailure) {
    super("The local Agent MCP endpoint self-test failed");
    this.name = "AgentMcpEndpointSelfTestError";
    this.code = code;
  }
}

type RunOptions = {
  allowModelLifecycle: boolean;
  bearerToken: string;
  endpointUrl: string;
  expectedOrigin?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  timeoutMs?: number;
};

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(code: AgentMcpEndpointSelfTestFailure): never {
  throw new AgentMcpEndpointSelfTestError(code);
}

function boundedSignal(
  parent: AbortSignal | undefined,
  timeoutMs: number,
): { dispose: () => void; signal: AbortSignal } {
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30_000) {
    return fail("request_failed");
  }
  const controller = new AbortController();
  const relayAbort = () => controller.abort();
  if (parent?.aborted) {
    controller.abort();
  } else {
    parent?.addEventListener("abort", relayAbort, { once: true });
  }
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  return {
    dispose: () => {
      globalThis.clearTimeout(timeout);
      parent?.removeEventListener("abort", relayAbort);
    },
    signal: controller.signal,
  };
}

function endpoint(value: string, expectedOrigin: string): URL {
  let parsed: URL;
  let origin: URL;
  try {
    parsed = new URL(value);
    origin = new URL(expectedOrigin);
  } catch {
    return fail("endpoint_invalid");
  }
  const loopback = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
  if (
    parsed.protocol !== "http:"
    || !loopback.has(parsed.hostname.toLocaleLowerCase())
    || parsed.pathname !== AGENT_MCP_ENDPOINT_PATH
    || parsed.username !== ""
    || parsed.password !== ""
    || parsed.search !== ""
    || parsed.hash !== ""
  ) {
    return fail("endpoint_invalid");
  }
  if (parsed.origin !== origin.origin) return fail("endpoint_origin_mismatch");
  return parsed;
}

function successEnvelope(value: unknown, id: string): Record<string, unknown> {
  if (
    !record(value)
    || value.jsonrpc !== "2.0"
    || value.id !== id
    || !record(value.result)
    || "error" in value
  ) {
    return fail("protocol_invalid");
  }
  return value.result;
}

const REQUIRED_AGENT_MCP_INSTRUCTION_MARKERS = [
  "Start with agent_discover",
  "agent_open",
  "agent_context",
  "agent_turn",
  "agent_wait",
  "agent_stop",
  "agent_workspace",
  "agent_artifacts",
  "agent_propose",
  "agent_propose_transaction",
  "agent_propose_lifecycle",
  "native review",
  "verified receipt",
  "verified output artifact",
  "agent_control",
  "egress receipt",
  "agent_runtime is opt-in",
  "agent_close retains history",
] as const;

function validateServerInstructions(value: unknown): void {
  if (
    typeof value !== "string"
    || value.length === 0
    || value.length > 512
    || REQUIRED_AGENT_MCP_INSTRUCTION_MARKERS.some((marker) => !value.includes(marker))
  ) {
    return fail("instructions_invalid");
  }
}

async function jsonRequest(
  fetchImpl: typeof fetch,
  url: URL,
  bearerToken: string,
  body: Record<string, unknown>,
  signal: AbortSignal | undefined,
  includeProtocolHeader: boolean,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url.href, {
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      headers: {
        Accept: "application/json, text/event-stream",
        Authorization: `Bearer ${bearerToken}`,
        "Content-Type": "application/json",
        [AGENT_MCP_SELF_TEST_HEADER]: AGENT_MCP_SELF_TEST_HEADER_VALUE,
        ...(includeProtocolHeader ? { "MCP-Protocol-Version": MCP_PROTOCOL_VERSION } : {}),
      },
      method: "POST",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal,
    });
  } catch {
    return fail("request_failed");
  }
  const contentType = response.headers.get("content-type")?.split(";", 1)[0].trim().toLocaleLowerCase();
  const cacheControl = response.headers.get("cache-control")?.toLocaleLowerCase() ?? "";
  const responseProtocol = response.headers.get("mcp-protocol-version");
  if (response.status === 401 || response.status === 403) {
    return fail("credential_rejected");
  }
  if (
    response.status !== 200
    || response.redirected
    || contentType !== "application/json"
    || !cacheControl.includes("no-store")
    || responseProtocol !== MCP_PROTOCOL_VERSION
  ) {
    return fail("protocol_invalid");
  }
  try {
    return await response.json();
  } catch {
    return fail("protocol_invalid");
  }
}

async function initializedNotification(
  fetchImpl: typeof fetch,
  url: URL,
  bearerToken: string,
  signal: AbortSignal | undefined,
): Promise<void> {
  let response: Response;
  try {
    response = await fetchImpl(url.href, {
      body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
      cache: "no-store",
      credentials: "omit",
      headers: {
        Accept: "application/json, text/event-stream",
        Authorization: `Bearer ${bearerToken}`,
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        [AGENT_MCP_SELF_TEST_HEADER]: AGENT_MCP_SELF_TEST_HEADER_VALUE,
      },
      method: "POST",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal,
    });
  } catch {
    return fail("request_failed");
  }
  const cacheControl = response.headers.get("cache-control")?.toLocaleLowerCase() ?? "";
  const responseProtocol = response.headers.get("mcp-protocol-version");
  if (response.status === 401 || response.status === 403) {
    return fail("credential_rejected");
  }
  if (
    response.status !== 202
    || response.redirected
    || !cacheControl.includes("no-store")
    || responseProtocol !== MCP_PROTOCOL_VERSION
  ) {
    return fail("protocol_invalid");
  }
}

function validateToolSurface(value: unknown, allowModelLifecycle: boolean): void {
  const result = successEnvelope(value, "self-test-tools");
  if (!Array.isArray(result.tools)) return fail("tool_surface_invalid");
  const names = result.tools.map((item) => {
    if (
      !record(item)
      || typeof item.name !== "string"
      || typeof item.description !== "string"
      || !record(item.inputSchema)
    ) {
      return fail("tool_surface_invalid");
    }
    return item.name;
  });
  const expected = [
    ...AGENT_MCP_CORE_TOOL_NAMES,
    ...(allowModelLifecycle ? ["agent_runtime"] : []),
  ];
  if (
    names.length !== expected.length
    || new Set(names).size !== names.length
    || expected.some((name) => !names.includes(name))
  ) {
    return fail("tool_surface_invalid");
  }
}

function validateDiscovery(value: unknown): void {
  const result = successEnvelope(value, "self-test-discover");
  if (
    result.isError !== false
    || !record(result.structuredContent)
    || result.structuredContent.contract_version !== AGENT_MCP_CONTRACT_VERSION
    || result.structuredContent.tool !== "agent_discover"
    || !record(result.structuredContent.result)
    || result.structuredContent.result.contract_version !== AGENT_ORCHESTRATION_CONTRACT_VERSION
  ) {
    return fail("discovery_invalid");
  }
}

export async function runAgentMcpEndpointSelfTest({
  allowModelLifecycle,
  bearerToken,
  endpointUrl,
  expectedOrigin = globalThis.location?.origin ?? "",
  fetchImpl = globalThis.fetch,
  signal,
  timeoutMs = AGENT_MCP_SELF_TEST_TIMEOUT_MS,
}: RunOptions): Promise<AgentMcpEndpointSelfTestResult> {
  if (!TOKEN_PATTERN.test(bearerToken)) return fail("credential_invalid");
  if (!expectedOrigin || typeof fetchImpl !== "function") return fail("endpoint_invalid");
  const url = endpoint(endpointUrl, expectedOrigin);
  const bounded = boundedSignal(signal, timeoutMs);
  try {
    const initialized = await jsonRequest(
      fetchImpl,
      url,
      bearerToken,
      {
        jsonrpc: "2.0",
        id: "self-test-initialize",
        method: "initialize",
        params: {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: { name: "prompt-enhancer-native-self-test", version: "1" },
        },
      },
      bounded.signal,
      false,
    );
    const initializeResult = successEnvelope(initialized, "self-test-initialize");
    if (
      initializeResult.protocolVersion !== MCP_PROTOCOL_VERSION
      || !record(initializeResult.serverInfo)
      || initializeResult.serverInfo.name !== AGENT_MCP_SERVER_NAME
    ) {
      return fail("protocol_invalid");
    }
    validateServerInstructions(initializeResult.instructions);

    await initializedNotification(fetchImpl, url, bearerToken, bounded.signal);
    const tools = await jsonRequest(
      fetchImpl,
      url,
      bearerToken,
      { jsonrpc: "2.0", id: "self-test-tools", method: "tools/list" },
      bounded.signal,
      true,
    );
    validateToolSurface(tools, allowModelLifecycle);

    const discovery = await jsonRequest(
      fetchImpl,
      url,
      bearerToken,
      {
        jsonrpc: "2.0",
        id: "self-test-discover",
        method: "tools/call",
        params: { name: "agent_discover", arguments: { refresh: false } },
      },
      bounded.signal,
      true,
    );
    validateDiscovery(discovery);

    return {
      contractVersion: "agent-mcp-endpoint-self-test.v1",
      coreToolCount: AGENT_MCP_CORE_TOOL_NAMES.length,
      discoveryContractVersion: AGENT_ORCHESTRATION_CONTRACT_VERSION,
      modelLifecycleAdvertised: allowModelLifecycle,
      protocolVersion: MCP_PROTOCOL_VERSION,
      serverName: AGENT_MCP_SERVER_NAME,
      startsModel: false,
      startsProcess: false,
      startsTerminal: false,
    };
  } finally {
    bounded.dispose();
  }
}
