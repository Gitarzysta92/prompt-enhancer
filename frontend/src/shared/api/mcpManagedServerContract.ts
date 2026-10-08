import type {
  McpManagedPermission,
  McpManagedHostProbe,
  McpManagedLifecycleEffect,
  McpManagedLifecyclePreview,
  McpManagedLifecycleReceipt,
  McpManagedLocalCleanupEffect,
  McpManagedLocalCleanupPreview,
  McpManagedLocalCleanupReceipt,
  McpManagedLocalConfigurationInspection,
  McpManagedLocalConfigurationInspectionEffect,
  McpManagedLocalConfigurationInspectionPreview,
  McpManagedLocalConfigurationInspectionReceipt,
  McpManagedLocalUpdateEffect,
  McpManagedLocalUpdatePreview,
  McpManagedLocalUpdateReceipt,
  McpManagedLocalPackageEvidence,
  McpManagedLocalRollbackGeneration,
  McpManagedLocalRollbackEffect,
  McpManagedLocalRollbackPreview,
  McpManagedLocalRollbackReceipt,
  McpManagedLocalRollbackCleanupEffect,
  McpManagedLocalRollbackCleanupPreview,
  McpManagedLocalRollbackCleanupReceipt,
  McpManagedLocalOperationRecoveryEffect,
  McpManagedLocalOperationRecoveryPreview,
  McpManagedLocalOperationRecoveryReceipt,
  McpManagedProbeReceipt,
  McpManagedProjectBinding,
  McpManagedRequirement,
  McpManagedRequirementState,
  McpManagedServer,
  McpManagedServerList,
  McpManagedServerReceipt,
  McpManagedSecretVaultStatus,
  McpManagedReviewedTool,
  McpManagedToolSnapshot,
  McpManagedToolSnapshotSummary,
  McpRegistryReviewRisk,
} from "./contracts";

export class McpManagedServerPayloadError extends Error {
  constructor() {
    super("MCP managed-server response was invalid");
    this.name = "McpManagedServerPayloadError";
  }
}

function fail(): never {
  throw new McpManagedServerPayloadError();
}

function row(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).sort().join("\u0000") === [...keys].sort().join("\u0000");
}

function boundedText(value: unknown, min: number, max: number): value is string {
  return typeof value === "string"
    && value.length >= min
    && value.length <= max
    && value.trim() === value
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): value is T {
  return typeof value === "string" && values.includes(value as T);
}

const ID = /^[0-9a-f]{32}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;
const NAME = /^[A-Za-z0-9.-]{1,160}\/[A-Za-z0-9._-]{1,80}$/u;
function endpointHost(value: unknown): value is string {
  return boundedText(value, 1, 255)
    && !/[\s/?#@]/u.test(value)
    && !value.includes("\\");
}
const PERMISSIONS: readonly McpManagedPermission[] = [
  "process_spawn",
  "filesystem_read",
  "filesystem_write",
  "network_egress",
  "credential_use",
];
const RISKS: readonly McpRegistryReviewRisk[] = [
  "downloads_package",
  "executes_local_code",
  "package_integrity_not_declared",
  "command_arguments_declared",
  "filesystem_input_declared",
  "credential_input_declared",
  "remote_network_egress",
  "insecure_remote_transport",
];
const REQUIREMENT_STATES: readonly McpManagedRequirementState[] = [
  "publisher_value_declared",
  "registry_default_declared",
  "value_required",
  "value_pending_store",
  "value_stored",
  "value_store_failed",
  "value_pending_removal",
  "value_cleanup_required",
  "optional_unset",
  "secret_missing",
  "secret_pending_store",
  "secret_stored",
  "secret_store_failed",
  "secret_pending_removal",
  "secret_cleanup_required",
];

const PROBE_ACTIONS = [
  "available_native_confirmation_required",
  "unavailable_install_required",
  "unavailable_configuration_required",
  "unavailable_option_unsupported",
  "not_applicable_verified_during_install",
] as const;
const INSTALL_ACTIONS = [
  "available_native_confirmation_required",
  "unavailable_compatibility_check_required",
  "unavailable_configuration_required",
  "unavailable_package_registry_not_supported",
  "unavailable_package_integrity_required",
  "unavailable_local_transport_unsupported",
  "unavailable_configuration_inspection_required",
  "unavailable_cleanup_required",
  "unavailable_operation_in_progress",
  "not_applicable_already_installed",
] as const;
const UNINSTALL_ACTIONS = [
  "available_native_confirmation_required",
  "not_applicable_not_installed",
  "unavailable_cleanup_required",
  "unavailable_operation_in_progress",
] as const;
const LIFECYCLE_EFFECTS: readonly McpManagedLifecycleEffect[] = [
  "persist_remote_activation",
  "remove_remote_activation",
  "download_exact_package",
  "verify_artifact_sha256",
  "stage_isolated_package",
  "execute_bounded_compatibility_probe",
  "stop_and_verify_process_tree",
  "publish_verified_package",
  "verify_installed_tree_digest",
  "quarantine_verified_package",
  "remove_quarantined_package",
  "no_package_change",
  "no_process_start",
  "no_connection_retained",
  "no_tool_authority",
];
const LOCAL_CONFIGURATION_INSPECTION_EFFECTS: readonly McpManagedLocalConfigurationInspectionEffect[] = [
  "download_exact_package",
  "verify_artifact_sha256",
  "inspect_manifest_configuration",
  "discard_inspection_archive",
  "persist_content_free_configuration_schema",
  "revoke_project_bindings_if_permissions_expand",
  "no_configuration_values_persisted",
  "no_process_start",
  "no_connection_retained",
  "no_tool_authority",
];

function parseProbe(value: unknown): McpManagedHostProbe {
  const item = row(value);
  if (!exactKeys(item, [
    "request_id", "checked_at", "transport", "protocol_version", "tool_count",
    "schema_digest", "elapsed_ms", "connection_state", "process_started",
    "process_tree_cleanup", "tool_names_persisted", "tool_schemas_persisted",
    "tool_results_requested", "tool_authority_granted",
  ])
    || typeof item.request_id !== "string" || !ID.test(item.request_id)
    || !boundedText(item.checked_at, 20, 40) || Number.isNaN(Date.parse(item.checked_at))
    || !oneOf(item.transport, ["stdio", "streamable-http", "sse"])
    || typeof item.protocol_version !== "string" || !/^20\d{2}-\d{2}-\d{2}$/u.test(item.protocol_version)
    || !Number.isInteger(item.tool_count) || Number(item.tool_count) < 0 || Number(item.tool_count) > 256
    || typeof item.schema_digest !== "string" || !DIGEST.test(item.schema_digest)
    || !Number.isInteger(item.elapsed_ms) || Number(item.elapsed_ms) < 0 || Number(item.elapsed_ms) > 120_000
    || item.connection_state !== "closed_after_probe"
    || typeof item.process_started !== "boolean"
    || !oneOf(item.process_tree_cleanup, ["verified", "not_applicable"])
    || typeof item.tool_names_persisted !== "boolean"
    || typeof item.tool_schemas_persisted !== "boolean"
    || item.tool_names_persisted !== item.tool_schemas_persisted
    || item.tool_results_requested !== false
    || item.tool_authority_granted !== false
    || (item.process_started ? item.process_tree_cleanup !== "verified" : item.process_tree_cleanup !== "not_applicable")) fail();
  return item as unknown as McpManagedHostProbe;
}

function parseLocalPackageEvidence(value: unknown): McpManagedLocalPackageEvidence {
  const item = row(value);
  if (!exactKeys(item, [
    "artifact_sha256", "artifact_bytes", "tree_digest", "manifest_digest",
    "manifest_version", "license_state", "runtime_kind", "runtime_version",
  ])
    || typeof item.artifact_sha256 !== "string" || !DIGEST.test(item.artifact_sha256)
    || !Number.isInteger(item.artifact_bytes) || Number(item.artifact_bytes) < 1
    || Number(item.artifact_bytes) > 64 * 1024 * 1024
    || typeof item.tree_digest !== "string" || !DIGEST.test(item.tree_digest)
    || typeof item.manifest_digest !== "string" || !DIGEST.test(item.manifest_digest)
    || !oneOf(item.manifest_version, ["0.3", "0.4"])
    || item.license_state !== "declared"
    || !oneOf(item.runtime_kind, ["node", "python", "binary"])
    || (item.runtime_version !== null && !boundedText(item.runtime_version, 1, 64))
    || ((item.runtime_kind === "binary") !== (item.runtime_version === null))) fail();
  return item as unknown as McpManagedLocalPackageEvidence;
}

function parseLocalConfigurationInspection(
  value: unknown,
): McpManagedLocalConfigurationInspection {
  const item = row(value);
  if (!exactKeys(item, [
    "plan_revision", "artifact_sha256", "artifact_bytes", "manifest_digest",
    "manifest_version", "configuration_schema_digest", "requirement_ids",
    "inspected_at", "archive_retained", "process_started",
    "configuration_values_persisted", "manifest_content_persisted",
  ])
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || typeof item.artifact_sha256 !== "string" || !DIGEST.test(item.artifact_sha256)
    || !Number.isInteger(item.artifact_bytes) || Number(item.artifact_bytes) < 1
    || Number(item.artifact_bytes) > 64 * 1024 * 1024
    || typeof item.manifest_digest !== "string" || !DIGEST.test(item.manifest_digest)
    || !oneOf(item.manifest_version, ["0.3", "0.4"])
    || typeof item.configuration_schema_digest !== "string"
    || !DIGEST.test(item.configuration_schema_digest)
    || !Array.isArray(item.requirement_ids) || item.requirement_ids.length > 32
    || item.requirement_ids.some((entry) => typeof entry !== "string" || !ID.test(entry))
    || new Set(item.requirement_ids).size !== item.requirement_ids.length
    || !boundedText(item.inspected_at, 20, 40)
    || Number.isNaN(Date.parse(item.inspected_at as string))
    || item.archive_retained !== false
    || item.process_started !== false
    || item.configuration_values_persisted !== false
    || item.manifest_content_persisted !== false) fail();
  return item as unknown as McpManagedLocalConfigurationInspection;
}

function canonicalPermissions(value: unknown): McpManagedPermission[] {
  if (!Array.isArray(value) || value.length > PERMISSIONS.length) fail();
  if (value.some((item) => !oneOf(item, PERMISSIONS))) fail();
  const permissions = value as McpManagedPermission[];
  if (new Set(permissions).size !== permissions.length) fail();
  const canonical = PERMISSIONS.filter((item) => permissions.includes(item));
  if (canonical.join("\u0000") !== permissions.join("\u0000")) fail();
  return permissions;
}

function parseRollbackGeneration(
  value: unknown,
  serverName: string,
  requiredPermissions: McpManagedPermission[],
): McpManagedLocalRollbackGeneration {
  const item = row(value);
  if (!exactKeys(item, [
    "catalog_id", "server_name", "server_title", "server_version",
    "server_status_at_review", "option_id", "plan_revision", "option_label",
    "registry_type", "package_identifier", "package_version", "runtime_hint",
    "transport", "required_permissions", "risks", "generation_id",
    "local_package_evidence", "probe", "installed_at", "retained_at",
  ])
    || typeof item.catalog_id !== "string" || !ID.test(item.catalog_id)
    || item.server_name !== serverName || typeof item.server_name !== "string" || !NAME.test(item.server_name)
    || !boundedText(item.server_title, 1, 100)
    || !boundedText(item.server_version, 1, 255)
    || !oneOf(item.server_status_at_review, ["active", "deprecated", "deleted"])
    || typeof item.option_id !== "string" || !ID.test(item.option_id)
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !boundedText(item.option_label, 1, 120)
    || item.registry_type !== "mcpb"
    || !boundedText(item.package_identifier, 1, 512)
    || (item.package_version !== null && !boundedText(item.package_version, 1, 255))
    || (item.runtime_hint !== null && !boundedText(item.runtime_hint, 1, 32))
    || item.transport !== "stdio"
    || !Array.isArray(item.risks) || item.risks.length > RISKS.length
    || item.risks.some((risk) => !oneOf(risk, RISKS))
    || new Set(item.risks).size !== item.risks.length
    || typeof item.generation_id !== "string" || !ID.test(item.generation_id)
    || !boundedText(item.installed_at, 20, 40) || Number.isNaN(Date.parse(item.installed_at))
    || !boundedText(item.retained_at, 20, 40) || Number.isNaN(Date.parse(item.retained_at))
    || Date.parse(item.retained_at as string) < Date.parse(item.installed_at as string)) fail();
  const permissions = canonicalPermissions(item.required_permissions);
  if (permissions.join("\u0000") !== requiredPermissions.join("\u0000")) fail();
  const evidence = parseLocalPackageEvidence(item.local_package_evidence);
  const probe = parseProbe(item.probe);
  if (probe.transport !== "stdio" || !probe.process_started
    || probe.process_tree_cleanup !== "verified") fail();
  return {
    ...(item as unknown as McpManagedLocalRollbackGeneration),
    required_permissions: permissions,
    risks: item.risks as McpRegistryReviewRisk[],
    local_package_evidence: evidence,
    probe,
  };
}

function parseRequirement(value: unknown): McpManagedRequirement {
  const item = row(value);
  if (!exactKeys(item, [
    "requirement_id", "location", "name", "required", "secret", "format",
    "user_value_needed", "configuration_state", "secret_vault_provider",
    "value_vault_provider",
  ])
    || typeof item.requirement_id !== "string" || !ID.test(item.requirement_id)
    || !oneOf(item.location, ["runtime_argument", "package_argument", "environment_variable", "transport_header", "remote_variable"])
    || !boundedText(item.name, 1, 128)
    || typeof item.required !== "boolean"
    || typeof item.secret !== "boolean"
    || !oneOf(item.format, ["string", "number", "boolean", "filepath", "unknown"])
    || typeof item.user_value_needed !== "boolean"
    || !oneOf(item.configuration_state, REQUIREMENT_STATES)
    || (item.secret_vault_provider !== null && item.secret_vault_provider !== "windows_credential_manager")
    || (item.value_vault_provider !== null && item.value_vault_provider !== "windows_credential_manager")) fail();
  const secretState = String(item.configuration_state).startsWith("secret_");
  if (item.secret !== secretState) fail();
  if (item.secret
    && ((item.configuration_state === "secret_missing") !== (item.secret_vault_provider === null))) fail();
  if (item.secret && item.value_vault_provider !== null) fail();
  if (!item.secret && item.secret_vault_provider !== null) fail();
  const valueState = String(item.configuration_state).startsWith("value_");
  if (!item.secret && item.user_value_needed !== valueState) fail();
  if (!item.secret && item.user_value_needed
    && ((item.configuration_state === "value_required") !== (item.value_vault_provider === null))) fail();
  if ((!item.user_value_needed || item.secret) && item.value_vault_provider !== null) fail();
  return item as unknown as McpManagedRequirement;
}

function toolText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length >= 1
    && value.length <= maximum
    && value.trim() === value
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value);
}

function parseToolSchema(value: unknown, input: boolean): Record<string, unknown> {
  const root = row(value);
  if (input && root.type !== undefined && root.type !== "object") fail();
  const seen = new WeakSet<object>();
  const stack: Array<{ value: unknown; depth: number }> = [{ value: root, depth: 1 }];
  let nodes = 0;
  while (stack.length > 0) {
    const current = stack.pop();
    if (current === undefined) fail();
    nodes += 1;
    if (nodes > 8_192 || current.depth > 32) fail();
    const candidate = current.value;
    if (candidate === null || typeof candidate === "string" || typeof candidate === "boolean") continue;
    if (typeof candidate === "number") {
      if (!Number.isFinite(candidate)) fail();
      continue;
    }
    if (typeof candidate !== "object") fail();
    if (seen.has(candidate)) fail();
    seen.add(candidate);
    if (Array.isArray(candidate)) {
      if (candidate.length > 1_024) fail();
      candidate.forEach((child) => stack.push({ value: child, depth: current.depth + 1 }));
      continue;
    }
    const entries = Object.entries(candidate as Record<string, unknown>);
    if (entries.length > 1_024) fail();
    for (const [key, child] of entries) {
      if (key.length > 256) fail();
      if (key === "$ref" && (typeof child !== "string" || child.length > 1_024 || !child.startsWith("#/"))) fail();
      if (key === "$schema" && (typeof child !== "string" || ![
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/schema#",
      ].includes(child))) fail();
      stack.push({ value: child, depth: current.depth + 1 });
    }
  }
  let encoded: string;
  try {
    encoded = JSON.stringify(root);
  } catch {
    fail();
  }
  if (new TextEncoder().encode(encoded).byteLength > 262_144) fail();
  return root;
}

function projectToolSchemaForModel(
  schema: Record<string, unknown>,
): Record<string, unknown> {
  const scalarKeys = new Set([
    "$ref", "$schema", "type", "enum", "const", "required",
    "dependentRequired", "minLength", "maxLength", "pattern", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minItems", "maxItems", "uniqueItems", "minProperties",
    "maxProperties",
  ]);
  const mappingKeys = new Set([
    "properties", "patternProperties", "$defs", "dependentSchemas",
  ]);
  const schemaKeys = new Set([
    "items", "additionalProperties", "unevaluatedProperties", "contains",
    "propertyNames", "not", "if", "then", "else",
  ]);
  const sequenceKeys = new Set(["allOf", "anyOf", "oneOf", "prefixItems"]);
  const project = (value: Record<string, unknown>): Record<string, unknown> => {
    const result: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      if (scalarKeys.has(key)) {
        result[key] = child;
      } else if (mappingKeys.has(key) && child !== null
        && typeof child === "object" && !Array.isArray(child)) {
        result[key] = Object.fromEntries(
          Object.entries(child).flatMap(([name, nested]) => (
            nested !== null && typeof nested === "object" && !Array.isArray(nested)
              ? [[name, project(nested as Record<string, unknown>)]]
              : []
          )),
        );
      } else if (schemaKeys.has(key)) {
        if (typeof child === "boolean") result[key] = child;
        else if (child !== null && typeof child === "object" && !Array.isArray(child)) {
          result[key] = project(child as Record<string, unknown>);
        }
      } else if (sequenceKeys.has(key) && Array.isArray(child)) {
        result[key] = child.flatMap((nested) => (
          nested !== null && typeof nested === "object" && !Array.isArray(nested)
            ? [project(nested as Record<string, unknown>)]
            : []
        ));
      }
    }
    return Object.keys(result).length === 0 ? { type: "object" } : result;
  };
  return project(schema);
}

function canonicalToolSchema(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalToolSchema).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalToolSchema(child)}`)
      .join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) fail();
  return encoded;
}

function parseReviewedTool(value: unknown): McpManagedReviewedTool {
  const item = row(value);
  if (!exactKeys(item, [
    "tool_id", "name", "title", "description", "model_alias", "input_schema",
    "input_schema_digest", "model_input_schema", "output_schema",
    "output_schema_digest", "contract_digest",
  ])
    || typeof item.tool_id !== "string" || !ID.test(item.tool_id)
    || typeof item.name !== "string" || !/^[A-Za-z0-9_.:/-]{1,128}$/u.test(item.name)
    || (item.title !== null && !toolText(item.title, 256))
    || (item.description !== null && !toolText(item.description, 4_096))
    || typeof item.model_alias !== "string"
    || !/^[A-Za-z0-9_-]{1,64}$/u.test(item.model_alias)
    || typeof item.input_schema_digest !== "string" || !DIGEST.test(item.input_schema_digest)
    || (item.output_schema_digest !== null
      && (typeof item.output_schema_digest !== "string" || !DIGEST.test(item.output_schema_digest)))
    || typeof item.contract_digest !== "string" || !DIGEST.test(item.contract_digest)
    || item.tool_id !== item.contract_digest.slice(0, 32)
    || ((item.output_schema === null) !== (item.output_schema_digest === null))) fail();
  const inputSchema = parseToolSchema(item.input_schema, true);
  const modelInputSchema = parseToolSchema(item.model_input_schema, true);
  if (canonicalToolSchema(modelInputSchema)
    !== canonicalToolSchema(projectToolSchemaForModel(inputSchema))) fail();
  return {
    ...(item as unknown as McpManagedReviewedTool),
    input_schema: inputSchema,
    model_input_schema: modelInputSchema,
    output_schema: item.output_schema === null ? null : parseToolSchema(item.output_schema, false),
  };
}

function parseToolSnapshotSummary(value: unknown): McpManagedToolSnapshotSummary {
  const item = row(value);
  if (!exactKeys(item, [
    "snapshot_id", "plan_revision", "source", "source_tree_digest",
    "source_manifest_digest",
    "protocol_version", "tool_count", "schema_digest", "reviewed_at",
    "tool_names_retained_locally", "tool_schemas_retained_locally",
    "connection_retained", "tool_authority_granted",
  ])
    || typeof item.snapshot_id !== "string" || !ID.test(item.snapshot_id)
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.source, ["remote_probe", "local_package_probe"])
    || (item.source_tree_digest !== null
      && (typeof item.source_tree_digest !== "string" || !DIGEST.test(item.source_tree_digest)))
    || (item.source_manifest_digest !== null
      && (typeof item.source_manifest_digest !== "string" || !DIGEST.test(item.source_manifest_digest)))
    || (item.source === "local_package_probe") !== (item.source_tree_digest !== null)
    || (item.source === "local_package_probe") !== (item.source_manifest_digest !== null)
    || typeof item.protocol_version !== "string" || !/^20\d{2}-\d{2}-\d{2}$/u.test(item.protocol_version)
    || !Number.isInteger(item.tool_count) || Number(item.tool_count) < 0 || Number(item.tool_count) > 256
    || typeof item.schema_digest !== "string" || !DIGEST.test(item.schema_digest)
    || !boundedText(item.reviewed_at, 20, 40) || Number.isNaN(Date.parse(item.reviewed_at))
    || item.tool_names_retained_locally !== true
    || item.tool_schemas_retained_locally !== true
    || item.connection_retained !== false
    || item.tool_authority_granted !== false) fail();
  return item as unknown as McpManagedToolSnapshotSummary;
}

export function parseMcpManagedToolSnapshot(value: unknown): McpManagedToolSnapshot {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "management_id", "snapshot_id", "plan_revision", "source",
    "source_tree_digest", "source_manifest_digest", "protocol_version",
    "tool_count", "schema_digest",
    "reviewed_at", "tool_names_retained_locally", "tool_schemas_retained_locally",
    "connection_retained", "tool_authority_granted", "tools",
  ])
    || item.contract_version !== "mcp-managed-tool-snapshot.v1"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Array.isArray(item.tools) || item.tools.length > 256) fail();
  const summaryInput = { ...item };
  delete summaryInput.contract_version;
  delete summaryInput.management_id;
  delete summaryInput.tools;
  const summary = parseToolSnapshotSummary(summaryInput);
  const tools = item.tools.map(parseReviewedTool);
  const encoder = new TextEncoder();
  const schemaBytes = tools.reduce((total, tool) => total
    + encoder.encode(JSON.stringify(tool.input_schema)).byteLength
    + (tool.output_schema === null
      ? 0
      : encoder.encode(JSON.stringify(tool.output_schema)).byteLength), 0);
  const modelSchemaBytes = tools.reduce((total, tool) => total
    + encoder.encode(JSON.stringify(tool.model_input_schema)).byteLength, 0);
  const metadataBytes = tools.reduce((total, tool) => total
    + encoder.encode(JSON.stringify({
      name: tool.name,
      title: tool.title,
      description: tool.description,
    })).byteLength, 0);
  if (tools.length !== summary.tool_count
    || schemaBytes > 1_048_576
    || modelSchemaBytes > 1_048_576
    || metadataBytes > 512 * 1_024
    || new Set(tools.map((tool) => tool.tool_id)).size !== tools.length
    || new Set(tools.map((tool) => tool.name)).size !== tools.length
    || new Set(tools.map((tool) => tool.model_alias)).size !== tools.length
    || tools.map((tool) => tool.name).join("\u0000")
      !== [...tools].sort((left, right) => left.name.localeCompare(right.name)).map((tool) => tool.name).join("\u0000")) fail();
  return {
    contract_version: "mcp-managed-tool-snapshot.v1",
    management_id: item.management_id,
    ...summary,
    tools,
  };
}

function parseBinding(
  value: unknown,
  requiredPermissions: McpManagedPermission[],
): McpManagedProjectBinding {
  const item = row(value);
  if (!exactKeys(item, [
    "project_id", "project_name", "enabled", "required_permissions",
    "granted_permissions", "admitted_tool_ids", "tool_snapshot_id",
    "admission_state", "effective_state", "created_at", "updated_at", "revision",
  ])
    || typeof item.project_id !== "string" || !ID.test(item.project_id)
    || !boundedText(item.project_name, 1, 120)
    || typeof item.enabled !== "boolean"
    || !Array.isArray(item.admitted_tool_ids) || item.admitted_tool_ids.length > 256
    || item.admitted_tool_ids.some((toolId) => typeof toolId !== "string" || !ID.test(toolId))
    || new Set(item.admitted_tool_ids).size !== item.admitted_tool_ids.length
    || item.admitted_tool_ids.join("\u0000") !== [...item.admitted_tool_ids].sort().join("\u0000")
    || (item.tool_snapshot_id !== null
      && (typeof item.tool_snapshot_id !== "string" || !ID.test(item.tool_snapshot_id)))
    || !oneOf(item.admission_state, ["disabled", "review_required", "admitted"])
    || !oneOf(item.effective_state, [
      "disabled", "inactive_tool_review_required", "inactive_install_required",
      "inactive_host_unavailable",
    ])
    || !boundedText(item.created_at, 20, 40)
    || !boundedText(item.updated_at, 20, 40)
    || !Number.isInteger(item.revision) || Number(item.revision) < 1) fail();
  const required = canonicalPermissions(item.required_permissions);
  const granted = canonicalPermissions(item.granted_permissions);
  if (required.join("\u0000") !== requiredPermissions.join("\u0000")) fail();
  if (Number.isNaN(Date.parse(item.created_at as string))
    || Number.isNaN(Date.parse(item.updated_at as string))
    || Date.parse(item.updated_at as string) < Date.parse(item.created_at as string)) fail();
  if (item.enabled) {
    if (granted.join("\u0000") !== required.join("\u0000")) fail();
    if (item.admission_state === "admitted") {
      if (item.admitted_tool_ids.length === 0 || item.tool_snapshot_id === null
        || !oneOf(item.effective_state, ["inactive_install_required", "inactive_host_unavailable"])) fail();
    } else if (item.admission_state !== "review_required"
      || item.admitted_tool_ids.length !== 0 || item.tool_snapshot_id !== null
      || item.effective_state !== "inactive_tool_review_required") fail();
  } else if (item.effective_state !== "disabled" || granted.length !== 0
    || item.admitted_tool_ids.length !== 0 || item.tool_snapshot_id !== null
    || item.admission_state !== "disabled") fail();
  return { ...(item as unknown as McpManagedProjectBinding), required_permissions: required, granted_permissions: granted };
}

export function parseMcpManagedServer(value: unknown): McpManagedServer {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "management_id", "catalog_id", "server_name",
    "server_title", "server_version", "server_status_at_review", "option_id",
    "plan_revision", "option_kind", "option_label", "registry_type",
    "package_identifier", "package_version", "runtime_hint", "transport",
    "endpoint_host", "endpoint_state", "secure_transport", "required_permissions",
    "risks", "requirements", "project_bindings", "created_at", "updated_at",
    "revision", "lifecycle_state", "installation_state", "installation_kind",
    "operation_state", "installed_plan_revision", "installed_at",
    "local_package_evidence", "local_configuration_inspection", "rollback_generation",
    "process_tree_cleanup", "host_state",
    "health_state", "last_health_checked_at", "last_probe", "tool_snapshot",
    "tool_review_state", "update_state",
    "latest_available_version", "tool_routing_state", "install_action",
    "uninstall_action", "probe_action",
  ])
    || item.contract_version !== "mcp-managed-server.v2"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || typeof item.catalog_id !== "string" || !ID.test(item.catalog_id)
    || typeof item.server_name !== "string" || !NAME.test(item.server_name)
    || !boundedText(item.server_title, 1, 100)
    || !boundedText(item.server_version, 1, 255)
    || !oneOf(item.server_status_at_review, ["active", "deprecated", "deleted"])
    || typeof item.option_id !== "string" || !ID.test(item.option_id)
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.option_kind, ["local_package", "remote_server"])
    || !boundedText(item.option_label, 1, 120)
    || (item.registry_type !== null && !boundedText(item.registry_type, 1, 32))
    || (item.package_identifier !== null && !boundedText(item.package_identifier, 1, 512))
    || (item.package_version !== null && !boundedText(item.package_version, 1, 255))
    || (item.runtime_hint !== null && !boundedText(item.runtime_hint, 1, 32))
    || !oneOf(item.transport, ["stdio", "streamable-http", "sse", "unknown"])
    || (item.endpoint_host !== null && !endpointHost(item.endpoint_host))
    || !oneOf(item.endpoint_state, ["not_applicable", "fixed_host", "template_requires_configuration", "invalid"])
    || (item.secure_transport !== null && typeof item.secure_transport !== "boolean")
    || !Array.isArray(item.risks) || item.risks.length > RISKS.length
    || item.risks.some((risk) => !oneOf(risk, RISKS))
    || new Set(item.risks).size !== item.risks.length
    || !Array.isArray(item.requirements) || item.requirements.length > 64
    || !Array.isArray(item.project_bindings) || item.project_bindings.length > 64
    || !boundedText(item.created_at, 20, 40)
    || !boundedText(item.updated_at, 20, 40)
    || !Number.isInteger(item.revision) || Number(item.revision) < 1
    || !oneOf(item.lifecycle_state, ["planned", "installed", "cleanup_required"])
    || !oneOf(item.installation_state, ["not_installed", "installed", "cleanup_required"])
    || !oneOf(item.installation_kind, ["none", "remote_activation", "local_package"])
    || !oneOf(item.operation_state, ["idle", "installing", "updating", "uninstalling", "rolling_back", "cleaning_up", "cleanup_required"])
    || (item.installed_plan_revision !== null
      && (typeof item.installed_plan_revision !== "string" || !DIGEST.test(item.installed_plan_revision)))
    || (item.installed_at !== null
      && (!boundedText(item.installed_at, 20, 40) || Number.isNaN(Date.parse(item.installed_at))))
    || !oneOf(item.process_tree_cleanup, ["not_applicable", "verified", "unconfirmed"])
    || item.host_state !== "not_started"
    || !oneOf(item.health_state, ["not_checked", "compatible"])
    || (item.last_health_checked_at !== null && !boundedText(item.last_health_checked_at, 20, 40))
    || (item.last_health_checked_at !== null && Number.isNaN(Date.parse(item.last_health_checked_at)))
    || !oneOf(item.tool_review_state, ["probe_required", "reviewable"])
    || item.update_state !== "not_checked"
    || item.latest_available_version !== null
    || item.tool_routing_state !== "inactive"
    || !oneOf(item.install_action, INSTALL_ACTIONS)
    || !oneOf(item.uninstall_action, UNINSTALL_ACTIONS)
    || !oneOf(item.probe_action, PROBE_ACTIONS)) fail();
  if (Number.isNaN(Date.parse(item.created_at as string))
    || Number.isNaN(Date.parse(item.updated_at as string))
    || Date.parse(item.updated_at as string) < Date.parse(item.created_at as string)) fail();
  if (item.option_kind === "local_package") {
    if (item.registry_type === null || item.package_identifier === null
      || item.endpoint_state !== "not_applicable" || item.secure_transport !== null) fail();
  } else if (item.registry_type !== null || item.package_identifier !== null
    || item.package_version !== null || item.runtime_hint !== null
    || item.endpoint_state === "not_applicable") fail();
  if (item.endpoint_state === "fixed_host") {
    if (item.endpoint_host === null || item.secure_transport === null) fail();
  } else if (item.endpoint_host !== null || (item.endpoint_state !== "not_applicable" && item.secure_transport !== null)) fail();
  const requiredPermissions = canonicalPermissions(item.required_permissions);
  const requirements = item.requirements.map(parseRequirement);
  if (new Set(requirements.map((entry) => entry.requirement_id)).size !== requirements.length) fail();
  const projectBindings = item.project_bindings.map((entry) => parseBinding(entry, requiredPermissions));
  if (new Set(projectBindings.map((entry) => entry.project_id)).size !== projectBindings.length) fail();
  const lastProbe = item.last_probe === null ? null : parseProbe(item.last_probe);
  const toolSnapshot = item.tool_snapshot === null
    ? null
    : parseToolSnapshotSummary(item.tool_snapshot);
  const localPackageEvidence = item.local_package_evidence === null
    ? null
    : parseLocalPackageEvidence(item.local_package_evidence);
  const localConfigurationInspection = item.local_configuration_inspection === null
    ? null
    : parseLocalConfigurationInspection(item.local_configuration_inspection);
  const rollbackGeneration = item.rollback_generation === null
    ? null
    : parseRollbackGeneration(item.rollback_generation, item.server_name as string, requiredPermissions);
  if (item.option_kind === "remote_server"
    && (rollbackGeneration !== null || localConfigurationInspection !== null)) fail();
  if (localConfigurationInspection !== null) {
    const requirementIds = new Set(requirements.map((entry) => entry.requirement_id));
    if (item.option_kind !== "local_package"
      || localConfigurationInspection.plan_revision !== item.plan_revision
      || localConfigurationInspection.requirement_ids.some((entry) => !requirementIds.has(entry))) fail();
    if (item.installation_state === "installed"
      && (localPackageEvidence === null
        || localConfigurationInspection.artifact_sha256 !== localPackageEvidence.artifact_sha256
        || localConfigurationInspection.manifest_digest !== localPackageEvidence.manifest_digest
        || localConfigurationInspection.manifest_version !== localPackageEvidence.manifest_version)) fail();
  }
  if (lastProbe === null) {
    if (item.health_state !== "not_checked" || item.last_health_checked_at !== null) fail();
  } else if (item.health_state !== "compatible"
    || item.last_health_checked_at !== lastProbe.checked_at
    || item.transport !== lastProbe.transport) fail();
  if (toolSnapshot === null) {
    if (item.tool_review_state !== "probe_required"
      || projectBindings.some((binding) => binding.admission_state === "admitted")) fail();
  } else {
    if (item.tool_review_state !== "reviewable" || lastProbe === null
      || toolSnapshot.plan_revision !== item.plan_revision
      || toolSnapshot.protocol_version !== lastProbe.protocol_version
      || toolSnapshot.tool_count !== lastProbe.tool_count
      || toolSnapshot.schema_digest !== lastProbe.schema_digest
      || !lastProbe.tool_names_persisted || !lastProbe.tool_schemas_persisted
      || projectBindings.some((binding) => binding.admission_state === "admitted"
        && binding.tool_snapshot_id !== toolSnapshot.snapshot_id)) fail();
    if (toolSnapshot.source === "local_package_probe") {
      if (item.option_kind !== "local_package" || localPackageEvidence === null
        || toolSnapshot.source_tree_digest !== localPackageEvidence.tree_digest
        || toolSnapshot.source_manifest_digest !== localPackageEvidence.manifest_digest) fail();
    } else if (item.option_kind !== "remote_server") fail();
  }
  const blockedStates: readonly McpManagedRequirementState[] = [
    "value_required", "value_pending_store", "value_store_failed",
    "value_pending_removal", "value_cleanup_required",
    "secret_missing", "secret_pending_store", "secret_store_failed",
    "secret_pending_removal", "secret_cleanup_required",
  ];
  const expectedProbeAction = item.option_kind === "local_package"
    ? item.installation_state === "installed" && lastProbe !== null
      ? "not_applicable_verified_during_install"
      : "unavailable_install_required"
    : !["streamable-http", "sse"].includes(item.transport as string)
      || item.endpoint_state !== "fixed_host" || item.secure_transport !== true
      ? "unavailable_option_unsupported"
      : requirements.some((entry) => blockedStates.includes(entry.configuration_state))
        ? "unavailable_configuration_required"
        : "available_native_confirmation_required";
  if (item.probe_action !== expectedProbeAction) fail();
  if (item.installation_state === "not_installed") {
    if (item.lifecycle_state !== "planned" || item.installation_kind !== "none"
      || item.installed_plan_revision !== null || item.installed_at !== null
      || localPackageEvidence !== null || rollbackGeneration !== null
      || item.process_tree_cleanup !== "not_applicable") fail();
  } else if (item.installation_state === "installed") {
    if (item.lifecycle_state !== "installed" || item.installation_kind === "none"
      || item.installed_plan_revision !== item.plan_revision || item.installed_at === null) fail();
    if (item.installation_kind === "remote_activation"
      && (item.option_kind !== "remote_server" || item.process_tree_cleanup !== "not_applicable"
        || localPackageEvidence !== null || rollbackGeneration !== null)) fail();
    if (item.installation_kind === "local_package"
      && (item.option_kind !== "local_package" || item.process_tree_cleanup !== "verified"
        || localPackageEvidence === null || lastProbe === null || !lastProbe.process_started
        || lastProbe.process_tree_cleanup !== "verified")) fail();
    if (rollbackGeneration !== null
      && (rollbackGeneration.plan_revision === item.plan_revision
        || rollbackGeneration.server_name !== item.server_name)) fail();
  } else if (item.lifecycle_state !== "cleanup_required"
    || item.operation_state !== "cleanup_required") fail();
  const expectedInstallAction = item.installation_state === "cleanup_required"
    ? "unavailable_cleanup_required"
    : item.operation_state !== "idle"
      ? "unavailable_operation_in_progress"
      : item.installation_state === "installed"
        ? "not_applicable_already_installed"
        : item.option_kind === "local_package"
          ? item.registry_type !== "mcpb"
            ? "unavailable_package_registry_not_supported"
            : item.risks.includes("package_integrity_not_declared")
              ? "unavailable_package_integrity_required"
              : item.transport !== "stdio"
                ? "unavailable_local_transport_unsupported"
                : localConfigurationInspection === null
                  ? "unavailable_configuration_inspection_required"
                  : requirements.some((entry) => blockedStates.includes(entry.configuration_state))
                    ? "unavailable_configuration_required"
                    : "available_native_confirmation_required"
          : requirements.some((entry) => blockedStates.includes(entry.configuration_state))
            ? "unavailable_configuration_required"
            : item.health_state !== "compatible"
              ? "unavailable_compatibility_check_required"
              : "available_native_confirmation_required";
  if (item.install_action !== expectedInstallAction) fail();
  const expectedUninstallAction = item.installation_state === "cleanup_required"
    ? "unavailable_cleanup_required"
    : item.operation_state !== "idle"
      ? "unavailable_operation_in_progress"
      : item.installation_state === "installed"
        ? "available_native_confirmation_required"
        : "not_applicable_not_installed";
  if (item.uninstall_action !== expectedUninstallAction) fail();
  return {
    ...(item as unknown as McpManagedServer),
    required_permissions: requiredPermissions,
    risks: item.risks as McpRegistryReviewRisk[],
    requirements,
    project_bindings: projectBindings,
    local_package_evidence: localPackageEvidence,
    local_configuration_inspection: localConfigurationInspection,
    rollback_generation: rollbackGeneration,
    last_probe: lastProbe,
    tool_snapshot: toolSnapshot,
  };
}

function parseVault(value: unknown): McpManagedSecretVaultStatus {
  const item = row(value);
  if (!exactKeys(item, [
    "provider", "availability", "values_in_database", "values_in_api_responses",
    "values_in_model_context",
  ])
    || !oneOf(item.provider, ["windows_credential_manager", "unavailable"])
    || !oneOf(item.availability, ["available", "unavailable"])
    || item.values_in_database !== false
    || item.values_in_api_responses !== false
    || item.values_in_model_context !== false
    || ((item.provider === "unavailable") !== (item.availability === "unavailable"))) fail();
  return item as unknown as McpManagedSecretVaultStatus;
}

export function parseMcpManagedServerList(value: unknown): McpManagedServerList {
  const item = row(value);
  if (!exactKeys(item, ["contract_version", "servers", "total", "secret_vault", "execution_truth"])
    || item.contract_version !== "mcp-managed-server.v2"
    || !Array.isArray(item.servers) || item.servers.length > 64
    || !Number.isInteger(item.total) || Number(item.total) !== item.servers.length
    || item.execution_truth !== "reviewed_tool_admission_without_persistent_host_or_tool_authority") fail();
  const servers = item.servers.map(parseMcpManagedServer);
  if (new Set(servers.map((server) => server.management_id)).size !== servers.length) fail();
  return {
    contract_version: "mcp-managed-server.v2",
    servers,
    total: item.total as number,
    secret_vault: parseVault(item.secret_vault),
    execution_truth: "reviewed_tool_admission_without_persistent_host_or_tool_authority",
  };
}

export function parseMcpManagedServerReceipt(value: unknown): McpManagedServerReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "server", "idempotent_replay", "process_started",
    "endpoint_connected", "package_changed", "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-server.v2"
    || typeof item.idempotent_replay !== "boolean"
    || item.process_started !== false
    || item.endpoint_connected !== false
    || item.package_changed !== false
    || item.tool_authority_granted !== false) fail();
  return {
    contract_version: "mcp-managed-server.v2",
    server: parseMcpManagedServer(item.server),
    idempotent_replay: item.idempotent_replay,
    process_started: false,
    endpoint_connected: false,
    package_changed: false,
    tool_authority_granted: false,
  };
}

export function parseMcpManagedProbeReceipt(value: unknown): McpManagedProbeReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "server", "probe", "idempotent_replay",
    "endpoint_connection_attempted", "connection_retained", "package_changed",
    "tool_results_requested", "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-server.v2"
    || typeof item.idempotent_replay !== "boolean"
    || item.endpoint_connection_attempted !== true
    || item.connection_retained !== false
    || item.package_changed !== false
    || item.tool_results_requested !== false
    || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  const probe = parseProbe(item.probe);
  if (server.last_probe === null
    || server.last_probe.request_id !== probe.request_id
    || server.last_probe.schema_digest !== probe.schema_digest
    || server.last_probe.checked_at !== probe.checked_at) fail();
  return {
    contract_version: "mcp-managed-server.v2",
    server,
    probe,
    idempotent_replay: item.idempotent_replay,
    endpoint_connection_attempted: true,
    connection_retained: false,
    package_changed: false,
    tool_results_requested: false,
    tool_authority_granted: false,
  };
}

export function parseMcpManagedLifecyclePreview(value: unknown): McpManagedLifecyclePreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "plan_revision", "installation_kind", "availability", "reason", "effects",
    "preview_digest", "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-lifecycle-preview.v1"
    || !oneOf(item.action, ["install", "uninstall"])
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.installation_kind, ["remote_activation", "local_package"])
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, [
      "ready_for_native_confirmation", "compatibility_check_required",
      "configuration_required", "configuration_inspection_required",
      "package_registry_not_supported",
      "package_integrity_required", "local_transport_unsupported",
      "local_installer_unavailable", "local_uninstaller_unavailable",
      "already_installed", "not_installed", "cleanup_required",
      "operation_in_progress",
    ])
    || !Array.isArray(item.effects) || item.effects.length < 4 || item.effects.length > 10
    || item.effects.some((effect) => !oneOf(effect, LIFECYCLE_EFFECTS))
    || new Set(item.effects).size !== item.effects.length
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available") !== (item.reason === "ready_for_native_confirmation")) fail();
  const expectedEffects: McpManagedLifecycleEffect[] = item.installation_kind === "local_package"
    ? item.action === "install"
      ? [
        "download_exact_package", "verify_artifact_sha256", "stage_isolated_package",
        "execute_bounded_compatibility_probe", "stop_and_verify_process_tree",
        "publish_verified_package", "no_connection_retained", "no_tool_authority",
      ]
      : [
        "verify_installed_tree_digest", "quarantine_verified_package",
        "remove_quarantined_package", "no_process_start", "no_connection_retained",
        "no_tool_authority",
      ]
    : [
      item.action === "install" ? "persist_remote_activation" : "remove_remote_activation",
      "no_package_change", "no_process_start", "no_connection_retained", "no_tool_authority",
    ];
  if (item.effects.join("\u0000") !== expectedEffects.join("\u0000")) fail();
  return item as unknown as McpManagedLifecyclePreview;
}

export function parseMcpManagedLifecycleReceipt(value: unknown): McpManagedLifecycleReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "installation_kind", "server", "preview_digest",
    "idempotent_replay", "package_changed", "process_started",
    "process_tree_cleanup", "endpoint_connected", "connection_retained", "persistent_host_started",
    "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-lifecycle-receipt.v2"
    || !oneOf(item.action, ["install", "uninstall"])
    || !oneOf(item.installation_kind, ["remote_activation", "local_package"])
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || typeof item.package_changed !== "boolean"
    || typeof item.process_started !== "boolean"
    || !oneOf(item.process_tree_cleanup, ["verified", "not_applicable"])
    || item.endpoint_connected !== false
    || item.connection_retained !== false
    || item.persistent_host_started !== false
    || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if ((item.action === "install" && server.installation_state !== "installed")
    || (item.action === "uninstall" && server.installation_state !== "not_installed")) fail();
  if (item.action === "install" && server.installation_kind !== item.installation_kind) fail();
  const localChange = item.installation_kind === "local_package";
  const localInstall = localChange && item.action === "install";
  if (item.package_changed !== localChange || item.process_started !== localInstall
    || item.process_tree_cleanup !== (localInstall ? "verified" : "not_applicable")) fail();
  return {
    ...(item as unknown as McpManagedLifecycleReceipt),
    server,
  };
}

export function parseMcpManagedLocalConfigurationInspectionPreview(
  value: unknown,
): McpManagedLocalConfigurationInspectionPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "plan_revision", "availability", "reason", "effects", "preview_digest",
    "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-configuration-inspection-preview.v1"
    || item.action !== "inspect_configuration"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, [
      "ready_for_native_confirmation", "local_package_required", "already_inspected",
      "already_installed", "cleanup_required", "operation_in_progress",
      "package_registry_not_supported", "package_integrity_required",
      "local_transport_unsupported", "local_installer_unavailable",
    ])
    || !Array.isArray(item.effects)
    || item.effects.join("\u0000") !== LOCAL_CONFIGURATION_INSPECTION_EFFECTS.join("\u0000")
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available")
    !== (item.reason === "ready_for_native_confirmation")) fail();
  return item as unknown as McpManagedLocalConfigurationInspectionPreview;
}

export function parseMcpManagedLocalConfigurationInspectionReceipt(
  value: unknown,
): McpManagedLocalConfigurationInspectionReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "server", "inspection", "preview_digest",
    "idempotent_replay", "archive_retained", "process_started",
    "endpoint_connected", "connection_retained", "persistent_host_started",
    "tool_authority_granted", "configuration_values_persisted",
  ])
    || item.contract_version !== "mcp-managed-local-configuration-inspection-receipt.v1"
    || item.action !== "inspect_configuration"
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || item.archive_retained !== false
    || item.process_started !== false
    || item.endpoint_connected !== false
    || item.connection_retained !== false
    || item.persistent_host_started !== false
    || item.tool_authority_granted !== false
    || item.configuration_values_persisted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  const inspection = parseLocalConfigurationInspection(item.inspection);
  const retained = server.local_configuration_inspection;
  if (server.option_kind !== "local_package"
    || server.installation_state !== "not_installed"
    || retained === null
    || retained.plan_revision !== inspection.plan_revision
    || retained.artifact_sha256 !== inspection.artifact_sha256
    || retained.artifact_bytes !== inspection.artifact_bytes
    || retained.manifest_digest !== inspection.manifest_digest
    || retained.manifest_version !== inspection.manifest_version
    || retained.configuration_schema_digest !== inspection.configuration_schema_digest
    || retained.requirement_ids.join("\u0000") !== inspection.requirement_ids.join("\u0000")
    || retained.inspected_at !== inspection.inspected_at) fail();
  return {
    ...(item as unknown as McpManagedLocalConfigurationInspectionReceipt),
    server,
    inspection,
  };
}

const LOCAL_CLEANUP_EFFECTS: McpManagedLocalCleanupEffect[] = [
  "verify_operation_journal",
  "verify_installed_or_quarantined_tree_digest",
  "finish_quarantined_removal",
  "clear_cleanup_state",
  "no_process_start",
  "no_connection_retained",
  "no_tool_authority",
];

export function parseMcpManagedLocalCleanupPreview(
  value: unknown,
): McpManagedLocalCleanupPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "plan_revision", "availability", "reason", "effects", "preview_digest",
    "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-cleanup-preview.v1"
    || item.action !== "complete_interrupted_uninstall"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, [
      "ready_for_native_confirmation", "cleanup_not_required",
      "unsupported_cleanup_state", "local_uninstaller_unavailable",
    ])
    || !Array.isArray(item.effects)
    || item.effects.join("\u0000") !== LOCAL_CLEANUP_EFFECTS.join("\u0000")
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available")
    !== (item.reason === "ready_for_native_confirmation")) fail();
  return item as unknown as McpManagedLocalCleanupPreview;
}

const LOCAL_UPDATE_EFFECTS: McpManagedLocalUpdateEffect[] = [
  "resolve_official_latest_exact_version",
  "download_exact_target_package",
  "verify_target_artifact_sha256",
  "stage_target_in_isolation",
  "execute_bounded_target_probe",
  "stop_and_verify_target_process_tree",
  "retain_verified_rollback_generation",
  "publish_verified_target_package",
  "no_connection_retained",
  "no_tool_authority",
];

export function parseMcpManagedLocalUpdatePreview(
  value: unknown,
): McpManagedLocalUpdatePreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "current_version", "current_plan_revision", "target_version",
    "target_catalog_id", "target_option_id", "target_plan_revision",
    "availability", "reason", "effects", "preview_digest",
    "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-update-preview.v1"
    || item.action !== "update"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || !boundedText(item.current_version, 1, 255)
    || typeof item.current_plan_revision !== "string" || !DIGEST.test(item.current_plan_revision)
    || !(item.target_version === null || boundedText(item.target_version, 1, 255))
    || !(item.target_catalog_id === null
      || (typeof item.target_catalog_id === "string" && ID.test(item.target_catalog_id)))
    || !(item.target_option_id === null
      || (typeof item.target_option_id === "string" && ID.test(item.target_option_id)))
    || !(item.target_plan_revision === null
      || (typeof item.target_plan_revision === "string" && DIGEST.test(item.target_plan_revision)))
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, [
      "ready_for_native_confirmation", "local_package_required",
      "install_required", "cleanup_required", "operation_in_progress",
      "registry_unavailable", "already_latest",
      "current_version_metadata_changed", "rollback_cleanup_required",
      "configuration_migration_required", "target_not_installable",
      "target_option_ambiguous", "permission_change_required",
      "local_installer_unavailable",
    ])
    || !Array.isArray(item.effects)
    || item.effects.join("\u0000") !== LOCAL_UPDATE_EFFECTS.join("\u0000")
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available")
    !== (item.reason === "ready_for_native_confirmation")) fail();
  const targetIdentity = [
    item.target_catalog_id,
    item.target_option_id,
    item.target_plan_revision,
  ];
  if (targetIdentity.some((entry) => entry === null)
    !== targetIdentity.every((entry) => entry === null)) fail();
  if (item.availability === "available" && (
    item.target_version === null
    || targetIdentity.some((entry) => entry === null)
    || item.target_version === item.current_version
  )) fail();
  return item as unknown as McpManagedLocalUpdatePreview;
}

export function parseMcpManagedLocalCleanupReceipt(
  value: unknown,
): McpManagedLocalCleanupReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "server", "preview_digest",
    "idempotent_replay", "package_presence", "filesystem_changed",
    "process_started", "endpoint_connected", "connection_retained",
    "persistent_host_started", "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-local-cleanup-receipt.v1"
    || item.action !== "complete_interrupted_uninstall"
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || item.package_presence !== "absent"
    || typeof item.filesystem_changed !== "boolean"
    || item.process_started !== false
    || item.endpoint_connected !== false
    || item.connection_retained !== false
    || item.persistent_host_started !== false
    || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if (server.option_kind !== "local_package"
    || server.installation_state !== "not_installed"
    || server.lifecycle_state !== "planned"
    || server.operation_state !== "idle"
    || server.local_package_evidence !== null
    || (item.idempotent_replay && item.filesystem_changed)) fail();
  return {
    ...(item as unknown as McpManagedLocalCleanupReceipt),
    server,
  };
}

export function parseMcpManagedLocalUpdateReceipt(
  value: unknown,
): McpManagedLocalUpdateReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "server", "preview_digest",
    "idempotent_replay", "package_changed", "process_started",
    "process_tree_cleanup", "rollback_generation_retained",
    "endpoint_connected", "connection_retained", "persistent_host_started",
    "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-local-update-receipt.v1"
    || item.action !== "update"
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || item.package_changed !== true || item.process_started !== true
    || item.process_tree_cleanup !== "verified"
    || item.rollback_generation_retained !== true
    || item.endpoint_connected !== false || item.connection_retained !== false
    || item.persistent_host_started !== false || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if (server.option_kind !== "local_package"
    || server.installation_state !== "installed"
    || server.operation_state !== "idle"
    || server.local_package_evidence === null
    || server.rollback_generation === null) fail();
  return { ...(item as unknown as McpManagedLocalUpdateReceipt), server };
}

const LOCAL_ROLLBACK_EFFECTS: McpManagedLocalRollbackEffect[] = [
  "verify_current_tree_digest",
  "verify_rollback_tree_digest",
  "atomically_swap_verified_generations",
  "retain_superseded_current_generation",
  "no_process_start",
  "no_connection_retained",
  "no_tool_authority",
];
const LOCAL_ROLLBACK_REASONS = [
  "ready_for_native_confirmation", "local_package_required", "install_required",
  "cleanup_required", "operation_in_progress", "rollback_generation_missing",
  "local_installer_unavailable",
] as const;

export function parseMcpManagedLocalRollbackPreview(
  value: unknown,
): McpManagedLocalRollbackPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "current_version", "current_plan_revision", "target_version",
    "target_plan_revision", "availability", "reason", "effects",
    "preview_digest", "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-rollback-preview.v1"
    || item.action !== "rollback"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || !boundedText(item.current_version, 1, 255)
    || typeof item.current_plan_revision !== "string" || !DIGEST.test(item.current_plan_revision)
    || !(item.target_version === null || boundedText(item.target_version, 1, 255))
    || !(item.target_plan_revision === null
      || (typeof item.target_plan_revision === "string" && DIGEST.test(item.target_plan_revision)))
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, LOCAL_ROLLBACK_REASONS)
    || !Array.isArray(item.effects)
    || item.effects.join("\u0000") !== LOCAL_ROLLBACK_EFFECTS.join("\u0000")
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available") !== (item.reason === "ready_for_native_confirmation")
    || ((item.target_version === null) !== (item.target_plan_revision === null))
    || (item.availability === "available" && item.target_version === null)) fail();
  return item as unknown as McpManagedLocalRollbackPreview;
}

export function parseMcpManagedLocalRollbackReceipt(
  value: unknown,
): McpManagedLocalRollbackReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "server", "preview_digest",
    "idempotent_replay", "package_changed", "process_started",
    "process_tree_cleanup", "rollback_generation_retained",
    "endpoint_connected", "connection_retained", "persistent_host_started",
    "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-local-rollback-receipt.v1"
    || item.action !== "rollback"
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || item.package_changed !== true || item.process_started !== false
    || item.process_tree_cleanup !== "not_applicable"
    || item.rollback_generation_retained !== true
    || item.endpoint_connected !== false || item.connection_retained !== false
    || item.persistent_host_started !== false || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if (server.option_kind !== "local_package"
    || server.installation_state !== "installed"
    || server.operation_state !== "idle"
    || server.local_package_evidence === null
    || server.rollback_generation === null) fail();
  return { ...(item as unknown as McpManagedLocalRollbackReceipt), server };
}

const LOCAL_ROLLBACK_CLEANUP_EFFECTS: McpManagedLocalRollbackCleanupEffect[] = [
  "verify_rollback_tree_digest",
  "quarantine_verified_rollback_generation",
  "remove_quarantined_rollback_generation",
  "keep_current_generation_installed",
  "no_process_start",
  "no_connection_retained",
  "no_tool_authority",
];

export function parseMcpManagedLocalRollbackCleanupPreview(
  value: unknown,
): McpManagedLocalRollbackCleanupPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "rollback_version", "rollback_plan_revision", "availability", "reason",
    "effects", "preview_digest", "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-rollback-cleanup-preview.v1"
    || item.action !== "cleanup_rollback_generation"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || !(item.rollback_version === null || boundedText(item.rollback_version, 1, 255))
    || !(item.rollback_plan_revision === null
      || (typeof item.rollback_plan_revision === "string" && DIGEST.test(item.rollback_plan_revision)))
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, LOCAL_ROLLBACK_REASONS)
    || !Array.isArray(item.effects)
    || item.effects.join("\u0000") !== LOCAL_ROLLBACK_CLEANUP_EFFECTS.join("\u0000")
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  if ((item.availability === "available") !== (item.reason === "ready_for_native_confirmation")
    || ((item.rollback_version === null) !== (item.rollback_plan_revision === null))
    || (item.availability === "available" && item.rollback_version === null)) fail();
  return item as unknown as McpManagedLocalRollbackCleanupPreview;
}

export function parseMcpManagedLocalRollbackCleanupReceipt(
  value: unknown,
): McpManagedLocalRollbackCleanupReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "server", "preview_digest",
    "idempotent_replay", "filesystem_changed", "rollback_generation_retained",
    "process_started", "endpoint_connected", "connection_retained",
    "persistent_host_started", "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-local-rollback-cleanup-receipt.v1"
    || item.action !== "cleanup_rollback_generation"
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || typeof item.filesystem_changed !== "boolean"
    || item.rollback_generation_retained !== false || item.process_started !== false
    || item.endpoint_connected !== false || item.connection_retained !== false
    || item.persistent_host_started !== false || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if (server.option_kind !== "local_package"
    || server.installation_state !== "installed"
    || server.operation_state !== "idle"
    || server.local_package_evidence === null
    || server.rollback_generation !== null
    || (item.idempotent_replay && item.filesystem_changed)) fail();
  return { ...(item as unknown as McpManagedLocalRollbackCleanupReceipt), server };
}

const LOCAL_RECOVERY_EFFECTS_BY_ACTION: Record<
  "update" | "rollback" | "cleanup" | "none",
  readonly McpManagedLocalOperationRecoveryEffect[]
> = {
  update: [
    "verify_operation_journal", "restore_durable_current_generation",
    "discard_verified_staged_target", "clear_cleanup_state",
    "no_process_start", "no_connection_retained", "no_tool_authority",
  ],
  rollback: [
    "verify_operation_journal", "restore_durable_current_generation",
    "retain_verified_rollback_generation", "clear_cleanup_state",
    "no_process_start", "no_connection_retained", "no_tool_authority",
  ],
  cleanup: [
    "verify_operation_journal", "finish_verified_rollback_generation_removal",
    "clear_cleanup_state", "no_process_start", "no_connection_retained",
    "no_tool_authority",
  ],
  none: [
    "verify_operation_journal", "clear_cleanup_state", "no_process_start",
    "no_connection_retained", "no_tool_authority",
  ],
};

export function parseMcpManagedLocalOperationRecoveryPreview(
  value: unknown,
): McpManagedLocalOperationRecoveryPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "management_id", "expected_revision",
    "interrupted_action", "availability", "reason", "effects",
    "preview_digest", "native_confirmation_required",
  ])
    || item.contract_version !== "mcp-managed-local-operation-recovery-preview.v1"
    || item.action !== "recover_interrupted_local_operation"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || !Number.isInteger(item.expected_revision) || Number(item.expected_revision) < 1
    || !(item.interrupted_action === null
      || oneOf(item.interrupted_action, ["update", "rollback", "cleanup"]))
    || !oneOf(item.availability, ["available", "unavailable"])
    || !oneOf(item.reason, [
      "ready_for_native_confirmation", "cleanup_not_required",
      "unsupported_cleanup_state", "process_cleanup_unconfirmed",
      "local_installer_unavailable",
    ])
    || !Array.isArray(item.effects)
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.native_confirmation_required !== true) fail();
  const expectedEffects = LOCAL_RECOVERY_EFFECTS_BY_ACTION[
    item.interrupted_action === null ? "none" : item.interrupted_action
  ];
  if (item.effects.join("\u0000") !== expectedEffects.join("\u0000")
    || (item.availability === "available") !== (item.reason === "ready_for_native_confirmation")
    || (item.availability === "available" && item.interrupted_action === null)) fail();
  return item as unknown as McpManagedLocalOperationRecoveryPreview;
}

export function parseMcpManagedLocalOperationRecoveryReceipt(
  value: unknown,
): McpManagedLocalOperationRecoveryReceipt {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "action", "recovered_action", "server",
    "preview_digest", "idempotent_replay", "filesystem_state_verified",
    "process_started", "endpoint_connected", "connection_retained",
    "persistent_host_started", "tool_authority_granted",
  ])
    || item.contract_version !== "mcp-managed-local-operation-recovery-receipt.v1"
    || item.action !== "recover_interrupted_local_operation"
    || !oneOf(item.recovered_action, ["update", "rollback", "cleanup"])
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || typeof item.idempotent_replay !== "boolean"
    || item.filesystem_state_verified !== true || item.process_started !== false
    || item.endpoint_connected !== false || item.connection_retained !== false
    || item.persistent_host_started !== false || item.tool_authority_granted !== false) fail();
  const server = parseMcpManagedServer(item.server);
  if (server.option_kind !== "local_package"
    || server.installation_state !== "installed"
    || server.operation_state !== "idle"
    || server.local_package_evidence === null
    || (item.recovered_action === "cleanup" && server.rollback_generation !== null)
    || (item.recovered_action === "rollback" && server.rollback_generation === null)
    || (item.recovered_action === "update" && server.rollback_generation !== null)) fail();
  return { ...(item as unknown as McpManagedLocalOperationRecoveryReceipt), server };
}
