import { describe, expect, it, vi } from "vitest";

import {
  AGENT_MCP_CORE_TOOL_NAMES,
  runAgentMcpEndpointSelfTest,
} from "./agentMcpEndpointSelfTest";

const ORIGIN = "http://127.0.0.1:8765";
const ENDPOINT = `${ORIGIN}/mcp/agent`;
const TOKEN = `pemcp2.${"a".repeat(32)}.1.${"B".repeat(43)}`;
const INSTRUCTIONS = [
  "Start with agent_discover; agent_open, agent_context, agent_turn, agent_wait, agent_stop.",
  "Read: agent_workspace, agent_artifacts.",
  "agent_propose/agent_propose_transaction; agent_propose_lifecycle.",
  "native review; verified receipt; verified output artifact; agent_control.",
  "egress receipt; agent_runtime is opt-in; agent_close retains history.",
].join(" ");

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: {
      "Cache-Control": "no-store, private",
      "Content-Type": "application/json",
      "MCP-Protocol-Version": "2025-06-18",
    },
  });
}

function notificationResponse(): Response {
  return new Response(null, {
    status: 202,
    headers: {
      "Cache-Control": "no-store, private",
      "MCP-Protocol-Version": "2025-06-18",
    },
  });
}

function initializeResponse(): Response {
  return jsonResponse({
    jsonrpc: "2.0",
    id: "self-test-initialize",
    result: {
      protocolVersion: "2025-06-18",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "prompt-enhancer-agent", version: "synthetic" },
      instructions: INSTRUCTIONS,
    },
  });
}

function toolListResponse(names: readonly string[]): Response {
  return jsonResponse({
    jsonrpc: "2.0",
    id: "self-test-tools",
    result: {
      tools: names.map((name) => ({
        name,
        description: `Synthetic ${name}`,
        inputSchema: { type: "object" },
      })),
    },
  });
}

function discoveryResponse(): Response {
  return jsonResponse({
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
  });
}

function successfulFetch(names: readonly string[]) {
  return vi.fn()
    .mockResolvedValueOnce(initializeResponse())
    .mockResolvedValueOnce(notificationResponse())
    .mockResolvedValueOnce(toolListResponse(names))
    .mockResolvedValueOnce(discoveryResponse());
}

describe("Agent MCP endpoint self-test", () => {
  it("proves the exact core handshake without returning or storing the bearer", async () => {
    const fetchImpl = successfulFetch(AGENT_MCP_CORE_TOOL_NAMES);
    const result = await runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result).toEqual({
      contractVersion: "agent-mcp-endpoint-self-test.v1",
      coreToolCount: 19,
      discoveryContractVersion: "local-agent-orchestration.v22",
      modelLifecycleAdvertised: false,
      protocolVersion: "2025-06-18",
      serverName: "prompt-enhancer-agent",
      startsModel: false,
      startsProcess: false,
      startsTerminal: false,
    });
    expect(JSON.stringify(result)).not.toContain(TOKEN);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    for (const [url, init] of fetchImpl.mock.calls) {
      expect(url).toBe(ENDPOINT);
      expect(init.credentials).toBe("omit");
      expect(init.redirect).toBe("error");
      expect(init.referrerPolicy).toBe("no-referrer");
      expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
      expect(init.headers["X-Prompt-Enhancer-MCP-Probe"])
        .toBe("native-endpoint-self-test.v1");
    }
    expect(JSON.parse(String(fetchImpl.mock.calls[3][1].body))).toEqual({
      jsonrpc: "2.0",
      id: "self-test-discover",
      method: "tools/call",
      params: { name: "agent_discover", arguments: { refresh: false } },
    });
  });

  it("requires the lifecycle tool exactly when the scoped connection permits it", async () => {
    const fetchImpl = successfulFetch([...AGENT_MCP_CORE_TOOL_NAMES, "agent_runtime"]);
    const result = await runAgentMcpEndpointSelfTest({
      allowModelLifecycle: true,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result.modelLifecycleAdvertised).toBe(true);
    expect(result.coreToolCount).toBe(19);
  });

  it.each([
    "https://127.0.0.1:8765/mcp/agent",
    "http://example.test/mcp/agent",
    `http://synthetic-user${String.fromCharCode(64)}127.0.0.1:8765/mcp/agent`,
    "http://127.0.0.1:8765/mcp/agent?token=ignored",
    "http://127.0.0.1:8765/another-path",
  ])("refuses an unsafe endpoint before sending the credential: %s", async (endpointUrl) => {
    const fetchImpl = vi.fn();
    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({ code: "endpoint_invalid" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a different loopback origin before sending the credential", async () => {
    const fetchImpl = vi.fn();
    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: "http://127.0.0.1:9999",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({
      code: "endpoint_origin_mismatch",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("fails closed when the advertised tool surface is incomplete", async () => {
    const fetchImpl = successfulFetch(AGENT_MCP_CORE_TOOL_NAMES.slice(0, -1));
    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({
      code: "tool_surface_invalid",
    });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it.each([
    undefined,
    "Synthetic guidance without the required orchestration sequence.",
    `${INSTRUCTIONS}${"x".repeat(513)}`,
  ])("fails closed when initialize guidance is missing or incomplete", async (instructions) => {
    const initialized = initializeResponse();
    const payload = await initialized.json() as {
      result: { instructions?: string };
    };
    payload.result.instructions = instructions;
    const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse(payload));

    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({ code: "instructions_invalid" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects a response that omits the negotiated protocol header", async () => {
    const malformed = new Response(JSON.stringify({
      jsonrpc: "2.0",
      id: "self-test-initialize",
      result: {
        protocolVersion: "2025-06-18",
        serverInfo: { name: "prompt-enhancer-agent", version: "synthetic" },
        instructions: INSTRUCTIONS,
      },
    }), {
      status: 200,
      headers: {
        "Cache-Control": "no-store, private",
        "Content-Type": "application/json",
      },
    });
    const fetchImpl = vi.fn().mockResolvedValueOnce(malformed);

    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({ code: "protocol_invalid" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("classifies rejected scoped authority without reading an error body", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: "synthetic private detail" }),
      { status: 401 },
    ));

    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({ code: "credential_rejected" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("aborts a stalled endpoint within the caller-selected test bound", async () => {
    const fetchImpl = vi.fn((_url: URL | RequestInfo, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Synthetic abort", "AbortError"));
        }, { once: true });
      })
    ));

    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 5,
    })).rejects.toMatchObject({ code: "request_failed" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("fails closed when discovery does not return the exact contracts", async () => {
    const fetchImpl = successfulFetch(AGENT_MCP_CORE_TOOL_NAMES);
    fetchImpl.mockReset()
      .mockResolvedValueOnce(initializeResponse())
      .mockResolvedValueOnce(notificationResponse())
      .mockResolvedValueOnce(toolListResponse(AGENT_MCP_CORE_TOOL_NAMES))
      .mockResolvedValueOnce(jsonResponse({
        jsonrpc: "2.0",
        id: "self-test-discover",
        result: { isError: true, structuredContent: { error: "synthetic_failure" } },
      }));

    await expect(runAgentMcpEndpointSelfTest({
      allowModelLifecycle: false,
      bearerToken: TOKEN,
      endpointUrl: ENDPOINT,
      expectedOrigin: ORIGIN,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    })).rejects.toMatchObject({
      code: "discovery_invalid",
    });
  });
});
