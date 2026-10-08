import type {
  McpRegistryInputRequirement,
  McpRegistryInstallOption,
  McpRegistryOptionCompatibility,
  McpRegistryProvenance,
  McpRegistryReviewCompatibilityReason,
  McpRegistryReviewRisk,
  McpRegistryServerReview,
  McpRegistryVersionSummary,
} from "./contracts";
import {
  isSafeMcpRegistryText,
  parseMcpRegistryServer,
} from "./mcpRegistryCatalogContract";

export class McpRegistryServerReviewPayloadError extends Error {
  constructor() {
    super("MCP Registry server review response was invalid");
    this.name = "McpRegistryServerReviewPayloadError";
  }
}

function invalid(): never {
  throw new McpRegistryServerReviewPayloadError();
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    invalid();
  }
}

const safeText = isSafeMcpRegistryText;

function utcTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/u.test(value)
    && Number.isFinite(Date.parse(value));
}

function optionalHttpsUrl(value: unknown): value is string | null {
  if (value === null) return true;
  if (!safeText(value, 1, 1024)) return false;
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

const compatibilityReasons = new Set<McpRegistryReviewCompatibilityReason>([
  "known_package_registry",
  "unknown_package_registry",
  "supported_transport",
  "unknown_transport",
  "runtime_hint_missing",
  "configuration_required",
  "endpoint_template_requires_configuration",
  "endpoint_invalid",
  "machine_runtime_not_probed",
  "platform_not_declared",
  "mcp_handshake_not_performed",
]);

const risks = new Set<McpRegistryReviewRisk>([
  "downloads_package",
  "executes_local_code",
  "package_integrity_not_declared",
  "command_arguments_declared",
  "filesystem_input_declared",
  "credential_input_declared",
  "remote_network_egress",
  "insecure_remote_transport",
]);

function parseRequirement(value: unknown): McpRegistryInputRequirement {
  const item = record(value);
  exactKeys(item, [
    "requirement_id",
    "location",
    "name",
    "description",
    "required",
    "secret",
    "format",
    "repeated",
    "fixed_value_declared",
    "default_declared",
    "choices_count",
    "user_value_needed",
  ]);
  if (
    typeof item.requirement_id !== "string"
    || !/^[0-9a-f]{32}$/u.test(item.requirement_id)
    || ![
      "runtime_argument",
      "package_argument",
      "environment_variable",
      "transport_header",
      "remote_variable",
    ].includes(String(item.location))
    || !safeText(item.name, 1, 128)
    || !(item.description === null || safeText(item.description, 1, 240))
    || typeof item.required !== "boolean"
    || typeof item.secret !== "boolean"
    || !["string", "number", "boolean", "filepath", "unknown"].includes(String(item.format))
    || typeof item.repeated !== "boolean"
    || typeof item.fixed_value_declared !== "boolean"
    || typeof item.default_declared !== "boolean"
    || !Number.isSafeInteger(item.choices_count)
    || Number(item.choices_count) < 0
    || Number(item.choices_count) > 64
    || typeof item.user_value_needed !== "boolean"
    || item.user_value_needed !== (
      item.required && !item.fixed_value_declared && !item.default_declared
    )
  ) invalid();
  return item as unknown as McpRegistryInputRequirement;
}

function parseCompatibility(value: unknown): McpRegistryOptionCompatibility {
  const item = record(value);
  exactKeys(item, [
    "status",
    "reasons",
    "platform_compatibility",
    "runtime_availability",
    "mcp_handshake",
  ]);
  if (
    !["reviewable", "requires_configuration", "unsupported"].includes(String(item.status))
    || !Array.isArray(item.reasons)
    || item.reasons.length < 3
    || item.reasons.length > 10
    || item.reasons.some((reason) => !compatibilityReasons.has(reason as McpRegistryReviewCompatibilityReason))
    || new Set(item.reasons).size !== item.reasons.length
    || !item.reasons.includes("machine_runtime_not_probed")
    || !item.reasons.includes("platform_not_declared")
    || !item.reasons.includes("mcp_handshake_not_performed")
    || item.platform_compatibility !== "unverified"
    || item.runtime_availability !== "unverified"
    || item.mcp_handshake !== "not_performed"
  ) invalid();
  const reasonSet = new Set(item.reasons);
  const expected = reasonSet.has("unknown_package_registry")
    || reasonSet.has("unknown_transport")
    || reasonSet.has("endpoint_invalid")
    ? "unsupported"
    : reasonSet.has("runtime_hint_missing")
      || reasonSet.has("configuration_required")
      || reasonSet.has("endpoint_template_requires_configuration")
      ? "requires_configuration"
      : "reviewable";
  if (item.status !== expected) invalid();
  return item as unknown as McpRegistryOptionCompatibility;
}

function parseInstallOption(value: unknown): McpRegistryInstallOption {
  const item = record(value);
  exactKeys(item, [
    "option_id",
    "kind",
    "label",
    "registry_type",
    "package_identifier",
    "package_version",
    "runtime_hint",
    "transport",
    "endpoint_host",
    "endpoint_state",
    "secure_transport",
    "checksum_state",
    "requirements",
    "risks",
    "compatibility",
    "execution_state",
  ]);
  if (
    typeof item.option_id !== "string"
    || !/^[0-9a-f]{32}$/u.test(item.option_id)
    || !["local_package", "remote_server"].includes(String(item.kind))
    || !safeText(item.label, 1, 120)
    || !(item.registry_type === null || safeText(item.registry_type, 1, 32))
    || !(item.package_identifier === null || safeText(item.package_identifier, 1, 512))
    || !(item.package_version === null || safeText(item.package_version, 1, 255))
    || !(item.runtime_hint === null || safeText(item.runtime_hint, 1, 32))
    || !["stdio", "streamable-http", "sse", "unknown"].includes(String(item.transport))
    || !["not_applicable", "fixed_host", "template_requires_configuration", "invalid"].includes(String(item.endpoint_state))
    || !(item.endpoint_host === null || safeText(item.endpoint_host, 1, 255))
    || !(item.secure_transport === null || typeof item.secure_transport === "boolean")
    || !["declared", "not_declared", "not_applicable"].includes(String(item.checksum_state))
    || !Array.isArray(item.requirements)
    || item.requirements.length > 32
    || !Array.isArray(item.risks)
    || item.risks.length > 8
    || item.risks.some((risk) => !risks.has(risk as McpRegistryReviewRisk))
    || new Set(item.risks).size !== item.risks.length
    || item.execution_state !== "preview_only"
  ) invalid();
  if (
    (item.endpoint_state === "fixed_host"
      && (item.endpoint_host === null || typeof item.secure_transport !== "boolean"))
    || (item.endpoint_state !== "fixed_host"
      && (item.endpoint_host !== null || item.secure_transport !== null))
  ) invalid();
  if (item.kind === "local_package") {
    if (
      item.registry_type === null
      || item.package_identifier === null
      || item.checksum_state === "not_applicable"
    ) invalid();
  } else if (
    item.registry_type !== null
    || item.package_identifier !== null
    || item.package_version !== null
    || item.runtime_hint !== null
    || item.checksum_state !== "not_applicable"
    || item.endpoint_state === "not_applicable"
  ) invalid();
  const requirements = item.requirements.map(parseRequirement);
  if (new Set(requirements.map((requirement) => requirement.requirement_id)).size !== requirements.length) {
    invalid();
  }
  return {
    ...(item as unknown as McpRegistryInstallOption),
    requirements,
    compatibility: parseCompatibility(item.compatibility),
  };
}

function parseProvenance(value: unknown): McpRegistryProvenance {
  const item = record(value);
  exactKeys(item, [
    "registry",
    "registry_membership_security_review",
    "publisher_namespace",
    "repository_url",
    "repository_source",
    "repository_identity_declared",
    "repository_subfolder_declared",
    "website_url",
    "schema_url",
    "license_state",
  ]);
  if (
    item.registry !== "official_mcp_registry"
    || item.registry_membership_security_review !== "not_claimed"
    || !safeText(item.publisher_namespace, 1, 160)
    || !optionalHttpsUrl(item.repository_url)
    || !(item.repository_source === null || safeText(item.repository_source, 1, 32))
    || typeof item.repository_identity_declared !== "boolean"
    || typeof item.repository_subfolder_declared !== "boolean"
    || !optionalHttpsUrl(item.website_url)
    || !optionalHttpsUrl(item.schema_url)
    || item.license_state !== "not_declared_by_registry_contract"
  ) invalid();
  return item as unknown as McpRegistryProvenance;
}

function parseVersion(value: unknown): McpRegistryVersionSummary {
  const item = record(value);
  exactKeys(item, ["version", "status", "updated_at", "selected"]);
  if (
    !safeText(item.version, 1, 255)
    || !["active", "deprecated", "deleted", "unknown"].includes(String(item.status))
    || !(item.updated_at === null || utcTimestamp(item.updated_at))
    || typeof item.selected !== "boolean"
  ) invalid();
  return item as unknown as McpRegistryVersionSummary;
}

export function parseMcpRegistryServerReview(value: unknown): McpRegistryServerReview {
  const payload = record(value);
  exactKeys(payload, [
    "contract_version",
    "source",
    "server",
    "provenance",
    "versions",
    "version_history_state",
    "options",
    "plan_revision",
    "partial",
    "management_state",
    "install_action",
    "uninstall_action",
    "review_truth",
  ]);
  const source = record(payload.source);
  exactKeys(source, ["registry", "base_url", "fetched_at", "delivery", "cache_age_seconds"]);
  if (
    payload.contract_version !== "mcp-registry-server-review.v1"
    || source.registry !== "official_mcp_registry"
    || source.base_url !== "https://registry.modelcontextprotocol.io"
    || !utcTimestamp(source.fetched_at)
    || source.delivery !== "live"
    || source.cache_age_seconds !== 0
    || !Array.isArray(payload.versions)
    || payload.versions.length > 20
    || !["live", "partial", "unavailable"].includes(String(payload.version_history_state))
    || !Array.isArray(payload.options)
    || payload.options.length > 16
    || typeof payload.plan_revision !== "string"
    || !/^[0-9a-f]{64}$/u.test(payload.plan_revision)
    || typeof payload.partial !== "boolean"
    || (payload.version_history_state !== "live" && payload.partial !== true)
    || payload.management_state !== "not_managed"
    || payload.install_action !== "unavailable"
    || payload.uninstall_action !== "not_applicable"
    || payload.review_truth !== "preview_only_no_install_or_connection_authority"
  ) invalid();
  const server = parseMcpRegistryServer(payload.server);
  const provenance = parseProvenance(payload.provenance);
  if (provenance.publisher_namespace !== server.publisher) invalid();
  const versions = payload.versions.map(parseVersion);
  if (
    new Set(versions.map((item) => item.version)).size !== versions.length
    || versions.filter((item) => item.selected).length !== 1
    || versions.find((item) => item.selected)?.version !== server.version
  ) invalid();
  const options = payload.options.map(parseInstallOption);
  if (new Set(options.map((item) => item.option_id)).size !== options.length) invalid();
  return {
    contract_version: "mcp-registry-server-review.v1",
    source: source as unknown as McpRegistryServerReview["source"],
    server,
    provenance,
    versions,
    version_history_state: payload.version_history_state as McpRegistryServerReview["version_history_state"],
    options,
    plan_revision: payload.plan_revision,
    partial: payload.partial,
    management_state: "not_managed",
    install_action: "unavailable",
    uninstall_action: "not_applicable",
    review_truth: "preview_only_no_install_or_connection_authority",
  };
}
