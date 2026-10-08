import type {
  McpRegistryCatalog,
  McpRegistryIcon,
  McpRegistryPackage,
  McpRegistryRemote,
  McpRegistryServer,
} from "./contracts";

export class McpRegistryCatalogPayloadError extends Error {
  constructor() {
    super("MCP Registry catalog response was invalid");
    this.name = "McpRegistryCatalogPayloadError";
  }
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new McpRegistryCatalogPayloadError();
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new McpRegistryCatalogPayloadError();
  }
}

export function isSafeMcpRegistryText(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string {
  if (typeof value !== "string" || value.normalize("NFC") !== value || /\p{C}/u.test(value)) {
    return false;
  }
  const characters = Array.from(value);
  if (characters.length < minimum || characters.length > maximum || value.trim() !== value) {
    return false;
  }
  let combiningRun = 0;
  for (const character of characters) {
    if (/\p{M}/u.test(character)) {
      combiningRun += 1;
      if (combiningRun > 4) return false;
    } else {
      combiningRun = 0;
    }
  }
  return true;
}

const safeText = isSafeMcpRegistryText;

function utcTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/u.test(value)
    && Number.isFinite(Date.parse(value));
}

function optionalHttpsUrl(value: unknown): value is string | null {
  if (value === null) return true;
  if (!isSafeMcpRegistryText(value, 1, 1024)) return false;
  try {
    const parsed = new URL(value);
    const authority = value.slice("https://".length).split(/[/?#]/u, 1)[0] ?? "";
    return parsed.protocol === "https:"
      && parsed.hostname !== ""
      && !/[^\x00-\x7f]/u.test(authority)
      && parsed.username === ""
      && parsed.password === ""
      && parsed.hash === "";
  } catch {
    return false;
  }
}

function parseIcon(value: unknown): McpRegistryIcon | null {
  if (value === null) return null;
  const icon = record(value);
  exactKeys(icon, ["path", "mime_type"]);
  if (
    typeof icon.path !== "string"
    || !/^\/v1\/integrations\/mcp-store\/icons\/[0-9a-f]{32}$/u.test(icon.path)
    || !["image/png", "image/jpeg", "image/webp"].includes(String(icon.mime_type))
  ) {
    throw new McpRegistryCatalogPayloadError();
  }
  return icon as unknown as McpRegistryIcon;
}

function parsePackage(value: unknown): McpRegistryPackage {
  const item = record(value);
  exactKeys(item, [
    "registry_type",
    "identifier",
    "version",
    "transport",
    "runtime_hint",
    "checksum_available",
  ]);
  if (
    !safeText(item.registry_type, 1, 32)
    || !/^[a-z0-9][a-z0-9._-]{0,31}$/u.test(item.registry_type)
    || !safeText(item.identifier, 1, 512)
    || !(item.version === null || safeText(item.version, 1, 255))
    || !["stdio", "streamable-http", "sse", "unknown"].includes(String(item.transport))
    || !(item.runtime_hint === null || safeText(item.runtime_hint, 1, 32))
    || typeof item.checksum_available !== "boolean"
  ) {
    throw new McpRegistryCatalogPayloadError();
  }
  return item as unknown as McpRegistryPackage;
}

function parseRemote(value: unknown): McpRegistryRemote {
  const item = record(value);
  exactKeys(item, ["transport", "endpoint_host", "endpoint_state", "secure"]);
  if (
    !["stdio", "streamable-http", "sse", "unknown"].includes(String(item.transport))
    || !["fixed_host", "template_requires_configuration"].includes(String(item.endpoint_state))
    || !(
      (item.endpoint_state === "fixed_host"
        && safeText(item.endpoint_host, 1, 255)
        && typeof item.secure === "boolean")
      || (item.endpoint_state === "template_requires_configuration"
        && item.endpoint_host === null
        && item.secure === null)
    )
  ) {
    throw new McpRegistryCatalogPayloadError();
  }
  return item as unknown as McpRegistryRemote;
}

export function parseMcpRegistryServer(value: unknown): McpRegistryServer {
  const item = record(value);
  exactKeys(item, [
    "catalog_id",
    "presentation_revision",
    "name",
    "title",
    "description",
    "publisher",
    "version",
    "status",
    "updated_at",
    "repository_url",
    "website_url",
    "icon",
    "packages",
    "remotes",
    "supports_local",
    "supports_remote",
    "management_state",
    "install_action",
    "install_reason",
  ]);
  if (
    typeof item.catalog_id !== "string"
    || !/^[0-9a-f]{32}$/u.test(item.catalog_id)
    || typeof item.presentation_revision !== "string"
    || !/^[0-9a-f]{64}$/u.test(item.presentation_revision)
    || !safeText(item.name, 3, 241)
    || !/^[A-Za-z0-9.-]{1,160}\/[A-Za-z0-9._-]{1,80}$/u.test(item.name)
    || !safeText(item.title, 1, 100)
    || !safeText(item.description, 1, 500)
    || !safeText(item.publisher, 1, 160)
    || item.publisher !== item.name.split("/", 1)[0]
    || !safeText(item.version, 1, 255)
    || !["active", "deprecated", "deleted", "unknown"].includes(String(item.status))
    || !(item.updated_at === null || utcTimestamp(item.updated_at))
    || !optionalHttpsUrl(item.repository_url)
    || !optionalHttpsUrl(item.website_url)
    || !Array.isArray(item.packages)
    || item.packages.length > 8
    || !Array.isArray(item.remotes)
    || item.remotes.length > 8
    || typeof item.supports_local !== "boolean"
    || typeof item.supports_remote !== "boolean"
    || item.supports_local !== (item.packages.length > 0)
    || item.supports_remote !== (item.remotes.length > 0)
    || item.management_state !== "not_managed"
    || item.install_action !== "unavailable"
    || item.install_reason !== "guarded_install_host_not_implemented"
  ) {
    throw new McpRegistryCatalogPayloadError();
  }
  return {
    ...(item as unknown as McpRegistryServer),
    icon: parseIcon(item.icon),
    packages: item.packages.map(parsePackage),
    remotes: item.remotes.map(parseRemote),
  };
}

export function parseMcpRegistryCatalog(value: unknown): McpRegistryCatalog {
  const payload = record(value);
  exactKeys(payload, [
    "contract_version",
    "source",
    "search",
    "servers",
    "next_cursor",
    "partial",
    "management_truth",
  ]);
  const source = record(payload.source);
  exactKeys(source, ["registry", "base_url", "fetched_at", "delivery", "cache_age_seconds"]);
  if (
    payload.contract_version !== "mcp-registry-catalog.v1"
    || source.registry !== "official_mcp_registry"
    || source.base_url !== "https://registry.modelcontextprotocol.io"
    || !utcTimestamp(source.fetched_at)
    || !["live", "cached"].includes(String(source.delivery))
    || !Number.isSafeInteger(source.cache_age_seconds)
    || Number(source.cache_age_seconds) < 0
    || !safeText(payload.search, 0, 100)
    || payload.search.replace(/\s+/gu, " ") !== payload.search
    || !Array.isArray(payload.servers)
    || payload.servers.length > 48
    || !(payload.next_cursor === null || safeText(payload.next_cursor, 1, 512))
    || typeof payload.partial !== "boolean"
    || payload.management_truth !== "registry_only_no_install_authority"
  ) {
    throw new McpRegistryCatalogPayloadError();
  }
  const servers = payload.servers.map(parseMcpRegistryServer);
  if (new Set(servers.map((item) => item.catalog_id)).size !== servers.length) {
    throw new McpRegistryCatalogPayloadError();
  }
  return {
    contract_version: "mcp-registry-catalog.v1",
    source: source as unknown as McpRegistryCatalog["source"],
    search: payload.search,
    servers,
    next_cursor: payload.next_cursor as string | null,
    partial: payload.partial,
    management_truth: "registry_only_no_install_authority",
  };
}
