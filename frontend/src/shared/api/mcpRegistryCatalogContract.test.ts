import { describe, expect, it } from "vitest";

import { McpRegistryCatalogPayloadError, parseMcpRegistryCatalog } from "./mcpRegistryCatalogContract";

function payload() {
  return {
    contract_version: "mcp-registry-catalog.v1",
    source: {
      registry: "official_mcp_registry",
      base_url: "https://registry.modelcontextprotocol.io",
      fetched_at: "2026-08-29T12:00:00Z",
      delivery: "live",
      cache_age_seconds: 0,
    },
    search: "files",
    servers: [{
      catalog_id: "a".repeat(32),
      presentation_revision: "f".repeat(64),
      name: "com.example/synthetic-files",
      title: "Synthetic Files",
      description: "Inspect fictional example files through MCP.",
      publisher: "com.example",
      version: "1.2.3",
      status: "active",
      updated_at: "2026-08-28T10:20:30Z",
      repository_url: "https://github.com/example/synthetic-files",
      website_url: "https://example.com/synthetic-files",
      icon: {
        path: `/v1/integrations/mcp-store/icons/${"b".repeat(32)}`,
        mime_type: "image/png",
      },
      packages: [{
        registry_type: "npm",
        identifier: "@example/synthetic-files",
        version: "1.2.3",
        transport: "stdio",
        runtime_hint: "npx",
        checksum_available: true,
      }],
      remotes: [{
        transport: "streamable-http",
        endpoint_host: "mcp.example.com",
        endpoint_state: "fixed_host",
        secure: true,
      }],
      supports_local: true,
      supports_remote: true,
      management_state: "not_managed",
      install_action: "unavailable",
      install_reason: "guarded_install_host_not_implemented",
    }],
    next_cursor: "com.example/synthetic-files:1.2.3",
    partial: false,
    management_truth: "registry_only_no_install_authority",
  };
}

describe("parseMcpRegistryCatalog", () => {
  it("accepts the exact discovery-only contract", () => {
    const result = parseMcpRegistryCatalog(payload());
    expect(result.source.delivery).toBe("live");
    expect(result.servers[0].packages[0].checksum_available).toBe(true);
    expect(result.servers[0].management_state).toBe("not_managed");
    expect(result.servers[0].install_action).toBe("unavailable");
  });

  it.each([
    ["extra top-level authority", (value: ReturnType<typeof payload>) => { Object.assign(value, { install: true }); }],
    ["remote icon URL", (value: ReturnType<typeof payload>) => { value.servers[0].icon = { path: "https://example.com/icon.png", mime_type: "image/png" }; }],
    ["malformed presentation revision", (value: ReturnType<typeof payload>) => { value.servers[0].presentation_revision = "bad"; }],
    ["bidirectional title control", (value: ReturnType<typeof payload>) => { value.servers[0].title = "Synthetic\u202eFiles"; }],
    ["non-NFC title", (value: ReturnType<typeof payload>) => { value.servers[0].title = "Cafe\u0301"; }],
    ["combining-mark flood", (value: ReturnType<typeof payload>) => { value.servers[0].description = `Synthetic${"\u0301".repeat(5)}`; }],
    ["non-HTTPS repository", (value: ReturnType<typeof payload>) => { value.servers[0].repository_url = "http://example.com/source"; }],
    ["invented managed state", (value: ReturnType<typeof payload>) => { value.servers[0].management_state = "installed"; }],
    ["incoherent local support", (value: ReturnType<typeof payload>) => { value.servers[0].supports_local = false; }],
    ["unexpected package argument", (value: ReturnType<typeof payload>) => { Object.assign(value.servers[0].packages[0], { arguments: ["--unsafe"] }); }],
  ])("rejects %s", (_label, mutate) => {
    const value = payload();
    mutate(value);
    expect(() => parseMcpRegistryCatalog(value)).toThrow(McpRegistryCatalogPayloadError);
  });

  it("rejects duplicate stable identities", () => {
    const value = payload();
    value.servers.push(structuredClone(value.servers[0]));
    expect(() => parseMcpRegistryCatalog(value)).toThrow(McpRegistryCatalogPayloadError);
  });
});
