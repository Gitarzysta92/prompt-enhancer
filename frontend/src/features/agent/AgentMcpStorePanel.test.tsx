import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { McpRegistryCatalog, McpRegistryServerReview } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import {
  syntheticMcpManagedLifecyclePreview,
  syntheticMcpManagedLifecycleReceipt,
  syntheticMcpManagedLocalConfigurationInspection,
  syntheticMcpManagedLocalConfigurationInspectionPreview,
  syntheticMcpManagedLocalConfigurationInspectionReceipt,
  syntheticMcpManagedLocalLifecycleReceipt,
  syntheticMcpManagedLocalUninstallReceipt,
  syntheticMcpManagedLocalCleanupPreview,
  syntheticMcpManagedLocalCleanupReceipt,
  syntheticMcpManagedLocalOperationRecoveryPreview,
  syntheticMcpManagedLocalOperationRecoveryReceipt,
  syntheticMcpManagedLocalRollbackCleanupPreview,
  syntheticMcpManagedLocalRollbackCleanupReceipt,
  syntheticMcpManagedLocalRollbackPreview,
  syntheticMcpManagedLocalRollbackReceipt,
  syntheticMcpManagedLocalUpdatePreview,
  syntheticMcpManagedLocalUpdateReceipt,
  syntheticMcpManagedServer,
  syntheticMcpManagedServerList,
  syntheticMcpManagedProbeReceipt,
  syntheticMcpManagedServerReceipt,
  syntheticMcpManagedToolSnapshot,
} from "../../shared/api/mcpManagedServer.test-support";
import { syntheticMcpRegistryServerReview } from "../../shared/api/mcpRegistryServerReview.test-support";
import { AgentMcpStorePanel } from "./AgentMcpStorePanel";

function server(id: string, options: { local?: boolean; remote?: boolean } = {}) {
  const local = options.local ?? true;
  const remote = options.remote ?? true;
  return {
    catalog_id: id.repeat(32).slice(0, 32),
    presentation_revision: id.repeat(64).slice(0, 64),
    name: `com.example/synthetic-${id}`,
    title: `Synthetic ${id.toLocaleUpperCase()}`,
    description: `Fictional MCP server ${id}.`,
    publisher: "com.example",
    version: "1.0.0",
    status: "active" as const,
    updated_at: "2026-08-29T12:00:00Z",
    repository_url: `https://github.com/example/synthetic-${id}`,
    website_url: null,
    icon: id === "a" ? {
      path: `/v1/integrations/mcp-store/icons/${"a".repeat(32)}`,
      mime_type: "image/png" as const,
    } : null,
    packages: local ? [{
      registry_type: "npm",
      identifier: `@example/synthetic-${id}`,
      version: "1.0.0",
      transport: "stdio" as const,
      runtime_hint: "npx",
      checksum_available: true,
    }] : [],
    remotes: remote ? [{
      transport: "streamable-http" as const,
      endpoint_host: `${id}.example.com`,
      endpoint_state: "fixed_host" as const,
      secure: true,
    }] : [],
    supports_local: local,
    supports_remote: remote,
    management_state: "not_managed" as const,
    install_action: "unavailable" as const,
    install_reason: "guarded_install_host_not_implemented" as const,
  };
}

function catalog(servers = [server("a"), server("b", { local: false })], nextCursor: string | null = null): McpRegistryCatalog {
  return {
    contract_version: "mcp-registry-catalog.v1",
    source: {
      registry: "official_mcp_registry",
      base_url: "https://registry.modelcontextprotocol.io",
      fetched_at: "2026-08-29T12:00:00Z",
      delivery: "live",
      cache_age_seconds: 0,
    },
    search: "",
    servers,
    next_cursor: nextCursor,
    partial: false,
    management_truth: "registry_only_no_install_authority",
  };
}

function deferredCatalog() {
  let resolve!: (value: McpRegistryCatalog) => void;
  const promise = new Promise<McpRegistryCatalog>((next) => { resolve = next; });
  return { promise, resolve };
}

function pagedServer(index: number) {
  const identity = index.toString(16).padStart(32, "0");
  return {
    ...server("a"),
    catalog_id: identity,
    presentation_revision: index.toString(16).padStart(64, "0"),
    name: `com.example/synthetic-page-${index}`,
    title: `Synthetic page ${index}`,
    description: `Fictional paginated MCP server ${index}.`,
    repository_url: `https://github.com/example/synthetic-page-${index}`,
    icon: null,
  };
}

async function openManagedServers() {
  const managedTab = await screen.findByRole("tab", { name: "Managed servers" });
  fireEvent.click(managedTab);
  return screen.findByRole("region", { name: "Managed MCP servers" });
}

describe("AgentMcpStorePanel", () => {
  it("bounds the mounted catalog while preserving exact loaded-result navigation", async () => {
    const servers = Array.from({ length: 120 }, (_, index) => pagedServer(index));
    render(<AgentMcpStorePanel transport={{
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog(servers)),
    }} />);

    const region = await screen.findByRole("region", { name: "MCP Store" });
    expect(within(region).getAllByRole("article")).toHaveLength(48);
    expect(within(region).getByText("Showing 1–48 of 120")).toBeVisible();
    expect(within(region).getByText("Synthetic page 0")).toBeVisible();
    expect(within(region).queryByText("Synthetic page 48")).toBeNull();

    fireEvent.click(within(region).getByRole("button", { name: "Later" }));
    expect(within(region).getAllByRole("article")).toHaveLength(48);
    expect(within(region).getByText("Showing 49–96 of 120")).toBeVisible();
    expect(within(region).queryByText("Synthetic page 0")).toBeNull();
    expect(within(region).getByText("Synthetic page 48")).toBeVisible();
  });

  it("renders compact discovery cards with the narrow verified-package boundary", async () => {
    const listMcpRegistryCatalog = vi.fn().mockResolvedValue(catalog());
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);

    const region = await screen.findByRole("region", { name: "MCP Store" });
    expect(within(region).getByText("Official Registry · reviewed local management")).toBeVisible();
    expect(within(region).getByText("Synthetic A")).toBeVisible();
    expect(within(region).getByText("Synthetic B")).toBeVisible();
    expect(within(region).getByRole("tab", { name: "Browse servers" })).toHaveAttribute("aria-selected", "true");
    expect(within(region).getByRole("tab", { name: "Managed servers" })).toHaveAttribute("aria-selected", "false");
    expect(within(region).getByText("How review, installation and tool authority work")).toBeVisible();
    expect(within(region).queryByRole("region", { name: "Managed MCP servers" })).toBeNull();
    expect(within(region).queryByText("Package and connection details")).toBeNull();
    expect(within(region).getAllByText("Not managed")).toHaveLength(2);
    expect(within(region).getAllByRole("button", { name: /Review unavailable for Synthetic/u })).toHaveLength(2);
    within(region).getAllByRole("button", { name: /Review unavailable for Synthetic/u }).forEach((button) => {
      expect(button).toBeDisabled();
    });
    expect(region.querySelector(".agent-mcp-store__icon")).toHaveAttribute(
      "src",
      `/v1/integrations/mcp-store/icons/${"a".repeat(32)}`,
    );
    expect(within(region).getAllByText("Official Registry")).toHaveLength(2);
    expect(within(region).getByText("Registry logo declared")).toBeVisible();
    expect(within(region).getByText("Initials fallback")).toBeVisible();
    fireEvent.error(within(region).getByRole("img", { name: /Logo supplied through the local Official Registry image proxy/i }));
    expect(within(region).getByRole("img", { name: /Registry logo could not be displayed/i })).toBeVisible();
    expect(within(region).getAllByRole("img", { name: /Generated initials/i })).toHaveLength(2);
    expect(listMcpRegistryCatalog).toHaveBeenCalledWith(
      { search: "", cursor: undefined, limit: 24 },
      expect.any(AbortSignal),
    );
  });

  it("renders markup-like Registry metadata only as inert text", async () => {
    const hostile = {
      ...server("b"),
      title: "<img src=x onerror=synthetic>",
      description: "<script>synthetic()</script>",
    };
    render(<AgentMcpStorePanel transport={{
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog([hostile])),
    }} />);

    expect(await screen.findByText("<img src=x onerror=synthetic>")).toBeVisible();
    expect(screen.getByText("<script>synthetic()</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("img[src='x']")).toBeNull();
  });

  it("keeps discovery and managed lifecycle in separate keyboard-reachable workspaces", async () => {
    const managed = syntheticMcpManagedServer({
      installation_state: "installed",
      installation_kind: "local_package",
      lifecycle_state: "installed",
    });
    render(<AgentMcpStorePanel transport={{
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
    }} />);

    const browseTab = await screen.findByRole("tab", { name: "Browse servers" });
    const managedTab = screen.getByRole("tab", { name: "Managed servers" });
    expect(screen.getByLabelText("Search MCP servers")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Managed MCP servers" })).toBeNull();

    browseTab.focus();
    fireEvent.keyDown(browseTab, { key: "ArrowRight" });
    expect(managedTab).toHaveAttribute("aria-selected", "true");
    expect(managedTab).toHaveFocus();
    const managedRegion = await screen.findByRole("region", { name: "Managed MCP servers" });
    expect(within(managedRegion).getByText("Installed")).toBeVisible();
    expect(screen.queryByLabelText("Search MCP servers")).toBeNull();

    fireEvent.keyDown(managedTab, { key: "ArrowLeft" });
    expect(browseTab).toHaveAttribute("aria-selected", "true");
    expect(browseTab).toHaveFocus();
    expect(await screen.findByLabelText("Search MCP servers")).toBeVisible();
  });

  it("searches explicitly and filters the returned page locally", async () => {
    const listMcpRegistryCatalog = vi.fn().mockImplementation(async ({ search }: { search: string }) => ({
      ...catalog(),
      search,
    }));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic A");

    fireEvent.change(screen.getByLabelText("Search MCP servers"), { target: { value: "  fictional   files  " } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(listMcpRegistryCatalog).toHaveBeenLastCalledWith(
      { search: "fictional files", cursor: undefined, limit: 24 },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("Search: “fictional files”")).toBeVisible();

    fireEvent.click(screen.getByLabelText("Local packages"));
    expect(screen.getByText("Synthetic A")).toBeVisible();
    expect(screen.queryByText("Synthetic B")).toBeNull();
    fireEvent.click(screen.getByLabelText("Remote servers"));
    expect(screen.getByText("Synthetic A")).toBeVisible();
    expect(screen.getByText("Synthetic B")).toBeVisible();
  });

  it("sorts only loaded results and can put current managed lifecycle first", async () => {
    const alpha = server("a");
    const beta = server("b");
    const gamma = server("c");
    alpha.updated_at = "2026-08-27T12:00:00Z";
    beta.updated_at = "2026-08-29T12:00:00Z";
    gamma.updated_at = "2026-08-28T12:00:00Z";
    const managed = syntheticMcpManagedServer({
      catalog_id: beta.catalog_id,
      server_name: beta.name,
      server_title: beta.title,
      server_version: beta.version,
      installation_state: "installed",
      installation_kind: "local_package",
      lifecycle_state: "installed",
    });
    render(<AgentMcpStorePanel transport={{
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog([gamma, beta, alpha])),
    }} />);
    await screen.findByText("Synthetic C");

    const titles = () => screen.getAllByRole("article").map((article) => within(article).getByRole("strong").textContent);
    expect(titles()).toEqual(["Synthetic C", "Synthetic B", "Synthetic A"]);

    fireEvent.change(screen.getByLabelText("Sort loaded results"), { target: { value: "title" } });
    expect(titles()).toEqual(["Synthetic A", "Synthetic B", "Synthetic C"]);
    expect(screen.getByText("Sorted loaded results only")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Sort loaded results"), { target: { value: "updated" } });
    expect(titles()).toEqual(["Synthetic B", "Synthetic C", "Synthetic A"]);

    fireEvent.change(screen.getByLabelText("Sort loaded results"), { target: { value: "managed" } });
    expect(titles()[0]).toBe("Synthetic B");
    expect(within(screen.getAllByRole("article")[0]).getByText("Installed")).toBeVisible();
  });

  it("distinguishes search-empty and filter-empty states and gives direct recovery", async () => {
    const listMcpRegistryCatalog = vi.fn().mockImplementation(async ({ search }: { search: string }) => (
      search ? catalog([], null) : catalog([server("b", { local: false, remote: true })])
    ));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic B");

    fireEvent.change(screen.getByLabelText("Search MCP servers"), { target: { value: "missing example" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No Registry servers matched “missing example”.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(await screen.findByText("Synthetic B")).toBeVisible();

    fireEvent.click(screen.getByLabelText("Local packages"));
    expect(screen.getByText("No loaded servers match this distribution filter.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Show all distributions" }));
    expect(screen.getByText("Synthetic B")).toBeVisible();
    expect(screen.getByLabelText("All")).toBeChecked();
  });

  it("shows a bounded loading skeleton while the first catalog request is pending", async () => {
    const pending = deferredCatalog();
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog: vi.fn().mockReturnValue(pending.promise) }} />);

    expect(screen.getByText("Loading the official MCP Registry…")).toBeVisible();
    expect(document.querySelectorAll(".agent-mcp-store__skeleton")).toHaveLength(4);
    pending.resolve(catalog());
    expect(await screen.findByText("Synthetic A")).toBeVisible();
    expect(document.querySelector(".agent-mcp-store__skeleton")).toBeNull();
  });

  it("opens an exact read-only review and routes protected lifecycle through a managed plan", async () => {
    const selected = server("a");
    const payload = syntheticMcpRegistryServerReview();
    Object.assign(payload.server, selected);
    payload.provenance.publisher_namespace = selected.publisher;
    payload.versions[0].version = selected.version;
    const listMcpRegistryCatalog = vi.fn().mockResolvedValue(catalog([selected]));
    const getMcpRegistryServerReview = vi.fn().mockResolvedValue(
      payload as unknown as McpRegistryServerReview,
    );
    render(<AgentMcpStorePanel transport={{
      getMcpRegistryServerReview,
      listMcpRegistryCatalog,
    }} />);
    await screen.findByText("Synthetic A");

    fireEvent.click(screen.getByRole("button", { name: "Review Synthetic A" }));
    expect(await screen.findByRole("heading", { name: "Declared setup options" })).toBeVisible();
    expect(getMcpRegistryServerReview).toHaveBeenCalledWith({
      catalog_id: selected.catalog_id,
      name: selected.name,
      presentation_revision: selected.presentation_revision,
      version: selected.version,
    }, expect.any(AbortSignal));
    expect(screen.getByText("Preview only. This review cannot install or run code, connect an endpoint, collect a credential, or edit an MCP client configuration.")).toBeVisible();
    expect(screen.getByText("EXAMPLE_TOKEN")).toBeVisible();
    expect(screen.getByText("Requests secret or credential input")).toBeVisible();
    expect(screen.getByText("Input needed")).toBeVisible();
    expect(screen.getByText("Registry record · not a security approval")).toBeVisible();
    expect(screen.getByText("Configuration required")).toBeVisible();
    expect(screen.getByText("This machine's runtime has not been probed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save setup plan" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Install unavailable" })).toBeNull();
    expect(screen.getByText("Protected lifecycle continues in a managed plan")).toBeVisible();
    expect(screen.queryByText("synthetic-secret")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Back to catalog" }));
    expect(screen.getByLabelText("Search MCP servers")).toBeVisible();
    expect(screen.getByText("Synthetic A")).toBeVisible();
  });

  it("reloads the catalog instead of retrying a review whose source identity changed", async () => {
    const selected = server("a");
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([selected]))
      .mockResolvedValueOnce(catalog([selected]));
    const getMcpRegistryServerReview = vi.fn().mockRejectedValue(
      new TransportError(
        "synthetic private metadata",
        409,
        "mcp_registry_source_disagreement",
      ),
    );
    render(<AgentMcpStorePanel transport={{
      getMcpRegistryServerReview,
      listMcpRegistryCatalog,
    }} />);
    await screen.findByText("Synthetic A");
    fireEvent.click(screen.getByRole("button", { name: "Review Synthetic A" }));

    expect(await screen.findByText(/Registry disagreed about this exact server identity/i)).toBeVisible();
    expect(screen.queryByText("synthetic private metadata")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reload catalog" }));
    expect(await screen.findByLabelText("Search MCP servers")).toBeVisible();
    await waitFor(() => expect(listMcpRegistryCatalog).toHaveBeenCalledTimes(2));
    expect(getMcpRegistryServerReview).toHaveBeenCalledTimes(1);
  });

  it("loads another cursor, de-duplicates identities, and preserves prior cards", async () => {
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([server("a")], "next-page"))
      .mockResolvedValueOnce(catalog([server("a"), server("c")], null));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic A");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Synthetic C")).toBeVisible();
    expect(screen.getAllByText("Synthetic A")).toHaveLength(1);
    expect(listMcpRegistryCatalog).toHaveBeenLastCalledWith(
      { search: "", cursor: "next-page", limit: 24 },
      expect.any(AbortSignal),
    );
  });

  it("preserves the earlier card when a later page contradicts the same identity", async () => {
    const original = server("a");
    const conflicting = {
      ...original,
      presentation_revision: "b".repeat(64),
      title: "Contradictory title",
    };
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([original], "next-page"))
      .mockResolvedValueOnce(catalog([conflicting], null));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic A");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/Registry disagreed about this exact server identity/i)).toBeVisible();
    expect(screen.getByText("Synthetic A")).toBeVisible();
    expect(screen.queryByText("Contradictory title")).toBeNull();
    expect(screen.getByRole("button", { name: "Restart catalog" })).toBeVisible();
  });

  it("stops a multi-page cursor cycle without merging the cycling response", async () => {
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([pagedServer(0)], "cursor-a"))
      .mockResolvedValueOnce(catalog([pagedServer(1)], "cursor-b"))
      .mockResolvedValueOnce(catalog([pagedServer(2)], "cursor-a"));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic page 0");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Synthetic page 1")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText(/repeated an earlier page cursor/i)).toBeVisible();
    expect(screen.getByText("Synthetic page 0")).toBeVisible();
    expect(screen.getByText("Synthetic page 1")).toBeVisible();
    expect(screen.queryByText("Synthetic page 2")).toBeNull();
    expect(screen.getByRole("button", { name: "Restart catalog" })).toBeVisible();
  });

  it("stops an identical page replay even when the Registry changes its cursor", async () => {
    const repeated = pagedServer(0);
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([repeated], "cursor-a"))
      .mockResolvedValueOnce(catalog([repeated], "cursor-b"));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic page 0");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/replayed a page without adding a new server/i)).toBeVisible();
    expect(screen.getAllByText("Synthetic page 0")).toHaveLength(1);
    expect(listMcpRegistryCatalog).toHaveBeenCalledTimes(2);
  });

  it("bounds one catalog journey to 32 successful pages without a 33rd request", async () => {
    const listMcpRegistryCatalog = vi.fn().mockImplementation(
      ({ cursor }: { cursor?: string }) => {
        const page = cursor === undefined ? 0 : Number(cursor.replace("cursor-", ""));
        return Promise.resolve(catalog([pagedServer(page)], `cursor-${page + 1}`));
      },
    );
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic page 0");

    for (let page = 1; page < 32; page += 1) {
      fireEvent.click(screen.getByRole("button", { name: "Load more" }));
      await screen.findByText(`Synthetic page ${page}`);
    }
    expect(listMcpRegistryCatalog).toHaveBeenCalledTimes(32);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText(/32-page safety limit/i)).toBeVisible();
    expect(listMcpRegistryCatalog).toHaveBeenCalledTimes(32);
    expect(screen.getByRole("button", { name: "Restart catalog" })).toBeVisible();
  });

  it("keeps prior cards and retries the exact cursor after a next-page failure", async () => {
    const listMcpRegistryCatalog = vi.fn()
      .mockResolvedValueOnce(catalog([server("a")], "next-page"))
      .mockRejectedValueOnce(new TransportError("synthetic private detail", 503))
      .mockResolvedValueOnce(catalog([server("c")], null));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic A");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("The next Registry page could not be loaded.")).toBeVisible();
    expect(screen.getByText("Synthetic A")).toBeVisible();
    expect(screen.queryByText("synthetic private detail")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry next page" }));
    expect(await screen.findByText("Synthetic C")).toBeVisible();
    expect(screen.getByText("Synthetic A")).toBeVisible();
    expect(listMcpRegistryCatalog).toHaveBeenLastCalledWith(
      { search: "", cursor: "next-page", limit: 24 },
      expect.any(AbortSignal),
    );
  });

  it("ignores a late catalog response after a newer search aborts it", async () => {
    const first = deferredCatalog();
    const second = deferredCatalog();
    const listMcpRegistryCatalog = vi.fn().mockImplementation(({ search }: { search: string }) => {
      if (search === "first") return first.promise;
      if (search === "second") return second.promise;
      return Promise.resolve(catalog());
    });
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    await screen.findByText("Synthetic A");

    fireEvent.change(screen.getByLabelText("Search MCP servers"), { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(listMcpRegistryCatalog).toHaveBeenCalledWith(
      { search: "first", cursor: undefined, limit: 24 },
      expect.any(AbortSignal),
    ));
    const firstSignal = listMcpRegistryCatalog.mock.calls.at(-1)?.[1] as AbortSignal;

    fireEvent.change(screen.getByLabelText("Search MCP servers"), { target: { value: "second" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(firstSignal.aborted).toBe(true));
    second.resolve({ ...catalog([server("c")]), search: "second" });
    expect(await screen.findByText("Synthetic C")).toBeVisible();

    first.resolve({ ...catalog([server("d")]), search: "first" });
    await waitFor(() => expect(screen.queryByText("Synthetic D")).toBeNull());
    expect(screen.getByText("Search: “second”")).toBeVisible();
  });

  it("keeps Agent chat usable when no catalog route or registry is available", async () => {
    const { rerender } = render(<AgentMcpStorePanel transport={{}} />);
    expect(await screen.findByText(/does not expose the local catalog route/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Retry catalog" })).toBeNull();

    const listMcpRegistryCatalog = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic unavailable"))
      .mockResolvedValueOnce(catalog());
    rerender(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);
    expect(await screen.findByRole("button", { name: "Retry catalog" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry catalog" }));
    expect(await screen.findByText("Synthetic A")).toBeVisible();
  });

  it("retries managed-list loading without changing catalog authority", async () => {
    const cleanup = syntheticMcpManagedServer({
      lifecycle_state: "cleanup_required",
      installation_state: "cleanup_required",
      operation_state: "cleanup_required",
    });
    const listMcpManagedServers = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic unavailable"))
      .mockResolvedValueOnce(syntheticMcpManagedServerList([cleanup]));
    render(<AgentMcpStorePanel transport={{
      listMcpManagedServers,
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
    }} />);

    const managedTab = await screen.findByRole("tab", { name: "Managed servers" });
    fireEvent.click(managedTab);
    expect(await screen.findByText(/Managed lifecycle state could not be loaded/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry managed servers" }));

    const row = await screen.findByRole("button", { name: /Open Synthetic Files managed plan — Cleanup required/i });
    expect(row).toHaveTextContent("Recovery blocks new lifecycle actions");
    expect(within(row).getByText("Cleanup required")).toBeVisible();
    expect(listMcpManagedServers).toHaveBeenCalledTimes(2);
  });

  it("distinguishes safe transport failure classes without rendering error payloads", async () => {
    const listMcpRegistryCatalog = vi.fn()
      .mockRejectedValueOnce(new TransportError("synthetic private detail", 200))
      .mockRejectedValueOnce(new TransportError("synthetic private detail", 503));
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog }} />);

    expect(await screen.findByText(/rejected an invalid Registry response/i)).toBeVisible();
    expect(screen.queryByText("synthetic private detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry catalog" }));
    expect(await screen.findByText(/official Registry and an exact cached result were unavailable/i)).toBeVisible();
    expect(screen.queryByText("synthetic private detail")).toBeNull();
  });

  it("discloses cached and partial metadata", async () => {
    const cached: McpRegistryCatalog = {
      ...catalog(),
      source: { ...catalog().source, delivery: "cached", cache_age_seconds: 3600 },
      partial: true,
    };
    render(<AgentMcpStorePanel transport={{ listMcpRegistryCatalog: vi.fn().mockResolvedValue(cached) }} />);
    expect(await screen.findByText("Cached")).toBeVisible();
    expect(screen.getByText(/Offline fallback · 3600s old/)).toBeVisible();
    expect(screen.getByText("Some malformed or excess entries were omitted")).toBeVisible();
  });

  it("restores durable prepared plans and opens one without implying execution", async () => {
    const managed = syntheticMcpManagedServer();
    render(<AgentMcpStorePanel transport={{
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
    }} />);

    const prepared = await openManagedServers();
    expect(within(prepared).getByText("1")).toBeVisible();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));

    expect(await screen.findByRole("heading", { name: "Synthetic Files" })).toBeVisible();
    expect(screen.getByText(/only an exact MCPB release with a declared SHA-256 digest/i)).toBeVisible();
    expect(screen.getByText("not installed")).toBeVisible();
    expect(screen.getByText("not started")).toBeVisible();
    expect(screen.getAllByText("not checked", { selector: "dd" })).toHaveLength(2);
    expect(await screen.findByText(/lifecycle preview could not be verified/i)).toBeVisible();
  });

  it("saves only an exact reviewed setup plan after native presence", async () => {
    const selected = server("a");
    const review = syntheticMcpRegistryServerReview();
    Object.assign(review.server, selected);
    review.provenance.publisher_namespace = selected.publisher;
    review.versions[0].version = selected.version;
    const managed = syntheticMcpManagedServer({
      catalog_id: selected.catalog_id,
      server_name: selected.name,
      server_title: selected.title,
      server_version: selected.version,
      option_id: review.options[0].option_id,
      plan_revision: review.plan_revision,
    });
    const createMcpManagedServer = vi.fn().mockResolvedValue(
      syntheticMcpManagedServerReceipt(managed),
    );
    render(<AgentMcpStorePanel
      transport={{
        createMcpManagedServer,
        getMcpRegistryServerReview: vi.fn().mockResolvedValue(review as unknown as McpRegistryServerReview),
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog([selected])),
      }}
      userPresenceAvailable
    />);
    await screen.findByText("Synthetic A");
    fireEvent.click(screen.getByRole("button", { name: "Review Synthetic A" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save setup plan" }));

    expect(await screen.findByText(/only an exact MCPB release with a declared SHA-256 digest/i)).toBeVisible();
    expect(createMcpManagedServer).toHaveBeenCalledWith(expect.objectContaining({
      catalog_id: selected.catalog_id,
      name: selected.name,
      version: selected.version,
      option_id: review.options[0].option_id,
      plan_revision: review.plan_revision,
      request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
    }));
    expect(await screen.findByText(/lifecycle preview could not be verified/i)).toBeVisible();
  });

  it("keeps a prepared plan separate when newer Registry evidence changes its revision", async () => {
    const selected = server("a");
    const review = syntheticMcpRegistryServerReview();
    Object.assign(review.server, selected);
    review.provenance.publisher_namespace = selected.publisher;
    review.versions[0].version = selected.version;
    const previous = syntheticMcpManagedServer({
      catalog_id: selected.catalog_id,
      server_name: selected.name,
      server_title: selected.title,
      server_version: selected.version,
      option_id: review.options[0].option_id,
      plan_revision: "e".repeat(64),
    });
    const createMcpManagedServer = vi.fn();
    render(<AgentMcpStorePanel
      transport={{
        createMcpManagedServer,
        getMcpRegistryServerReview: vi.fn().mockResolvedValue(review as unknown as McpRegistryServerReview),
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([previous])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog([selected])),
      }}
      userPresenceAvailable
    />);
    await screen.findByText("Synthetic A");
    fireEvent.click(screen.getByRole("button", { name: "Review Synthetic A" }));

    expect(await screen.findByText(/Registry evidence changed since this plan was prepared/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open previous plan" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save setup plan" })).toBeNull();
    expect(createMcpManagedServer).not.toHaveBeenCalled();
  });

  it("requires every inferred project permission and keeps the saved binding inactive", async () => {
    const managed = syntheticMcpManagedProbeReceipt().server;
    const snapshot = syntheticMcpManagedToolSnapshot();
    const admittedToolIds = snapshot.tools.map((tool) => tool.tool_id).sort();
    const projectId = "f".repeat(32);
    const bound = syntheticMcpManagedServer({
      ...managed,
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
      project_bindings: [{
        project_id: projectId,
        project_name: "Synthetic project",
        enabled: true,
        required_permissions: managed.required_permissions,
        granted_permissions: managed.required_permissions,
        admitted_tool_ids: admittedToolIds,
        tool_snapshot_id: snapshot.snapshot_id,
        admission_state: "admitted",
        effective_state: "inactive_install_required",
        created_at: "2040-01-01T10:01:00Z",
        updated_at: "2040-01-01T10:01:00Z",
        revision: 1,
      }],
    });
    const setMcpManagedProjectBinding = vi.fn().mockResolvedValue(
      syntheticMcpManagedServerReceipt(bound),
    );
    const onManagedStateChange = vi.fn();
    render(<AgentMcpStorePanel
      activeProjectId={projectId}
      onManagedStateChange={onManagedStateChange}
      transport={{
        listAgentProjects: vi.fn().mockResolvedValue({
          contract_version: "agent-catalog.v2",
          projects: [{
            contract_version: "agent-catalog.v2",
            project_id: projectId,
            name: "Synthetic project",
            created_at: "2040-01-01T09:00:00Z",
            updated_at: "2040-01-01T09:00:00Z",
            revision: 1,
            pinned: false,
            archived_at: null,
            session_count: 0,
            is_default: false,
          }],
        }),
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
        getMcpManagedToolSnapshot: vi.fn().mockResolvedValue(snapshot),
        setMcpManagedProjectBinding,
      }}
      userPresenceAvailable
    />);
    const prepared = await openManagedServers();
    fireEvent.click(await within(prepared).findByRole("button", { name: /Synthetic Files/ }));
    const save = await screen.findByRole("button", { name: "Save project admission" });
    expect(save).toBeDisabled();

    const grants = within(screen.getByRole("group", { name: "Required runtime permissions" }))
      .getAllByRole("checkbox");
    expect(grants).toHaveLength(managed.required_permissions.length);
    await waitFor(() => grants.forEach((checkbox) => expect(checkbox).toBeEnabled()));
    grants.forEach((checkbox) => fireEvent.click(checkbox));
    const tools = within(screen.getByRole("group", { name: "Allowed reviewed tools" }))
      .getAllByRole("checkbox");
    expect(tools).toHaveLength(snapshot.tools.length);
    await waitFor(() => tools.forEach((checkbox) => expect(checkbox).toBeEnabled()));
    tools.forEach((checkbox) => fireEvent.click(checkbox));
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    expect(await screen.findByText("2 admitted · runtime status shown above when selected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Admission already current" })).toBeDisabled();
    expect(onManagedStateChange).toHaveBeenCalledTimes(1);
    expect(setMcpManagedProjectBinding).toHaveBeenCalledWith(
      managed.management_id,
      projectId,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 2,
        enabled: true,
        granted_permissions: managed.required_permissions,
        admitted_tool_ids: admittedToolIds,
      }),
    );
    expect(await screen.findByText(/lifecycle preview could not be verified/i)).toBeVisible();
  });

  it("uses a password field, clears it after vault storage, and never redisplays the value", async () => {
    const managed = syntheticMcpManagedServer();
    const requirementId = "e".repeat(32);
    const stored = syntheticMcpManagedServer({
      revision: 2,
      updated_at: "2040-01-01T10:01:00Z",
      requirements: managed.requirements.map((item) => item.requirement_id === requirementId
        ? {
          ...item,
          configuration_state: "secret_stored" as const,
          secret_vault_provider: "windows_credential_manager" as const,
        }
        : item),
    });
    const removed = syntheticMcpManagedServer({
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
    });
    const storeMcpManagedSecret = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic ambiguous failure"))
      .mockResolvedValueOnce(syntheticMcpManagedServerReceipt(stored));
    const removeMcpManagedSecret = vi.fn().mockResolvedValue(
      syntheticMcpManagedServerReceipt(removed),
    );
    render(<AgentMcpStorePanel
      transport={{
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
        removeMcpManagedSecret,
        storeMcpManagedSecret,
      }}
      userPresenceAvailable
    />);
    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));

    const input = await screen.findByLabelText("Credential value");
    expect(input).toHaveAttribute("type", "password");
    const value = "example-vault-value";
    fireEvent.change(input, { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Store in OS vault" }));

    expect(await screen.findByText(/not confirmed as stored/i)).toBeVisible();
    expect(screen.getByDisplayValue(value)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Store in OS vault" }));

    expect(await screen.findByRole("button", { name: "Remove from OS vault" })).toBeVisible();
    expect(screen.queryByDisplayValue(value)).toBeNull();
    expect(screen.queryByText(value)).toBeNull();
    expect(storeMcpManagedSecret).toHaveBeenLastCalledWith(
      managed.management_id,
      requirementId,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 1,
        value,
      }),
    );
    expect(storeMcpManagedSecret).toHaveBeenCalledTimes(2);
    expect(storeMcpManagedSecret.mock.calls[0][2].request_id).toBe(
      storeMcpManagedSecret.mock.calls[1][2].request_id,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove from OS vault" }));
    expect(await screen.findByRole("button", { name: "Store in OS vault" })).toBeDisabled();
    expect(removeMcpManagedSecret).toHaveBeenCalledWith(
      managed.management_id,
      requirementId,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 2,
      }),
    );
  });

  it("validates, vaults, clears, and removes required ordinary configuration", async () => {
    const managed = syntheticMcpManagedServer();
    const requirementId = "c".repeat(32);
    const stored = syntheticMcpManagedServer({
      revision: 2,
      updated_at: "2040-01-01T10:01:00Z",
      requirements: managed.requirements.map((item) => item.requirement_id === requirementId
        ? {
          ...item,
          configuration_state: "value_stored" as const,
          value_vault_provider: "windows_credential_manager" as const,
        }
        : item),
    });
    const removed = syntheticMcpManagedServer({
      revision: 3,
      updated_at: "2040-01-01T10:02:00Z",
    });
    const storeMcpManagedConfiguration = vi.fn()
      .mockRejectedValueOnce(new Error("synthetic ambiguous failure"))
      .mockResolvedValueOnce(syntheticMcpManagedServerReceipt(stored));
    const removeMcpManagedConfiguration = vi.fn().mockResolvedValue(
      syntheticMcpManagedServerReceipt(removed),
    );
    render(<AgentMcpStorePanel
      transport={{
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([managed])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
        removeMcpManagedConfiguration,
        storeMcpManagedConfiguration,
      }}
      userPresenceAvailable
    />);
    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));

    const input = await screen.findByLabelText("Configuration value for --workspace");
    expect(input).toHaveAttribute("type", "text");
    fireEvent.change(input, { target: { value: "relative/example" } });
    fireEvent.click(screen.getByRole("button", { name: "Store configuration" }));
    expect(await screen.findByText(/Enter an absolute file or folder path/i)).toBeVisible();
    expect(storeMcpManagedConfiguration).not.toHaveBeenCalled();

    const value = "X:\\example\\workspace";
    fireEvent.change(input, { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Store configuration" }));
    expect(await screen.findByText(/not confirmed as stored/i)).toBeVisible();
    expect(screen.getByDisplayValue(value)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Store configuration" }));

    expect(await screen.findByRole("button", { name: "Remove configuration" })).toBeVisible();
    expect(screen.queryByDisplayValue(value)).toBeNull();
    expect(screen.queryByText(value)).toBeNull();
    expect(storeMcpManagedConfiguration).toHaveBeenLastCalledWith(
      managed.management_id,
      requirementId,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 1,
        value,
      }),
    );
    expect(storeMcpManagedConfiguration).toHaveBeenCalledTimes(2);
    expect(storeMcpManagedConfiguration.mock.calls[0][2].request_id).toBe(
      storeMcpManagedConfiguration.mock.calls[1][2].request_id,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove configuration" }));
    expect(await screen.findByRole("button", { name: "Store configuration" })).toBeDisabled();
    expect(removeMcpManagedConfiguration).toHaveBeenCalledWith(
      managed.management_id,
      requirementId,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 2,
      }),
    );
  });

  it("keeps every management mutation disabled without native user presence", async () => {
    const createMcpManagedServer = vi.fn();
    render(<AgentMcpStorePanel transport={{
      createMcpManagedServer,
      getMcpRegistryServerReview: vi.fn().mockResolvedValue(syntheticMcpRegistryServerReview()),
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([])),
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
    }} />);

    await screen.findByText("Synthetic A");
    fireEvent.click(screen.getByRole("button", { name: "Review Synthetic A" }));
    expect(await screen.findByRole("button", { name: "Save setup plan" })).toBeDisabled();
    expect(createMcpManagedServer).not.toHaveBeenCalled();
  });

  it("runs one native-confirmed remote compatibility check and renders only its sanitized receipt", async () => {
    const remote = syntheticMcpManagedProbeReceipt().server;
    const unchecked = syntheticMcpManagedServer({
      ...remote,
      revision: 1,
      updated_at: "2040-01-01T10:00:00Z",
      health_state: "not_checked",
      last_health_checked_at: null,
      last_probe: null,
    });
    const receipt = syntheticMcpManagedProbeReceipt();
    const probeMcpManagedServer = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([unchecked])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
        probeMcpManagedServer,
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(await within(prepared).findByRole("button", { name: /Synthetic Files/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Run compatibility check" }));

    expect(await screen.findByText(/connection is closed and no tool was called/i)).toBeVisible();
    expect(screen.getByText("2026-07-28")).toBeVisible();
    expect(screen.getByText("Closed after probe")).toBeVisible();
    expect(screen.getByText(receipt.probe.schema_digest.slice(0, 12))).toBeVisible();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
    expect(probeMcpManagedServer).toHaveBeenCalledWith(
      unchecked.management_id,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: 1,
      }),
    );
    expect(document.body.textContent).not.toContain("synthetic_lookup");
  });

  it("keeps an otherwise available compatibility check disabled outside native confirmation", async () => {
    const remote = syntheticMcpManagedProbeReceipt().server;
    const unchecked = syntheticMcpManagedServer({
      ...remote,
      revision: 1,
      updated_at: "2040-01-01T10:00:00Z",
      health_state: "not_checked",
      last_health_checked_at: null,
      last_probe: null,
    });
    const probeMcpManagedServer = vi.fn();
    render(<AgentMcpStorePanel transport={{
      listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([unchecked])),
      listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      probeMcpManagedServer,
    }} />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByRole("button", { name: "Run compatibility check" })).toBeDisabled();
    expect(screen.getByText(/open the native Agent window/i)).toBeVisible();
    expect(probeMcpManagedServer).not.toHaveBeenCalled();
  });

  it("shows exact remote activation effects and applies only the preview digest", async () => {
    const compatible = syntheticMcpManagedProbeReceipt().server;
    const installPreview = syntheticMcpManagedLifecyclePreview({
      management_id: compatible.management_id,
      expected_revision: compatible.revision,
      plan_revision: compatible.plan_revision,
    });
    const uninstallPreview = syntheticMcpManagedLifecyclePreview({
      action: "uninstall",
      management_id: compatible.management_id,
      expected_revision: 3,
      plan_revision: compatible.plan_revision,
      effects: [
        "remove_remote_activation",
        "no_package_change",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
      preview_digest: "3".repeat(64),
    });
    const receipt = syntheticMcpManagedLifecycleReceipt();
    const getMcpManagedLifecyclePreview = vi.fn()
      .mockResolvedValueOnce(installPreview)
      .mockResolvedValueOnce(uninstallPreview);
    const applyMcpManagedLifecycle = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        applyMcpManagedLifecycle,
        getMcpManagedLifecyclePreview,
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([compatible])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByText("Save this exact reviewed remote activation")).toBeVisible();
    expect(screen.getByText("No process or terminal is started")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Activate remote plan" }));

    expect(await screen.findByText(/remote plan activated/i)).toBeVisible();
    expect(screen.getByText("Activated remote plan", { exact: false })).toBeVisible();
    expect(applyMcpManagedLifecycle).toHaveBeenCalledWith(
      compatible.management_id,
      "install",
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: installPreview.expected_revision,
        preview_digest: installPreview.preview_digest,
      }),
    );
    expect(await screen.findByRole("button", { name: "Remove remote activation" })).toBeEnabled();
    expect(getMcpManagedLifecyclePreview).toHaveBeenLastCalledWith(
      compatible.management_id,
      "uninstall",
      expect.any(AbortSignal),
    );
  });

  it("installs one checksum-pinned MCPB package and renders durable cleanup evidence", async () => {
    const planned = syntheticMcpManagedServer({
      option_label: "MCPB release",
      registry_type: "mcpb",
      package_identifier: "https://github.com/example/synthetic/releases/download/v1/synthetic.mcpb",
      runtime_hint: "node",
      requirements: [],
      install_action: "unavailable_configuration_inspection_required",
    });
    const inspection = syntheticMcpManagedLocalConfigurationInspection({
      plan_revision: planned.plan_revision,
      artifact_sha256: "4".repeat(64),
      manifest_digest: "6".repeat(64),
      manifest_version: "0.3",
      requirement_ids: [],
    });
    const inspectionPreview = syntheticMcpManagedLocalConfigurationInspectionPreview({
      management_id: planned.management_id,
      expected_revision: planned.revision,
      plan_revision: planned.plan_revision,
    });
    const inspected = syntheticMcpManagedServer({
      ...planned,
      revision: planned.revision + 1,
      updated_at: inspection.inspected_at,
      local_configuration_inspection: inspection,
      install_action: "available_native_confirmation_required",
    });
    const inspectionReceipt = syntheticMcpManagedLocalConfigurationInspectionReceipt({
      server: inspected,
      inspection,
      preview_digest: inspectionPreview.preview_digest,
    });
    const inspectionRequiredPreview = syntheticMcpManagedLifecyclePreview({
      management_id: planned.management_id,
      expected_revision: planned.revision,
      plan_revision: planned.plan_revision,
      installation_kind: "local_package",
      availability: "unavailable",
      reason: "configuration_inspection_required",
      effects: [
        "download_exact_package",
        "verify_artifact_sha256",
        "stage_isolated_package",
        "execute_bounded_compatibility_probe",
        "stop_and_verify_process_tree",
        "publish_verified_package",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    const installPreview = syntheticMcpManagedLifecyclePreview({
      management_id: planned.management_id,
      expected_revision: inspected.revision,
      plan_revision: planned.plan_revision,
      installation_kind: "local_package",
      effects: [
        "download_exact_package",
        "verify_artifact_sha256",
        "stage_isolated_package",
        "execute_bounded_compatibility_probe",
        "stop_and_verify_process_tree",
        "publish_verified_package",
        "no_connection_retained",
        "no_tool_authority",
      ],
    });
    const installedBase = syntheticMcpManagedLocalLifecycleReceipt();
    const installedReceipt = syntheticMcpManagedLocalLifecycleReceipt({
      server: {
        ...installedBase.server,
        local_configuration_inspection: inspection,
      },
    });
    const uninstallPreview = syntheticMcpManagedLifecyclePreview({
      action: "uninstall",
      management_id: planned.management_id,
      expected_revision: installedReceipt.server.revision,
      plan_revision: planned.plan_revision,
      installation_kind: "local_package",
      effects: [
        "verify_installed_tree_digest",
        "quarantine_verified_package",
        "remove_quarantined_package",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
      ],
      preview_digest: "3".repeat(64),
    });
    const removedReceipt = syntheticMcpManagedLocalUninstallReceipt({
      server: syntheticMcpManagedServer({
        ...syntheticMcpManagedLocalUninstallReceipt().server,
        management_id: planned.management_id,
        catalog_id: planned.catalog_id,
        option_id: planned.option_id,
        plan_revision: planned.plan_revision,
        server_name: planned.server_name,
        server_title: planned.server_title,
        revision: installedReceipt.server.revision + 1,
      }),
      preview_digest: uninstallPreview.preview_digest,
    });
    const reinstallPreview = syntheticMcpManagedLifecyclePreview({
      management_id: planned.management_id,
      expected_revision: removedReceipt.server.revision,
      plan_revision: planned.plan_revision,
      installation_kind: "local_package",
      availability: "unavailable",
      reason: "configuration_inspection_required",
      effects: installPreview.effects,
      preview_digest: "4".repeat(64),
    });
    const getMcpManagedLifecyclePreview = vi.fn()
      .mockResolvedValueOnce(inspectionRequiredPreview)
      .mockResolvedValueOnce(installPreview)
      .mockResolvedValueOnce(uninstallPreview)
      .mockResolvedValueOnce(reinstallPreview);
    const getMcpManagedLocalConfigurationInspectionPreview = vi.fn()
      .mockResolvedValue(inspectionPreview);
    const inspectMcpManagedLocalConfiguration = vi.fn()
      .mockResolvedValue(inspectionReceipt);
    const applyMcpManagedLifecycle = vi.fn()
      .mockResolvedValueOnce(installedReceipt)
      .mockResolvedValueOnce(removedReceipt);
    const onAcceptanceEvidence = vi.fn();
    render(<AgentMcpStorePanel
      onAcceptanceEvidence={onAcceptanceEvidence}
      transport={{
        applyMcpManagedLifecycle,
        getMcpManagedLifecyclePreview,
        getMcpManagedLocalConfigurationInspectionPreview,
        inspectMcpManagedLocalConfiguration,
        listMcpManagedServers: vi.fn().mockResolvedValue(syntheticMcpManagedServerList([planned])),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByText("Read only the bounded MCPB configuration schema; do not execute the package")).toBeVisible();
    expect(screen.getByText("Start no package process or terminal")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Inspect package configuration" }));
    expect(await screen.findByText(/package configuration inspected without execution/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Package configuration checkpoint" })).toBeVisible();
    expect(screen.getByText(/archive and staging tree were discarded/i)).toBeVisible();
    expect(inspectMcpManagedLocalConfiguration).toHaveBeenCalledWith(
      planned.management_id,
      expect.objectContaining({
        expected_revision: planned.revision,
        preview_digest: inspectionPreview.preview_digest,
      }),
    );
    expect(await screen.findByText("Match the declared SHA-256 digest before extraction")).toBeVisible();
    expect(screen.getByText("Stop the owned process tree and verify cleanup")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Install local package" }));

    expect(await screen.findByText(/local package installed from its verified checksum/i)).toBeVisible();
    expect(screen.getByText("Installed local package", { exact: false })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Verified local package" })).toBeVisible();
    expect(screen.getByText("4,096 bytes")).toBeVisible();
    expect(screen.getByText("MCPB 0.3")).toBeVisible();
    expect(screen.getByText("verified")).toBeVisible();
    expect(screen.getByText(/process tree is verified stopped/i)).toBeVisible();
    expect(applyMcpManagedLifecycle).toHaveBeenCalledWith(
      planned.management_id,
      "install",
      expect.objectContaining({
        expected_revision: inspected.revision,
        preview_digest: installPreview.preview_digest,
      }),
    );
    expect(onAcceptanceEvidence).toHaveBeenNthCalledWith(1, {
      kind: "lifecycle",
      receipt: installedReceipt,
    });
    expect(await screen.findByText("Verify the installed tree still matches its retained digest")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Remove local package" }));
    expect(await screen.findByText(/verified local package removed through digest-bound quarantine/i)).toBeVisible();
    expect(screen.getByText("Prepared plan", { exact: false })).toBeVisible();
    expect(applyMcpManagedLifecycle).toHaveBeenLastCalledWith(
      planned.management_id,
      "uninstall",
      expect.objectContaining({
        expected_revision: uninstallPreview.expected_revision,
        preview_digest: uninstallPreview.preview_digest,
      }),
    );
    expect(onAcceptanceEvidence).toHaveBeenNthCalledWith(2, {
      kind: "lifecycle",
      receipt: removedReceipt,
    });
  });

  it("shows and completes an exact interrupted local-package recovery", async () => {
    const cleanupServer = syntheticMcpManagedServer({
      ...syntheticMcpManagedLocalLifecycleReceipt().server,
      revision: 4,
      lifecycle_state: "cleanup_required",
      installation_state: "cleanup_required",
      operation_state: "cleanup_required",
    });
    const preview = syntheticMcpManagedLocalCleanupPreview({
      management_id: cleanupServer.management_id,
      expected_revision: cleanupServer.revision,
      plan_revision: cleanupServer.plan_revision,
    });
    const receipt = syntheticMcpManagedLocalCleanupReceipt({
      server: syntheticMcpManagedServer({
        ...syntheticMcpManagedLocalCleanupReceipt().server,
        management_id: cleanupServer.management_id,
        catalog_id: cleanupServer.catalog_id,
        option_id: cleanupServer.option_id,
        plan_revision: cleanupServer.plan_revision,
        server_name: cleanupServer.server_name,
        server_title: cleanupServer.server_title,
        revision: cleanupServer.revision + 1,
      }),
      preview_digest: preview.preview_digest,
    });
    const getMcpManagedLocalCleanupPreview = vi.fn().mockResolvedValue(preview);
    const completeMcpManagedLocalCleanup = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        completeMcpManagedLocalCleanup,
        getMcpManagedLocalCleanupPreview,
        listMcpManagedServers: vi.fn().mockResolvedValue(
          syntheticMcpManagedServerList([cleanupServer]),
        ),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(await within(prepared).findByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByRole("heading", { name: "Recovery preview" })).toBeVisible();
    expect(screen.getByText("Bind recovery to the retained uninstall journal")).toBeVisible();
    expect(screen.getByText(/blocks every new lifecycle change/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Complete interrupted removal" }));

    expect(await screen.findByText(/interrupted local-package removal completed/i)).toBeVisible();
    expect(completeMcpManagedLocalCleanup).toHaveBeenCalledWith(
      cleanupServer.management_id,
      expect.objectContaining({
        expected_revision: preview.expected_revision,
        preview_digest: preview.preview_digest,
      }),
    );
    expect(screen.getByText("not installed")).toBeVisible();
  });

  it("applies only the exact native-confirmed Registry update preview", async () => {
    const installed = syntheticMcpManagedLocalLifecycleReceipt().server;
    const preview = syntheticMcpManagedLocalUpdatePreview({
      management_id: installed.management_id,
      expected_revision: installed.revision,
      current_version: installed.server_version,
      current_plan_revision: installed.plan_revision,
    });
    const receipt = syntheticMcpManagedLocalUpdateReceipt({
      preview_digest: preview.preview_digest,
    });
    const afterUpdate = syntheticMcpManagedLocalUpdatePreview({
      expected_revision: receipt.server.revision,
      current_version: receipt.server.server_version,
      current_plan_revision: receipt.server.plan_revision,
      target_version: null,
      target_catalog_id: null,
      target_option_id: null,
      target_plan_revision: null,
      availability: "unavailable",
      reason: "already_latest",
    });
    const getMcpManagedLocalUpdatePreview = vi.fn()
      .mockResolvedValueOnce(preview)
      .mockResolvedValue(afterUpdate);
    const applyMcpManagedLocalUpdate = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        applyMcpManagedLocalUpdate,
        getMcpManagedLocalUpdatePreview,
        listMcpManagedServers: vi.fn().mockResolvedValue(
          syntheticMcpManagedServerList([installed]),
        ),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));

    expect(await screen.findByRole("heading", { name: "Registry latest update" })).toBeVisible();
    expect(screen.getByText("A newer exact Registry version is reviewable")).toBeVisible();
    expect(screen.getByText("2.0.0")).toBeVisible();
    expect(screen.getByText("Retain one verified bounded rollback generation")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Update to 2.0.0" }));

    expect(await screen.findByText(/exact target was checksum-verified/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Retained rollback generation" })).toBeVisible();
    expect(applyMcpManagedLocalUpdate).toHaveBeenCalledWith(
      installed.management_id,
      expect.objectContaining({
        request_id: expect.stringMatching(/^[0-9a-f]{32}$/u),
        expected_revision: preview.expected_revision,
        preview_digest: preview.preview_digest,
      }),
    );
    expect(getMcpManagedLocalUpdatePreview).toHaveBeenCalledWith(
      installed.management_id,
      expect.any(AbortSignal),
    );
  });

  it("atomically restores the retained generation and keeps the superseded package reversible", async () => {
    const updated = syntheticMcpManagedLocalUpdateReceipt().server;
    const preview = syntheticMcpManagedLocalRollbackPreview({
      management_id: updated.management_id,
      expected_revision: updated.revision,
      current_version: updated.server_version,
      current_plan_revision: updated.plan_revision,
      target_version: updated.rollback_generation?.server_version ?? "1.2.3",
      target_plan_revision: updated.rollback_generation?.plan_revision ?? "d".repeat(64),
    });
    const receipt = syntheticMcpManagedLocalRollbackReceipt({
      preview_digest: preview.preview_digest,
    });
    const applyMcpManagedLocalRollback = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        applyMcpManagedLocalRollback,
        getMcpManagedLocalRollbackPreview: vi.fn().mockResolvedValue(preview),
        getMcpManagedLocalRollbackCleanupPreview: vi.fn().mockResolvedValue(
          syntheticMcpManagedLocalRollbackCleanupPreview(),
        ),
        listMcpManagedServers: vi.fn().mockResolvedValue(
          syntheticMcpManagedServerList([updated]),
        ),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(await within(prepared).findByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByText("Atomically exchange the two verified generations")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Roll back to 1.2.3" }));

    expect(await screen.findByText(/two verified package generations were atomically exchanged/i)).toBeVisible();
    expect(applyMcpManagedLocalRollback).toHaveBeenCalledWith(
      updated.management_id,
      expect.objectContaining({
        expected_revision: preview.expected_revision,
        preview_digest: preview.preview_digest,
      }),
    );
    expect(screen.getByRole("heading", { name: "Retained rollback generation" })).toBeVisible();
  });

  it("removes only the verified retained generation while keeping the current package", async () => {
    const updated = syntheticMcpManagedLocalUpdateReceipt().server;
    const preview = syntheticMcpManagedLocalRollbackCleanupPreview({
      management_id: updated.management_id,
      expected_revision: updated.revision,
      rollback_version: updated.rollback_generation?.server_version ?? "1.2.3",
      rollback_plan_revision: updated.rollback_generation?.plan_revision ?? "d".repeat(64),
    });
    const receipt = syntheticMcpManagedLocalRollbackCleanupReceipt({
      preview_digest: preview.preview_digest,
    });
    const cleanupMcpManagedLocalRollback = vi.fn().mockResolvedValue(receipt);
    const onAcceptanceEvidence = vi.fn();
    render(<AgentMcpStorePanel
      onAcceptanceEvidence={onAcceptanceEvidence}
      transport={{
        cleanupMcpManagedLocalRollback,
        getMcpManagedLocalRollbackCleanupPreview: vi.fn().mockResolvedValue(preview),
        listMcpManagedServers: vi.fn().mockResolvedValue(
          syntheticMcpManagedServerList([updated]),
        ),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByText("Remove the verified quarantined generation")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Remove retained generation" }));

    expect(await screen.findByText(/retained rollback generation was verified and removed/i)).toBeVisible();
    expect(cleanupMcpManagedLocalRollback).toHaveBeenCalledWith(
      updated.management_id,
      expect.objectContaining({
        expected_revision: preview.expected_revision,
        preview_digest: preview.preview_digest,
      }),
    );
    expect(onAcceptanceEvidence).toHaveBeenCalledWith({
      kind: "rollback_cleanup",
      receipt,
    });
    expect(screen.queryByRole("heading", { name: "Retained rollback generation" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Verified local package" })).toBeVisible();
  });

  it("prefers the exact interrupted-operation journal over legacy uninstall recovery", async () => {
    const cleanupServer = syntheticMcpManagedServer({
      ...syntheticMcpManagedLocalLifecycleReceipt().server,
      revision: 5,
      lifecycle_state: "cleanup_required",
      installation_state: "cleanup_required",
      operation_state: "cleanup_required",
    });
    const preview = syntheticMcpManagedLocalOperationRecoveryPreview({
      management_id: cleanupServer.management_id,
      expected_revision: cleanupServer.revision,
    });
    const receipt = syntheticMcpManagedLocalOperationRecoveryReceipt({
      server: syntheticMcpManagedServer({
        ...syntheticMcpManagedLocalOperationRecoveryReceipt().server,
        management_id: cleanupServer.management_id,
        revision: cleanupServer.revision + 1,
      }),
      preview_digest: preview.preview_digest,
    });
    const recoverMcpManagedLocalOperation = vi.fn().mockResolvedValue(receipt);
    render(<AgentMcpStorePanel
      transport={{
        completeMcpManagedLocalCleanup: vi.fn(),
        getMcpManagedLocalCleanupPreview: vi.fn().mockResolvedValue(
          syntheticMcpManagedLocalCleanupPreview({
            management_id: cleanupServer.management_id,
            expected_revision: cleanupServer.revision,
          }),
        ),
        getMcpManagedLocalOperationRecoveryPreview: vi.fn().mockResolvedValue(preview),
        recoverMcpManagedLocalOperation,
        listMcpManagedServers: vi.fn().mockResolvedValue(
          syntheticMcpManagedServerList([cleanupServer]),
        ),
        listMcpRegistryCatalog: vi.fn().mockResolvedValue(catalog()),
      }}
      userPresenceAvailable
    />);

    const prepared = await openManagedServers();
    fireEvent.click(within(prepared).getByRole("button", { name: /Synthetic Files/ }));
    expect(await screen.findByText("Discard only the verified staged or partially published target")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Complete interrupted removal" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Recover interrupted update" }));

    expect(await screen.findByText(/interrupted update recovery verified the filesystem/i)).toBeVisible();
    expect(recoverMcpManagedLocalOperation).toHaveBeenCalledWith(
      cleanupServer.management_id,
      expect.objectContaining({
        expected_revision: preview.expected_revision,
        preview_digest: preview.preview_digest,
      }),
    );
  });
});
