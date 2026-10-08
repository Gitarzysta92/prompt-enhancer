import { describe, expect, it, vi } from "vitest";

import { createHttpTransport, TransportError } from "./httpTransport";
import { syntheticMcpRegistryServerReview } from "./mcpRegistryServerReview.test-support";

const AUTH = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: false,
  user_presence_confirmation_mode: "unavailable",
};

function catalog(search = "files") {
  return {
    contract_version: "mcp-registry-catalog.v1",
    source: {
      registry: "official_mcp_registry",
      base_url: "https://registry.modelcontextprotocol.io",
      fetched_at: "2026-08-29T12:00:00Z",
      delivery: "live",
      cache_age_seconds: 0,
    },
    search,
    servers: [],
    next_cursor: null,
    partial: false,
    management_truth: "registry_only_no_install_authority",
  };
}

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store, private",
      Pragma: "no-cache",
    },
  });
}

describe("MCP Registry HTTP transport", () => {
  it("encodes search and cursor and parses the strict response", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH))
      .mockResolvedValueOnce(jsonResponse(catalog("file tools")));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listMcpRegistryCatalog?.({
      search: "file tools",
      cursor: "com.example/server:1.0.0",
      limit: 12,
    })).resolves.toMatchObject({ search: "file tools", servers: [] });
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/v1/integrations/mcp-store/catalog?search=file+tools&cursor=com.example%2Fserver%3A1.0.0&limit=12");
    expect(init).toMatchObject({ method: "GET", redirect: "error", referrerPolicy: "no-referrer" });
  });

  it("rejects a response that adds installation authority", async () => {
    const invalid = { ...catalog(), install_command: "synthetic-command" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH))
      .mockResolvedValueOnce(jsonResponse(invalid));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.listMcpRegistryCatalog?.()).rejects.toBeInstanceOf(TransportError);
  });

  it("rejects invalid queries before browser-session or catalog network use", async () => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.listMcpRegistryCatalog?.({ limit: 49 })).rejects.toBeInstanceOf(TransportError);
    await expect(transport.listMcpRegistryCatalog?.({ search: "x".repeat(101) })).rejects.toBeInstanceOf(TransportError);
    await expect(transport.listMcpRegistryCatalog?.({ cursor: " bad" })).rejects.toBeInstanceOf(TransportError);
    await expect(transport.listMcpRegistryCatalog?.({ search: "files\u202e" })).rejects.toBeInstanceOf(TransportError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a response bound to a different normalized search", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH))
      .mockResolvedValueOnce(jsonResponse(catalog("other")));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.listMcpRegistryCatalog?.({ search: "files" })).rejects.toBeInstanceOf(TransportError);
  });

  it("loads an exact server review through a bounded read-only GET", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH))
      .mockResolvedValueOnce(jsonResponse(syntheticMcpRegistryServerReview()));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getMcpRegistryServerReview?.({
      catalog_id: "a".repeat(32),
      name: "com.example/synthetic-files",
      presentation_revision: "f".repeat(64),
      version: "1.2.3",
    })).resolves.toMatchObject({
      install_action: "unavailable",
      review_truth: "preview_only_no_install_or_connection_authority",
    });
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe(
      `/v1/integrations/mcp-store/servers/${"a".repeat(32)}/review?name=com.example%2Fsynthetic-files&version=1.2.3&presentation_revision=${"f".repeat(64)}`,
    );
    expect(init).toMatchObject({ method: "GET", redirect: "error", referrerPolicy: "no-referrer" });
  });

  it("rejects a review whose presentation revision differs from the selected card", async () => {
    const changed = syntheticMcpRegistryServerReview();
    changed.server.presentation_revision = "e".repeat(64);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH))
      .mockResolvedValueOnce(jsonResponse(changed));
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getMcpRegistryServerReview?.({
      catalog_id: "a".repeat(32),
      name: "com.example/synthetic-files",
      presentation_revision: "f".repeat(64),
      version: "1.2.3",
    })).rejects.toBeInstanceOf(TransportError);
  });

  it("rejects invalid review identity before browser-session or registry network use", async () => {
    const fetchMock = vi.fn();
    const transport = createHttpTransport({
      fetch: fetchMock as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.getMcpRegistryServerReview?.({
      catalog_id: "bad",
      name: "com.example/synthetic-files",
      presentation_revision: "f".repeat(64),
      version: "1.2.3",
    })).rejects.toBeInstanceOf(TransportError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
