import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AgentProject,
  McpManagedPermission,
  McpManagedLifecyclePreview,
  McpManagedLocalConfigurationInspectionEffect,
  McpManagedLocalConfigurationInspectionPreview,
  McpManagedLocalCleanupEffect,
  McpManagedLocalCleanupPreview,
  McpManagedLocalUpdateEffect,
  McpManagedLocalUpdatePreview,
  McpManagedLocalRollbackEffect,
  McpManagedLocalRollbackPreview,
  McpManagedLocalRollbackCleanupEffect,
  McpManagedLocalRollbackCleanupPreview,
  McpManagedLocalOperationRecoveryEffect,
  McpManagedLocalOperationRecoveryPreview,
  McpManagedRequirement,
  McpManagedSecretVaultStatus,
  McpManagedServer,
  McpManagedToolSnapshot,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentMcpAcceptancePanel } from "./AgentMcpAcceptancePanel";
import { AgentMcpManagedRuntimePanel } from "./AgentMcpManagedRuntimePanel";
import type {
  TrustedMcpAcceptanceEvidence,
  TrustedMcpAcceptanceRun,
} from "./trustedMcpAcceptance";

type ManagedTransport = Partial<Pick<
  PromptEnhancerTransport,
  | "listAgentProjects"
  | "getMcpManagedToolSnapshot"
  | "getMcpManagedHostStatus"
  | "getMcpManagedHostStartPreview"
  | "startMcpManagedHost"
  | "stopMcpManagedHost"
  | "getMcpManagedProjectRuntime"
  | "probeMcpManagedServer"
  | "getMcpManagedLifecyclePreview"
  | "getMcpManagedLocalConfigurationInspectionPreview"
  | "inspectMcpManagedLocalConfiguration"
  | "applyMcpManagedLifecycle"
  | "getMcpManagedLocalCleanupPreview"
  | "getMcpManagedLocalUpdatePreview"
  | "applyMcpManagedLocalUpdate"
  | "getMcpManagedLocalRollbackPreview"
  | "applyMcpManagedLocalRollback"
  | "getMcpManagedLocalRollbackCleanupPreview"
  | "cleanupMcpManagedLocalRollback"
  | "getMcpManagedLocalOperationRecoveryPreview"
  | "recoverMcpManagedLocalOperation"
  | "completeMcpManagedLocalCleanup"
  | "setMcpManagedProjectBinding"
  | "storeMcpManagedSecret"
  | "removeMcpManagedSecret"
  | "storeMcpManagedConfiguration"
  | "removeMcpManagedConfiguration"
>>;

const permissionLabels: Record<McpManagedPermission, string> = {
  process_spawn: "Start the reviewed server process",
  filesystem_read: "Read within an explicitly configured filesystem scope",
  filesystem_write: "Write within an explicitly configured filesystem scope",
  network_egress: "Connect to the reviewed remote host",
  credential_use: "Use configured OS-vault credentials",
};

const requirementStateLabels: Record<string, string> = {
  publisher_value_declared: "Publisher-fixed value declared",
  registry_default_declared: "Registry default declared",
  value_required: "Non-secret value still required",
  value_pending_store: "OS-vault write needs reconciliation",
  value_stored: "Last confirmed in Windows Credential Manager",
  value_store_failed: "OS-vault write failed",
  value_pending_removal: "OS-vault removal needs reconciliation",
  value_cleanup_required: "Configuration cleanup required",
  optional_unset: "Optional and not configured",
  secret_missing: "Credential not stored",
  secret_pending_store: "Vault write needs reconciliation",
  secret_stored: "Last confirmed in Windows Credential Manager",
  secret_store_failed: "Vault write failed",
  secret_pending_removal: "Vault removal needs reconciliation",
  secret_cleanup_required: "Credential cleanup required",
};

const lifecycleReasonLabels: Record<McpManagedLifecyclePreview["reason"], string> = {
  ready_for_native_confirmation: "Ready for one native-confirmed change",
  compatibility_check_required: "Run a current compatibility check first",
  configuration_required: "Complete required configuration first",
  configuration_inspection_required: "Inspect the package's declared configuration first",
  package_registry_not_supported: "Only checksum-pinned MCPB release packages are installable",
  package_integrity_required: "The Registry option does not declare a required SHA-256 digest",
  local_transport_unsupported: "The local package must use the stdio transport",
  local_installer_unavailable: "The isolated MCPB installer is unavailable in this runtime",
  local_uninstaller_unavailable: "The verified local-package remover is unavailable in this runtime",
  already_installed: "This exact plan is already active",
  not_installed: "There is no activation to remove",
  cleanup_required: "Cleanup must be reconciled before another lifecycle change",
  operation_in_progress: "Another lifecycle operation is still in progress",
};

const configurationInspectionReasonLabels: Record<McpManagedLocalConfigurationInspectionPreview["reason"], string> = {
  ready_for_native_confirmation: "Ready to inspect the exact checksum-pinned package",
  local_package_required: "Configuration inspection applies only to local packages",
  already_inspected: "This exact package plan has already been inspected",
  already_installed: "The installed package already passed its guarded setup",
  cleanup_required: "Recover the interrupted package operation before inspecting again",
  operation_in_progress: "Another package operation is still in progress",
  package_registry_not_supported: "Only checksum-pinned MCPB release packages can be inspected",
  package_integrity_required: "The package has no reviewable SHA-256 digest",
  local_transport_unsupported: "The package must use the stdio transport",
  local_installer_unavailable: "The isolated MCPB inspector is unavailable in this runtime",
};

const configurationInspectionEffectLabels: Record<McpManagedLocalConfigurationInspectionEffect, string> = {
  download_exact_package: "Download only the exact reviewed release artifact",
  verify_artifact_sha256: "Match its declared SHA-256 digest before reading the manifest",
  inspect_manifest_configuration: "Read only the bounded MCPB configuration schema; do not execute the package",
  discard_inspection_archive: "Delete the inspection archive and staging tree after the check",
  persist_content_free_configuration_schema: "Save only requirement identities, types, and content-free integrity evidence",
  revoke_project_bindings_if_permissions_expand: "Revoke existing project grants if the manifest expands required permissions",
  no_configuration_values_persisted: "Persist no configuration values, defaults, or manifest content",
  no_process_start: "Start no package process or terminal",
  no_connection_retained: "Retain no network or MCP connection",
  no_tool_authority: "Grant no tool authority",
};

const lifecycleEffectLabels: Record<McpManagedLifecyclePreview["effects"][number], string> = {
  persist_remote_activation: "Save this exact reviewed remote activation",
  remove_remote_activation: "Remove only the saved remote activation",
  download_exact_package: "Download only the exact reviewed release artifact",
  verify_artifact_sha256: "Match the declared SHA-256 digest before extraction",
  stage_isolated_package: "Extract into a bounded application-owned staging directory",
  execute_bounded_compatibility_probe: "Start one hidden, bounded MCP compatibility process",
  stop_and_verify_process_tree: "Stop the owned process tree and verify cleanup",
  publish_verified_package: "Atomically publish only the verified package tree",
  verify_installed_tree_digest: "Verify the installed tree still matches its retained digest",
  quarantine_verified_package: "Atomically move only that verified tree into application-owned quarantine",
  remove_quarantined_package: "Remove the quarantined tree with a restart-recoverable operation journal",
  no_package_change: "No package or model files are changed",
  no_process_start: "No process or terminal is started",
  no_connection_retained: "No network connection is retained",
  no_tool_authority: "No tool becomes available to a model",
};

const cleanupReasonLabels: Record<McpManagedLocalCleanupPreview["reason"], string> = {
  ready_for_native_confirmation: "Ready to finish the interrupted removal",
  cleanup_not_required: "There is no interrupted removal to reconcile",
  unsupported_cleanup_state: "This cleanup state needs a different recovery path",
  local_uninstaller_unavailable: "The verified local-package remover is unavailable in this runtime",
};

const cleanupEffectLabels: Record<McpManagedLocalCleanupEffect, string> = {
  verify_operation_journal: "Bind recovery to the retained uninstall journal",
  verify_installed_or_quarantined_tree_digest: "Accept only the recorded installed or quarantined tree digest",
  finish_quarantined_removal: "Finish removal, or verify that the interrupted operation already removed it",
  clear_cleanup_state: "Clear the journal only after package absence is verified",
  no_process_start: "No process or terminal is started",
  no_connection_retained: "No network connection is retained",
  no_tool_authority: "No tool becomes available to a model",
};

const updateReasonLabels: Record<McpManagedLocalUpdatePreview["reason"], string> = {
  ready_for_native_confirmation: "A newer exact Registry version is reviewable",
  local_package_required: "Updates apply only to installed local packages",
  install_required: "Install this reviewed package before checking for an update",
  cleanup_required: "Finish the interrupted lifecycle operation before checking again",
  operation_in_progress: "Another lifecycle operation is still in progress",
  registry_unavailable: "The Official MCP Registry could not be verified",
  already_latest: "The installed plan is the current exact Registry version",
  current_version_metadata_changed: "The current version's Registry metadata changed and needs a new owner review",
  rollback_cleanup_required: "A verified rollback generation is already retained; roll it back or remove it before another update",
  configuration_migration_required: "Configured package inputs require a separate owner-reviewed migration before update",
  target_not_installable: "The latest version has no checksum-pinned configuration-free MCPB target",
  target_option_ambiguous: "The latest version exposes multiple eligible packages; automatic selection is refused",
  permission_change_required: "The latest version changes required permissions and needs a new setup plan",
  local_installer_unavailable: "The isolated MCPB installer is unavailable in this runtime",
};

const updateEffectLabels: Record<McpManagedLocalUpdateEffect, string> = {
  resolve_official_latest_exact_version: "Resolve the Official Registry latest alias to one exact version",
  download_exact_target_package: "Download only the exact resolved target artifact",
  verify_target_artifact_sha256: "Verify the target artifact against its declared SHA-256 digest",
  stage_target_in_isolation: "Stage the target in a bounded application-owned directory",
  execute_bounded_target_probe: "Run one hidden bounded handshake against the staged target",
  stop_and_verify_target_process_tree: "Stop the target probe and verify its full owned process tree",
  retain_verified_rollback_generation: "Retain one verified bounded rollback generation",
  publish_verified_target_package: "Publish the verified target only after the rollback generation is safe",
  no_connection_retained: "Retain no network or MCP connection",
  no_tool_authority: "Grant no tool authority during update",
};

const rollbackReasonLabels: Record<McpManagedLocalRollbackPreview["reason"], string> = {
  ready_for_native_confirmation: "The retained verified generation can be restored",
  local_package_required: "Rollback applies only to a local package",
  install_required: "Install a package before rollback",
  cleanup_required: "Recover the interrupted operation before rollback",
  operation_in_progress: "Another package operation is in progress",
  rollback_generation_missing: "No retained rollback generation exists",
  local_installer_unavailable: "The isolated MCPB lifecycle adapter is unavailable",
};

const rollbackEffectLabels: Record<McpManagedLocalRollbackEffect, string> = {
  verify_current_tree_digest: "Verify the currently published tree digest",
  verify_rollback_tree_digest: "Verify the retained rollback tree digest",
  atomically_swap_verified_generations: "Atomically exchange the two verified generations",
  retain_superseded_current_generation: "Keep the superseded current generation for a reversible rollback",
  no_process_start: "Start no package process or terminal",
  no_connection_retained: "Retain no MCP or network connection",
  no_tool_authority: "Grant no tool authority",
};

const rollbackCleanupEffectLabels: Record<McpManagedLocalRollbackCleanupEffect, string> = {
  verify_rollback_tree_digest: "Verify the retained rollback tree digest",
  quarantine_verified_rollback_generation: "Move only that verified generation into owned quarantine",
  remove_quarantined_rollback_generation: "Remove the verified quarantined generation",
  keep_current_generation_installed: "Keep the current generation installed and unchanged",
  no_process_start: "Start no package process or terminal",
  no_connection_retained: "Retain no MCP or network connection",
  no_tool_authority: "Grant no tool authority",
};

const recoveryReasonLabels: Record<McpManagedLocalOperationRecoveryPreview["reason"], string> = {
  ready_for_native_confirmation: "The interrupted package operation has an exact recoverable journal",
  cleanup_not_required: "No interrupted package operation requires recovery",
  unsupported_cleanup_state: "The retained journal and package evidence do not form a supported recovery state",
  process_cleanup_unconfirmed: "A crash interrupted staging before process-tree cleanup could be proven",
  local_installer_unavailable: "The isolated MCPB recovery adapter is unavailable",
};

const recoveryEffectLabels: Record<McpManagedLocalOperationRecoveryEffect, string> = {
  verify_operation_journal: "Verify the exact interrupted-operation journal",
  restore_durable_current_generation: "Restore the generation recorded as current in the database",
  discard_verified_staged_target: "Discard only the verified staged or partially published target",
  retain_verified_rollback_generation: "Keep the verified rollback generation available",
  finish_verified_rollback_generation_removal: "Finish removal of the exact retained generation",
  clear_cleanup_state: "Clear cleanup state only after filesystem verification",
  no_process_start: "Start no package process or terminal",
  no_connection_retained: "Retain no MCP or network connection",
  no_tool_authority: "Grant no tool authority",
};

function requestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function configurationValueError(
  requirement: McpManagedRequirement,
  value: string,
): string | null {
  if (!value || /[\u0000\r\n]/u.test(value)
    || new TextEncoder().encode(value).byteLength > 2_048) {
    return "Configuration values must be between 1 and 2,048 UTF-8 bytes and contain no line or NUL separators.";
  }
  if (requirement.format === "boolean" && value !== "true" && value !== "false") {
    return "Choose either true or false for this configuration value.";
  }
  if (requirement.format === "number"
    && (value.trim() === "" || !Number.isFinite(Number(value)))) {
    return "Enter a finite numeric configuration value.";
  }
  if (requirement.format === "filepath"
    && (!/^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+|\/)/u.test(value)
      || /[*?\[\]]/u.test(value))) {
    return "Enter an absolute file or folder path without wildcard characters.";
  }
  return null;
}

function optionIdentity(server: McpManagedServer): string {
  return server.package_identifier
    ?? server.endpoint_host
    ?? (server.endpoint_state === "template_requires_configuration"
      ? "Endpoint template requires configuration"
      : "No executable endpoint configured");
}

function compatibilityFailureMessage(error: unknown): string {
  if (error instanceof TransportError) {
    if (error.reasonCode === "mcp_host_endpoint_not_public"
      || error.reasonCode === "mcp_host_endpoint_unresolvable"
      || error.reasonCode === "mcp_host_endpoint_unreachable") {
      return "Compatibility was refused because the reviewed host did not resolve to a usable public address. No connection is retained; review the endpoint and retry.";
    }
    if (error.reasonCode === "mcp_host_egress_origin_changed"
      || error.reasonCode === "mcp_host_tls_policy_invalid"
      || error.reasonCode === "mcp_host_redirect_refused") {
      return "Compatibility was refused after an origin, redirect, or TLS safety check. No connection is retained; review the current plan before retrying.";
    }
    if (error.reasonCode === "mcp_host_headers_too_large"
      || error.reasonCode === "mcp_host_headers_invalid"
      || error.reasonCode === "mcp_host_content_encoding_unsupported"
      || error.reasonCode === "mcp_host_response_too_large"
      || error.reasonCode === "mcp_host_response_count_exceeded"
      || error.reasonCode === "mcp_host_sse_event_count_exceeded") {
      return "Compatibility stopped at a response safety limit. No connection or response content is retained; review the server before retrying.";
    }
    if (error.reasonCode === "mcp_host_deadline_exceeded") {
      return "Compatibility timed out and the connection was closed. Check the server, then retry from this exact plan revision.";
    }
    if (error.reasonCode === "mcp_host_process_output_limit") {
      return "The local compatibility process exceeded its output safety limit and its owned process tree was stopped. No process output is retained; review the package before retrying.";
    }
    if (error.reasonCode === "mcp_host_visible_window_detected") {
      return "The local compatibility process tried to show a window, so its owned process tree was stopped. No process or tool authority is retained; review the package before retrying.";
    }
    if (error.reasonCode === "mcp_host_process_visibility_unconfirmed") {
      return "Prompt Enhancer could not verify that the local compatibility process stayed headless, so it stopped the owned process tree. Review the package before retrying.";
    }
    if (error.reasonCode === "mcp_host_protocol_unsupported"
      || error.reasonCode === "mcp_host_transport_mismatch") {
      return "Compatibility was refused because the server protocol or transport does not match this reviewed plan. No connection or tool authority is retained; choose a compatible option before retrying.";
    }
    if (error.reasonCode === "mcp_host_tool_alias_collision"
      || error.reasonCode === "mcp_host_tool_count_exceeded"
      || error.reasonCode === "mcp_host_tool_identity_conflict"
      || error.reasonCode === "mcp_host_tool_identity_invalid"
      || error.reasonCode === "mcp_host_tool_metadata_invalid"
      || error.reasonCode === "mcp_host_tool_metadata_total_exceeded") {
      return "Compatibility was refused because the server exposed ambiguous or excessive tool identities or metadata. No tool was admitted; review or update the server before checking again.";
    }
    if (error.reasonCode === "mcp_host_tool_schema_dialect_unsupported"
      || error.reasonCode === "mcp_host_tool_schema_external_ref"
      || error.reasonCode === "mcp_host_tool_schema_format_unsupported"
      || error.reasonCode === "mcp_host_tool_schema_invalid"
      || error.reasonCode === "mcp_host_tool_schema_keyword_unsupported"
      || error.reasonCode === "mcp_host_tool_schema_pattern_unsafe"
      || error.reasonCode === "mcp_host_tool_schema_recursive"
      || error.reasonCode === "mcp_host_tool_schema_ref_invalid"
      || error.reasonCode === "mcp_host_tool_schema_too_complex"
      || error.reasonCode === "mcp_host_tool_schema_too_large"
      || error.reasonCode === "mcp_host_tool_schema_total_exceeded") {
      return "Compatibility was refused because a tool schema was unsafe, unsupported, recursive, or over a safety limit. No schema or tool authority was admitted; update the server before checking again.";
    }
  }
  return "Compatibility was not verified. No connection is retained; review configuration and retry from the current plan revision.";
}

export function AgentMcpManagedPlanView({
  acceptanceRun = null,
  activeEventHead = 0,
  activeSessionId = null,
  onBack,
  onAcceptanceEvidence,
  onAcceptanceRunChange,
  onRuntimeChange,
  onServer,
  preferredProjectId = null,
  secretVault,
  server,
  transport,
  userPresenceAvailable,
}: {
  acceptanceRun?: TrustedMcpAcceptanceRun | null;
  activeEventHead?: number;
  activeSessionId?: string | null;
  onBack: () => void;
  onAcceptanceEvidence?: (evidence: TrustedMcpAcceptanceEvidence) => void;
  onAcceptanceRunChange?: (run: TrustedMcpAcceptanceRun | null) => void;
  onRuntimeChange?: () => void;
  onServer: (server: McpManagedServer) => void;
  preferredProjectId?: string | null;
  secretVault: McpManagedSecretVaultStatus;
  server: McpManagedServer;
  transport: ManagedTransport;
  userPresenceAvailable: boolean;
}) {
  const [projects, setProjects] = useState<AgentProject[]>([]);
  const [projectsState, setProjectsState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [projectsAttempt, setProjectsAttempt] = useState(0);
  const [selectedProject, setSelectedProject] = useState("");
  const [grants, setGrants] = useState<McpManagedPermission[]>([]);
  const [toolSnapshot, setToolSnapshot] = useState<McpManagedToolSnapshot | null>(null);
  const [toolState, setToolState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [toolAttempt, setToolAttempt] = useState(0);
  const [toolFilter, setToolFilter] = useState("");
  const [admittedTools, setAdmittedTools] = useState<string[]>([]);
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [configurationValues, setConfigurationValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [configurationInspectionPreview, setConfigurationInspectionPreview] = useState<McpManagedLocalConfigurationInspectionPreview | null>(null);
  const [configurationInspectionState, setConfigurationInspectionState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [lifecyclePreview, setLifecyclePreview] = useState<McpManagedLifecyclePreview | null>(null);
  const [lifecycleState, setLifecycleState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [cleanupPreview, setCleanupPreview] = useState<McpManagedLocalCleanupPreview | null>(null);
  const [cleanupState, setCleanupState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [updatePreview, setUpdatePreview] = useState<McpManagedLocalUpdatePreview | null>(null);
  const [updateState, setUpdateState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [rollbackPreview, setRollbackPreview] = useState<McpManagedLocalRollbackPreview | null>(null);
  const [rollbackState, setRollbackState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [rollbackCleanupPreview, setRollbackCleanupPreview] = useState<McpManagedLocalRollbackCleanupPreview | null>(null);
  const [rollbackCleanupState, setRollbackCleanupState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const [operationRecoveryPreview, setOperationRecoveryPreview] = useState<McpManagedLocalOperationRecoveryPreview | null>(null);
  const [operationRecoveryState, setOperationRecoveryState] = useState<"idle" | "loading" | "ready" | "unavailable">("idle");
  const projectRequest = useRef<AbortController | null>(null);
  const toolRequest = useRef<AbortController | null>(null);
  const configurationInspectionRequest = useRef<AbortController | null>(null);
  const lifecycleRequest = useRef<AbortController | null>(null);
  const cleanupRequest = useRef<AbortController | null>(null);
  const updateRequest = useRef<AbortController | null>(null);
  const rollbackRequest = useRef<AbortController | null>(null);
  const rollbackCleanupRequest = useRef<AbortController | null>(null);
  const operationRecoveryRequest = useRef<AbortController | null>(null);
  const mutationRequestIds = useRef(new Map<string, string>());

  const retryRequestId = useCallback((key: string): string => {
    const existing = mutationRequestIds.current.get(key);
    if (existing !== undefined) return existing;
    const next = requestId();
    mutationRequestIds.current.set(key, next);
    return next;
  }, []);

  const lifecycleAction = server.installation_state === "installed"
    ? "uninstall" as const
    : "install" as const;

  useEffect(() => {
    configurationInspectionRequest.current?.abort();
    if (server.option_kind !== "local_package"
      || server.installation_state !== "not_installed"
      || server.local_configuration_inspection !== null) {
      setConfigurationInspectionPreview(null);
      setConfigurationInspectionState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalConfigurationInspectionPreview;
    if (loadPreview === undefined) {
      setConfigurationInspectionPreview(null);
      setConfigurationInspectionState("unavailable");
      return;
    }
    const controller = new AbortController();
    configurationInspectionRequest.current = controller;
    setConfigurationInspectionPreview(null);
    setConfigurationInspectionState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setConfigurationInspectionPreview(value);
      setConfigurationInspectionState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setConfigurationInspectionPreview(null);
      setConfigurationInspectionState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.installation_state,
    server.local_configuration_inspection,
    server.management_id,
    server.option_kind,
    server.revision,
    transport.getMcpManagedLocalConfigurationInspectionPreview,
  ]);

  useEffect(() => {
    const loadPreview = transport.getMcpManagedLifecyclePreview;
    lifecycleRequest.current?.abort();
    if (server.installation_state === "cleanup_required") {
      setLifecyclePreview(null);
      setLifecycleState("unavailable");
      return;
    }
    if (loadPreview === undefined) {
      setLifecyclePreview(null);
      setLifecycleState("unavailable");
      return;
    }
    const controller = new AbortController();
    lifecycleRequest.current = controller;
    setLifecyclePreview(null);
    setLifecycleState("loading");
    void loadPreview(
      server.management_id,
      lifecycleAction,
      controller.signal,
    ).then((value) => {
      if (controller.signal.aborted) return;
      setLifecyclePreview(value);
      setLifecycleState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setLifecyclePreview(null);
      setLifecycleState("unavailable");
    });
    return () => controller.abort();
  }, [lifecycleAction, server.installation_state, server.management_id, server.revision, transport.getMcpManagedLifecyclePreview]);

  useEffect(() => {
    cleanupRequest.current?.abort();
    if (server.installation_state !== "cleanup_required") {
      setCleanupPreview(null);
      setCleanupState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalCleanupPreview;
    if (loadPreview === undefined) {
      setCleanupPreview(null);
      setCleanupState("unavailable");
      return;
    }
    const controller = new AbortController();
    cleanupRequest.current = controller;
    setCleanupPreview(null);
    setCleanupState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setCleanupPreview(value);
      setCleanupState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setCleanupPreview(null);
      setCleanupState("unavailable");
    });
    return () => controller.abort();
  }, [server.installation_state, server.management_id, server.revision, transport.getMcpManagedLocalCleanupPreview]);

  useEffect(() => {
    updateRequest.current?.abort();
    if (server.installation_state !== "installed"
      || server.installation_kind !== "local_package") {
      setUpdatePreview(null);
      setUpdateState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalUpdatePreview;
    if (loadPreview === undefined) {
      setUpdatePreview(null);
      setUpdateState("unavailable");
      return;
    }
    const controller = new AbortController();
    updateRequest.current = controller;
    setUpdatePreview(null);
    setUpdateState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setUpdatePreview(value);
      setUpdateState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setUpdatePreview(null);
      setUpdateState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.installation_kind,
    server.installation_state,
    server.management_id,
    server.revision,
    transport.getMcpManagedLocalUpdatePreview,
  ]);

  useEffect(() => {
    rollbackRequest.current?.abort();
    if (server.installation_state !== "installed"
      || server.installation_kind !== "local_package"
      || server.rollback_generation === null) {
      setRollbackPreview(null);
      setRollbackState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalRollbackPreview;
    if (loadPreview === undefined) {
      setRollbackPreview(null);
      setRollbackState("unavailable");
      return;
    }
    const controller = new AbortController();
    rollbackRequest.current = controller;
    setRollbackPreview(null);
    setRollbackState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setRollbackPreview(value);
      setRollbackState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setRollbackPreview(null);
      setRollbackState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.installation_kind,
    server.installation_state,
    server.management_id,
    server.revision,
    server.rollback_generation,
    transport.getMcpManagedLocalRollbackPreview,
  ]);

  useEffect(() => {
    rollbackCleanupRequest.current?.abort();
    if (server.installation_state !== "installed"
      || server.installation_kind !== "local_package"
      || server.rollback_generation === null) {
      setRollbackCleanupPreview(null);
      setRollbackCleanupState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalRollbackCleanupPreview;
    if (loadPreview === undefined) {
      setRollbackCleanupPreview(null);
      setRollbackCleanupState("unavailable");
      return;
    }
    const controller = new AbortController();
    rollbackCleanupRequest.current = controller;
    setRollbackCleanupPreview(null);
    setRollbackCleanupState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setRollbackCleanupPreview(value);
      setRollbackCleanupState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setRollbackCleanupPreview(null);
      setRollbackCleanupState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.installation_kind,
    server.installation_state,
    server.management_id,
    server.revision,
    server.rollback_generation,
    transport.getMcpManagedLocalRollbackCleanupPreview,
  ]);

  useEffect(() => {
    operationRecoveryRequest.current?.abort();
    if (server.installation_state !== "cleanup_required") {
      setOperationRecoveryPreview(null);
      setOperationRecoveryState("idle");
      return;
    }
    const loadPreview = transport.getMcpManagedLocalOperationRecoveryPreview;
    if (loadPreview === undefined) {
      setOperationRecoveryPreview(null);
      setOperationRecoveryState("unavailable");
      return;
    }
    const controller = new AbortController();
    operationRecoveryRequest.current = controller;
    setOperationRecoveryPreview(null);
    setOperationRecoveryState("loading");
    void loadPreview(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setOperationRecoveryPreview(value);
      setOperationRecoveryState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setOperationRecoveryPreview(null);
      setOperationRecoveryState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.installation_state,
    server.management_id,
    server.revision,
    transport.getMcpManagedLocalOperationRecoveryPreview,
  ]);

  useEffect(() => {
    const listProjects = transport.listAgentProjects;
    if (listProjects === undefined) {
      setProjectsState("unavailable");
      return;
    }
    projectRequest.current?.abort();
    const controller = new AbortController();
    projectRequest.current = controller;
    setProjects([]);
    setProjectsState("loading");
    void listProjects({ includeArchived: false, limit: 100 }, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setProjects(value.projects);
      setSelectedProject((current) => {
        const available = new Set(value.projects.map((project) => project.project_id));
        if (preferredProjectId !== null && available.has(preferredProjectId)) return preferredProjectId;
        return current && available.has(current) ? current : "";
      });
      setProjectsState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setProjects([]);
      setProjectsState("unavailable");
    });
    return () => controller.abort();
  }, [preferredProjectId, projectsAttempt, transport.listAgentProjects]);

  useEffect(() => {
    if (projectsState !== "ready" || preferredProjectId === null) return;
    setSelectedProject(projects.some((project) => project.project_id === preferredProjectId)
      ? preferredProjectId
      : "");
  }, [preferredProjectId, projects, projectsState]);

  useEffect(() => {
    toolRequest.current?.abort();
    if (server.tool_review_state !== "reviewable" || server.tool_snapshot === null) {
      setToolSnapshot(null);
      setToolState("idle");
      return;
    }
    const loadTools = transport.getMcpManagedToolSnapshot;
    if (loadTools === undefined) {
      setToolSnapshot(null);
      setToolState("unavailable");
      return;
    }
    const controller = new AbortController();
    toolRequest.current = controller;
    setToolSnapshot(null);
    setToolState("loading");
    void loadTools(server.management_id, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      if (value.snapshot_id !== server.tool_snapshot?.snapshot_id) {
        setToolState("unavailable");
        return;
      }
      setToolSnapshot(value);
      setToolState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setToolSnapshot(null);
      setToolState("unavailable");
    });
    return () => controller.abort();
  }, [
    server.management_id,
    server.revision,
    server.tool_review_state,
    server.tool_snapshot,
    toolAttempt,
    transport.getMcpManagedToolSnapshot,
  ]);

  const selectedBinding = useMemo(
    () => server.project_bindings.find((item) => item.project_id === selectedProject),
    [selectedProject, server.project_bindings],
  );

  useEffect(() => {
    setGrants(selectedBinding?.granted_permissions ?? []);
    setAdmittedTools(selectedBinding !== undefined
      && selectedBinding.tool_snapshot_id === toolSnapshot?.snapshot_id
      ? selectedBinding.admitted_tool_ids
      : []);
  }, [selectedBinding, toolSnapshot?.snapshot_id]);

  const allPermissionsGranted = server.required_permissions.every((permission) => grants.includes(permission))
    && grants.every((permission) => server.required_permissions.includes(permission));
  const normalizedToolFilter = toolFilter.trim().toLocaleLowerCase();
  const visibleReviewedTools = toolSnapshot?.tools.filter((tool) => (
    normalizedToolFilter === ""
    || tool.name.toLocaleLowerCase().includes(normalizedToolFilter)
    || (tool.title ?? "").toLocaleLowerCase().includes(normalizedToolFilter)
    || (tool.description ?? "").toLocaleLowerCase().includes(normalizedToolFilter)
  )) ?? [];
  const selectedBindingTools = selectedBinding !== undefined
    && selectedBinding.tool_snapshot_id === toolSnapshot?.snapshot_id
    ? selectedBinding.admitted_tool_ids
    : [];
  const projectSelectionChanged = selectedProject !== "" && (
    selectedBinding === undefined
    || !selectedBinding.enabled
    || selectedBinding.admission_state !== "admitted"
    || selectedBinding.tool_snapshot_id !== toolSnapshot?.snapshot_id
    || selectedBinding.granted_permissions.join("\u0000") !== server.required_permissions.join("\u0000")
    || selectedBindingTools.join("\u0000") !== admittedTools.join("\u0000")
  );
  const preferredProjectAvailable = preferredProjectId === null
    || projects.some((project) => project.project_id === preferredProjectId);

  const toggleGrant = (permission: McpManagedPermission) => {
    setGrants((current) => server.required_permissions.filter((item) => (
      item === permission ? !current.includes(item) : current.includes(item)
    )));
  };

  const toggleTool = (toolId: string) => {
    setAdmittedTools((current) => (
      current.includes(toolId)
        ? current.filter((item) => item !== toolId)
        : [...current, toolId].sort()
    ));
  };

  const selectVisibleTools = () => {
    const visibleIds = new Set(visibleReviewedTools.map((tool) => tool.tool_id));
    setAdmittedTools((current) => [...new Set([...current, ...visibleIds])].sort());
  };

  const clearTools = () => setAdmittedTools([]);

  const saveProject = useCallback(async () => {
    const mutate = transport.setMcpManagedProjectBinding;
    if (!mutate || !selectedProject || !allPermissionsGranted || !projectSelectionChanged || !userPresenceAvailable
      || toolState !== "ready" || toolSnapshot === null || admittedTools.length === 0) return;
    setBusy(`project:${selectedProject}`);
    setMessage(null);
    const retryKey = `project:${selectedProject}:${server.revision}:enable:${toolSnapshot.snapshot_id}:${admittedTools.join(",")}`;
    try {
      const receipt = await mutate(server.management_id, selectedProject, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
        enabled: true,
        granted_permissions: server.required_permissions,
        admitted_tool_ids: admittedTools,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      onAcceptanceEvidence?.({
        kind: "project_admission",
        projectId: selectedProject,
        server: receipt.server,
        toolSnapshot,
      });
      setMessage(`${admittedTools.length} reviewed tool${admittedTools.length === 1 ? "" : "s"} allowed for this project. The host remains stopped and routing remains inactive.`);
    } catch {
      setMessage("The project plan was not saved. Refresh the managed record before retrying.");
    } finally {
      setBusy(null);
    }
  }, [
    allPermissionsGranted,
    admittedTools,
    onServer,
    onAcceptanceEvidence,
    projectSelectionChanged,
    selectedProject,
    server,
    transport.setMcpManagedProjectBinding,
    toolSnapshot,
    toolState,
    retryRequestId,
    userPresenceAvailable,
  ]);

  const disableProject = useCallback(async (projectId: string) => {
    const mutate = transport.setMcpManagedProjectBinding;
    if (!mutate || !userPresenceAvailable) return;
    setBusy(`disable:${projectId}`);
    setMessage(null);
    const retryKey = `project:${projectId}:${server.revision}:disable`;
    try {
      const receipt = await mutate(server.management_id, projectId, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
        enabled: false,
        granted_permissions: [],
        admitted_tool_ids: [],
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage("Project plan disabled and its future grants cleared.");
    } catch {
      setMessage("The project plan was not disabled. Refresh the managed record before retrying.");
    } finally {
      setBusy(null);
    }
  }, [onServer, retryRequestId, server, transport.setMcpManagedProjectBinding, userPresenceAvailable]);

  const storeSecret = useCallback(async (requirementId: string) => {
    const mutate = transport.storeMcpManagedSecret;
    const value = secretValues[requirementId] ?? "";
    if (!mutate || !userPresenceAvailable || secretVault.availability !== "available" || !value) return;
    if (value.includes("\u0000") || new TextEncoder().encode(value).byteLength > 2_048) {
      setMessage("Credential values must be between 1 and 2,048 UTF-8 bytes and contain no NUL character.");
      return;
    }
    setBusy(`secret:${requirementId}`);
    setMessage(null);
    const retryKey = `secret:${requirementId}:${server.revision}:store`;
    try {
      const receipt = await mutate(server.management_id, requirementId, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
        value,
      });
      mutationRequestIds.current.delete(retryKey);
      setSecretValues((current) => ({ ...current, [requirementId]: "" }));
      onServer(receipt.server);
      setMessage("Credential stored in Windows Credential Manager. Its value will not be shown again.");
    } catch {
      setMessage("The credential was not confirmed as stored. Review its content-free state before retrying.");
    } finally {
      setBusy(null);
    }
  }, [onServer, retryRequestId, secretValues, secretVault.availability, server, transport.storeMcpManagedSecret, userPresenceAvailable]);

  const removeSecret = useCallback(async (requirementId: string) => {
    const mutate = transport.removeMcpManagedSecret;
    if (!mutate || !userPresenceAvailable || secretVault.availability !== "available") return;
    setBusy(`remove-secret:${requirementId}`);
    setMessage(null);
    const retryKey = `secret:${requirementId}:${server.revision}:remove`;
    try {
      const receipt = await mutate(server.management_id, requirementId, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage("Credential removed from Windows Credential Manager.");
    } catch {
      setMessage("Credential removal was not verified. The record now reports whether cleanup is required.");
    } finally {
      setBusy(null);
    }
  }, [onServer, retryRequestId, secretVault.availability, server, transport.removeMcpManagedSecret, userPresenceAvailable]);

  const storeConfiguration = useCallback(async (requirementId: string) => {
    const mutate = transport.storeMcpManagedConfiguration;
    const requirement = server.requirements.find((item) => (
      item.requirement_id === requirementId
      && !item.secret
      && item.user_value_needed
    ));
    const value = configurationValues[requirementId] ?? "";
    if (!mutate || !requirement || !userPresenceAvailable
      || secretVault.availability !== "available" || !value) return;
    const validation = configurationValueError(requirement, value);
    if (validation !== null) {
      setMessage(validation);
      return;
    }
    setBusy(`configuration:${requirementId}`);
    setMessage(null);
    const retryKey = `configuration:${requirementId}:${server.revision}:store`;
    try {
      const receipt = await mutate(server.management_id, requirementId, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
        value,
      });
      mutationRequestIds.current.delete(retryKey);
      setConfigurationValues((current) => ({ ...current, [requirementId]: "" }));
      onServer(receipt.server);
      setMessage("Configuration stored in Windows Credential Manager. Its value will not be shown again.");
    } catch {
      setMessage("The configuration value was not confirmed as stored. Review its content-free state before retrying.");
    } finally {
      setBusy(null);
    }
  }, [configurationValues, onServer, retryRequestId, secretVault.availability, server, transport.storeMcpManagedConfiguration, userPresenceAvailable]);

  const removeConfiguration = useCallback(async (requirementId: string) => {
    const mutate = transport.removeMcpManagedConfiguration;
    if (!mutate || !userPresenceAvailable || secretVault.availability !== "available") return;
    setBusy(`remove-configuration:${requirementId}`);
    setMessage(null);
    const retryKey = `configuration:${requirementId}:${server.revision}:remove`;
    try {
      const receipt = await mutate(server.management_id, requirementId, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
      });
      mutationRequestIds.current.delete(retryKey);
      setConfigurationValues((current) => ({ ...current, [requirementId]: "" }));
      onServer(receipt.server);
      setMessage("Configuration removed from Windows Credential Manager.");
    } catch {
      setMessage("Configuration removal was not verified. The record now reports whether cleanup is required.");
    } finally {
      setBusy(null);
    }
  }, [onServer, retryRequestId, secretVault.availability, server, transport.removeMcpManagedConfiguration, userPresenceAvailable]);

  const probeServer = useCallback(async () => {
    const probe = transport.probeMcpManagedServer;
    if (!probe || !userPresenceAvailable
      || server.probe_action !== "available_native_confirmation_required") return;
    setBusy("probe");
    setMessage(null);
    const retryKey = `probe:${server.revision}`;
    try {
      const receipt = await probe(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: server.revision,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage(`Compatibility verified with MCP ${receipt.probe.protocol_version}. The connection is closed and no tool was called.`);
    } catch (error: unknown) {
      setMessage(compatibilityFailureMessage(error));
    } finally {
      setBusy(null);
    }
  }, [onServer, retryRequestId, server, transport.probeMcpManagedServer, userPresenceAvailable]);

  const inspectLocalConfiguration = useCallback(async () => {
    const inspect = transport.inspectMcpManagedLocalConfiguration;
    if (!inspect || !configurationInspectionPreview
      || configurationInspectionPreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `configuration-inspection:${configurationInspectionPreview.preview_digest}`;
    setBusy("configuration-inspection");
    setMessage(null);
    try {
      const receipt = await inspect(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: configurationInspectionPreview.expected_revision,
        preview_digest: configurationInspectionPreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage(
        `Package configuration inspected without execution. ${receipt.inspection.requirement_ids.length} content-free requirement${receipt.inspection.requirement_ids.length === 1 ? "" : "s"} retained; the archive, manifest content, and all values were discarded.`,
      );
    } catch {
      setMessage("Package configuration was not verified. No process or terminal was started; reload the exact inspection preview before retrying.");
      setConfigurationInspectionState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [
    busy,
    configurationInspectionPreview,
    onServer,
    retryRequestId,
    server.management_id,
    transport.inspectMcpManagedLocalConfiguration,
    userPresenceAvailable,
  ]);

  const applyLifecycle = useCallback(async () => {
    const mutate = transport.applyMcpManagedLifecycle;
    if (!mutate || !lifecyclePreview || lifecyclePreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const action = lifecyclePreview.action;
    const retryKey = `lifecycle:${action}:${lifecyclePreview.preview_digest}`;
    setBusy(`lifecycle:${action}`);
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, action, {
        request_id: retryRequestId(retryKey),
        expected_revision: lifecyclePreview.expected_revision,
        preview_digest: lifecyclePreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      onAcceptanceEvidence?.({ kind: "lifecycle", receipt });
      setMessage(action === "install" && receipt.server.installation_kind === "local_package"
        ? "Local package installed from its verified checksum. The bounded compatibility process stopped with verified process-tree cleanup; no host, retained connection, or tool authority remains."
        : action === "install"
          ? "Remote plan activated. No process, retained connection, package, or tool authority was created."
        : receipt.installation_kind === "local_package"
          ? "Verified local package removed through digest-bound quarantine. No process or terminal was started; the reviewed plan remains available for a later reinstall."
          : "Remote activation removed. The reviewed plan and compatibility evidence remain available.");
    } catch {
      setMessage("The lifecycle change was not confirmed. Reload the exact preview before retrying.");
      setLifecycleState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [
    busy,
    lifecyclePreview,
    onAcceptanceEvidence,
    onServer,
    retryRequestId,
    server.management_id,
    transport.applyMcpManagedLifecycle,
    userPresenceAvailable,
  ]);

  const completeCleanup = useCallback(async () => {
    const mutate = transport.completeMcpManagedLocalCleanup;
    if (!mutate || !cleanupPreview || cleanupPreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `cleanup:${cleanupPreview.preview_digest}`;
    setBusy("cleanup");
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: cleanupPreview.expected_revision,
        preview_digest: cleanupPreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage(receipt.filesystem_changed
        ? "Interrupted local-package removal completed. Package absence was verified and the cleanup journal was cleared without starting a process."
        : "The interrupted removal had already removed the package. Its absence was verified and only the cleanup journal was cleared.");
    } catch {
      setMessage("Cleanup was not verified. The recovery journal remains intact; reload the exact preview before retrying.");
      setCleanupState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [
    busy,
    cleanupPreview,
    onServer,
    retryRequestId,
    server.management_id,
    transport.completeMcpManagedLocalCleanup,
    userPresenceAvailable,
  ]);

  const applyUpdate = useCallback(async () => {
    const mutate = transport.applyMcpManagedLocalUpdate;
    if (!mutate || !updatePreview || updatePreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `update:${updatePreview.preview_digest}`;
    setBusy("update");
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: updatePreview.expected_revision,
        preview_digest: updatePreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      onAcceptanceEvidence?.({ kind: "update", receipt });
      setMessage("The exact target was checksum-verified, probed in isolation, and published. Its process tree is stopped; one verified rollback generation is retained.");
    } catch {
      setMessage("The update did not commit. Reload the exact preview; any ambiguous filesystem state remains blocked for explicit recovery.");
      setUpdateState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [busy, onAcceptanceEvidence, onServer, retryRequestId, server.management_id, transport.applyMcpManagedLocalUpdate, updatePreview, userPresenceAvailable]);

  const applyRollback = useCallback(async () => {
    const mutate = transport.applyMcpManagedLocalRollback;
    if (!mutate || !rollbackPreview || rollbackPreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `rollback:${rollbackPreview.preview_digest}`;
    setBusy("rollback");
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: rollbackPreview.expected_revision,
        preview_digest: rollbackPreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      onAcceptanceEvidence?.({ kind: "rollback", receipt });
      setMessage("The two verified package generations were atomically exchanged without starting a process. The superseded generation remains available for a reversible rollback.");
    } catch {
      setMessage("Rollback was not confirmed. Reload the exact preview or use the recovery journal if the operation is blocked.");
      setRollbackState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [busy, onAcceptanceEvidence, onServer, retryRequestId, rollbackPreview, server.management_id, transport.applyMcpManagedLocalRollback, userPresenceAvailable]);

  const cleanupRollback = useCallback(async () => {
    const mutate = transport.cleanupMcpManagedLocalRollback;
    if (!mutate || !rollbackCleanupPreview || rollbackCleanupPreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `rollback-cleanup:${rollbackCleanupPreview.preview_digest}`;
    setBusy("rollback-cleanup");
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: rollbackCleanupPreview.expected_revision,
        preview_digest: rollbackCleanupPreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      onAcceptanceEvidence?.({ kind: "rollback_cleanup", receipt });
      setMessage(receipt.filesystem_changed
        ? "The exact retained rollback generation was verified and removed. The current package stayed installed and no process started."
        : "The retained generation was already absent; its durable record was finalized without starting a process.");
    } catch {
      setMessage("Rollback-generation cleanup was not verified. The retained journal remains authoritative.");
      setRollbackCleanupState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [busy, onAcceptanceEvidence, onServer, retryRequestId, rollbackCleanupPreview, server.management_id, transport.cleanupMcpManagedLocalRollback, userPresenceAvailable]);

  const recoverOperation = useCallback(async () => {
    const mutate = transport.recoverMcpManagedLocalOperation;
    if (!mutate || !operationRecoveryPreview || operationRecoveryPreview.availability !== "available"
      || !userPresenceAvailable || busy !== null) return;
    const retryKey = `operation-recovery:${operationRecoveryPreview.preview_digest}`;
    setBusy("operation-recovery");
    setMessage(null);
    try {
      const receipt = await mutate(server.management_id, {
        request_id: retryRequestId(retryKey),
        expected_revision: operationRecoveryPreview.expected_revision,
        preview_digest: operationRecoveryPreview.preview_digest,
      });
      mutationRequestIds.current.delete(retryKey);
      onServer(receipt.server);
      setMessage(`Interrupted ${receipt.recovered_action} recovery verified the filesystem and restored a usable installed state without starting a process.`);
    } catch {
      setMessage("Interrupted-operation recovery remains unconfirmed. The cleanup journal is preserved and all new package operations stay blocked.");
      setOperationRecoveryState("unavailable");
    } finally {
      setBusy(null);
    }
  }, [busy, onServer, operationRecoveryPreview, retryRequestId, server.management_id, transport.recoverMcpManagedLocalOperation, userPresenceAvailable]);

  const secretRequirements = server.requirements.filter((item) => item.secret);
  const ordinaryRequirements = server.requirements.filter((item) => !item.secret);
  const userConfigurationRequirements = ordinaryRequirements.filter(
    (item) => item.user_value_needed,
  );
  const declaredConfigurationRequirements = ordinaryRequirements.filter(
    (item) => !item.user_value_needed,
  );
  const operationRecoveryApplies = operationRecoveryState === "ready"
    && operationRecoveryPreview?.interrupted_action !== null
    && operationRecoveryPreview?.interrupted_action !== undefined;

  return (
    <section aria-labelledby="agent-mcp-managed-title" className="agent-mcp-managed">
      <button className="button button--ghost agent-mcp-store__back" onClick={onBack} type="button">
        Back to MCP Store
      </button>
      <header className="agent-mcp-managed__head">
        <span>
          <small>{server.installation_state === "installed"
            ? server.installation_kind === "local_package" ? "Installed local package" : "Activated remote plan"
            : server.installation_state === "cleanup_required" ? "Cleanup required"
            : "Prepared plan"} · revision {server.revision}</small>
          <h3 id="agent-mcp-managed-title">{server.server_title}</h3>
          <code>{server.server_name} · {server.server_version}</code>
        </span>
        <span data-state={server.lifecycle_state}>{server.lifecycle_state.replaceAll("_", " ")}</span>
      </header>
      <p className="agent-mcp-store__review-boundary">
        {server.option_kind === "remote_server"
          ? "This durable record survives restart. A remote activation only remembers the exact reviewed plan; it does not keep a connection, start a process, install a package, call a tool, or route authority to a model. Compatibility checks still close after bounded schema inspection."
          : server.installation_state === "installed"
            ? "This checksum-pinned MCPB package and its content-free verification evidence survive restart. Exact updates retain at most one verified rollback generation until you restore or remove it. Every compatibility process is hidden, bounded, and stopped with its owned process tree verified. No persistent host, retained connection, tool call, or model authority was created."
            : server.installation_state === "cleanup_required"
              ? "A local-package operation was interrupted or could not confirm cleanup. The retained content-free journal blocks every new lifecycle change until an explicit, digest-bound recovery is natively confirmed. Recovery starts no package process and grants no tool authority."
            : "This durable reviewed plan survives restart. Only an exact MCPB release with a declared SHA-256 digest and stdio transport can be installed after native confirmation. Unsupported registries remain explicit; no package, process, connection, tool call, or model authority exists yet."}
      </p>
      {message && <p className="agent-mcp-managed__message" role="status">{message}</p>}

      <dl className="agent-mcp-managed__status-grid">
        <div><dt>Option</dt><dd>{server.option_kind.replaceAll("_", " ")}</dd></div>
        <div><dt>Identity</dt><dd>{optionIdentity(server)}</dd></div>
        <div><dt>Install</dt><dd>{server.installation_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Install kind</dt><dd>{server.installation_kind.replaceAll("_", " ")}</dd></div>
        <div><dt>Operation</dt><dd>{server.operation_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Host</dt><dd>{server.host_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Health</dt><dd>{server.health_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Updates</dt><dd>{server.update_state.replaceAll("_", " ")}</dd></div>
        <div><dt>Tool routing</dt><dd>{server.tool_routing_state}</dd></div>
        <div><dt>Plan digest</dt><dd><code>{server.plan_revision.slice(0, 12)}</code></dd></div>
      </dl>

      {onAcceptanceRunChange !== undefined && (
        <AgentMcpAcceptancePanel
          activeProjectId={preferredProjectId}
          activeSessionId={activeSessionId}
          eventHead={activeEventHead}
          onRunChange={onAcceptanceRunChange}
          run={acceptanceRun}
          server={server}
        />
      )}

      {server.option_kind === "local_package" && server.installation_state === "not_installed" && (
        <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-configuration-inspection-title">
          <header>
            <span>
              <h4 id="agent-mcp-managed-configuration-inspection-title">Package configuration checkpoint</h4>
              <small>Inspect the exact MCPB manifest before entering values or installing. Inspection reads a bounded schema only and never executes the package.</small>
            </span>
            <b>{server.local_configuration_inspection
              ? "Inspected"
              : configurationInspectionState === "loading"
                ? "Checking"
                : configurationInspectionState === "ready"
                  ? "Review"
                  : "Unavailable"}</b>
          </header>
          {server.local_configuration_inspection ? (
            <>
              <dl className="agent-mcp-managed__status-grid">
                <div><dt>Artifact SHA-256</dt><dd><code>{server.local_configuration_inspection.artifact_sha256.slice(0, 12)}</code></dd></div>
                <div><dt>Artifact size</dt><dd>{server.local_configuration_inspection.artifact_bytes.toLocaleString("en-US")} bytes</dd></div>
                <div><dt>Manifest</dt><dd>MCPB {server.local_configuration_inspection.manifest_version}</dd></div>
                <div><dt>Manifest digest</dt><dd><code>{server.local_configuration_inspection.manifest_digest.slice(0, 12)}</code></dd></div>
                <div><dt>Configuration schema</dt><dd><code>{server.local_configuration_inspection.configuration_schema_digest.slice(0, 12)}</code></dd></div>
                <div><dt>Inputs discovered</dt><dd>{server.local_configuration_inspection.requirement_ids.length}</dd></div>
                <div><dt>Inspected</dt><dd>{new Date(server.local_configuration_inspection.inspected_at).toLocaleString()}</dd></div>
                <div><dt>Execution</dt><dd>Not started</dd></div>
              </dl>
              <p>Inspection is complete. The archive and staging tree were discarded; no value, default, manifest content, connection, or tool authority was retained.</p>
            </>
          ) : configurationInspectionState === "loading" ? (
            <p role="status">Loading the exact non-executing inspection preview…</p>
          ) : configurationInspectionState === "unavailable" ? (
            <p role="status">The package inspection preview could not be verified. Installation stays blocked and no process was started.</p>
          ) : configurationInspectionPreview ? (
            <div className="agent-mcp-managed__lifecycle">
              <p><strong>{configurationInspectionReasonLabels[configurationInspectionPreview.reason]}</strong></p>
              <ul>
                {configurationInspectionPreview.effects.map((effect) => (
                  <li key={effect}>{configurationInspectionEffectLabels[effect]}</li>
                ))}
              </ul>
              <small>Preview digest · <code>{configurationInspectionPreview.preview_digest.slice(0, 12)}</code> · revision {configurationInspectionPreview.expected_revision}</small>
              {configurationInspectionPreview.availability === "available" && (
                <button
                  className="button button--ghost"
                  disabled={!userPresenceAvailable || busy !== null || transport.inspectMcpManagedLocalConfiguration === undefined}
                  onClick={() => void inspectLocalConfiguration()}
                  type="button"
                >
                  {busy === "configuration-inspection" ? "Inspecting without execution…" : "Inspect package configuration"}
                </button>
              )}
              {!userPresenceAvailable && configurationInspectionPreview.availability === "available" && (
                <small>Open the native Agent window to confirm this exact package download and non-executing inspection.</small>
              )}
            </div>
          ) : null}
        </section>
      )}

      {server.local_package_evidence && (
        <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-package-evidence-title">
          <header>
            <span>
              <h4 id="agent-mcp-managed-package-evidence-title">Verified local package</h4>
              <small>Content-free integrity, manifest, runtime, and cleanup evidence persisted across restart.</small>
            </span>
            <b>Verified</b>
          </header>
          <dl className="agent-mcp-managed__status-grid">
            <div><dt>Artifact SHA-256</dt><dd><code>{server.local_package_evidence.artifact_sha256.slice(0, 12)}</code></dd></div>
            <div><dt>Artifact size</dt><dd>{server.local_package_evidence.artifact_bytes.toLocaleString("en-US")} bytes</dd></div>
            <div><dt>Published tree</dt><dd><code>{server.local_package_evidence.tree_digest.slice(0, 12)}</code></dd></div>
            <div><dt>Manifest</dt><dd>MCPB {server.local_package_evidence.manifest_version}</dd></div>
            <div><dt>Manifest digest</dt><dd><code>{server.local_package_evidence.manifest_digest.slice(0, 12)}</code></dd></div>
            <div><dt>License</dt><dd>{server.local_package_evidence.license_state}</dd></div>
            <div><dt>Runtime</dt><dd>{server.local_package_evidence.runtime_kind}{server.local_package_evidence.runtime_version ? ` · ${server.local_package_evidence.runtime_version}` : ""}</dd></div>
            <div><dt>Process tree</dt><dd>{server.process_tree_cleanup}</dd></div>
          </dl>
        </section>
      )}

      {server.installation_state === "installed" && server.installation_kind === "local_package" && (
        <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-update-title">
          <header>
            <span>
              <h4 id="agent-mcp-managed-update-title">Registry latest update</h4>
              <small>Live read-only resolution of the Official Registry <code>latest</code> alias. This check changes no package, process, connection, or permission.</small>
            </span>
            <b>{updateState === "ready" && updatePreview
              ? updatePreview.availability === "available" ? "Candidate" : "Checked"
              : updateState === "loading" ? "Checking" : "Unavailable"}</b>
          </header>
          {updateState === "loading" && <p role="status">Resolving the latest alias and rebinding one exact version…</p>}
          {updateState === "unavailable" && (
            <p role="status">The latest-version preview could not be verified. The installed package was not changed.</p>
          )}
          {updateState === "ready" && updatePreview && (
            <div className="agent-mcp-managed__lifecycle">
              <p><strong>{updateReasonLabels[updatePreview.reason]}</strong></p>
              <dl className="agent-mcp-managed__status-grid">
                <div><dt>Installed</dt><dd>{updatePreview.current_version}</dd></div>
                <div><dt>Resolved target</dt><dd>{updatePreview.target_version ?? "Not available"}</dd></div>
                <div><dt>Current plan</dt><dd><code>{updatePreview.current_plan_revision.slice(0, 12)}</code></dd></div>
                <div><dt>Target plan</dt><dd>{updatePreview.target_plan_revision
                  ? <code>{updatePreview.target_plan_revision.slice(0, 12)}</code>
                  : "Not admitted"}</dd></div>
              </dl>
              {updatePreview.availability === "available" && (
                <>
                  <ul>
                    {updatePreview.effects.map((effect) => (
                      <li key={effect}>{updateEffectLabels[effect]}</li>
                    ))}
                  </ul>
                  <button
                    className="button button--ghost"
                    disabled={!userPresenceAvailable || busy !== null || transport.applyMcpManagedLocalUpdate === undefined}
                    onClick={() => void applyUpdate()}
                    type="button"
                  >
                    {busy === "update" ? "Verifying and publishing…" : `Update to ${updatePreview.target_version ?? "verified target"}`}
                  </button>
                  {!userPresenceAvailable && (
                    <small>Open the native Agent window to confirm this exact update.</small>
                  )}
                </>
              )}
              <small>Preview digest · <code>{updatePreview.preview_digest.slice(0, 12)}</code> · revision {updatePreview.expected_revision}</small>
            </div>
          )}
        </section>
      )}

      {server.installation_state === "installed" && server.rollback_generation && (
        <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-rollback-title">
          <header>
            <span>
              <h4 id="agent-mcp-managed-rollback-title">Retained rollback generation</h4>
              <small>One bounded, checksum-verified generation. Restore it or explicitly remove it; neither action starts package code.</small>
            </span>
            <b>1 retained</b>
          </header>
          <dl className="agent-mcp-managed__status-grid">
            <div><dt>Version</dt><dd>{server.rollback_generation.server_version}</dd></div>
            <div><dt>Plan</dt><dd><code>{server.rollback_generation.plan_revision.slice(0, 12)}</code></dd></div>
            <div><dt>Tree</dt><dd><code>{server.rollback_generation.local_package_evidence.tree_digest.slice(0, 12)}</code></dd></div>
            <div><dt>Retained</dt><dd>{new Date(server.rollback_generation.retained_at).toLocaleString()}</dd></div>
          </dl>
          {rollbackState === "loading" && <p role="status">Verifying rollback eligibility…</p>}
          {rollbackState === "unavailable" && <p role="status">The rollback preview could not be verified. No package state changed.</p>}
          {rollbackState === "ready" && rollbackPreview && (
            <div className="agent-mcp-managed__lifecycle">
              <p><strong>{rollbackReasonLabels[rollbackPreview.reason]}</strong></p>
              {rollbackPreview.availability === "available" && (
                <>
                  <ul>{rollbackPreview.effects.map((effect) => <li key={effect}>{rollbackEffectLabels[effect]}</li>)}</ul>
                  <button
                    className="button button--ghost"
                    disabled={!userPresenceAvailable || busy !== null || transport.applyMcpManagedLocalRollback === undefined}
                    onClick={() => void applyRollback()}
                    type="button"
                  >
                    {busy === "rollback" ? "Exchanging generations…" : `Roll back to ${rollbackPreview.target_version ?? "retained version"}`}
                  </button>
                </>
              )}
              <small>Rollback preview · <code>{rollbackPreview.preview_digest.slice(0, 12)}</code> · revision {rollbackPreview.expected_revision}</small>
            </div>
          )}
          {rollbackCleanupState === "loading" && <p role="status">Verifying retained-generation cleanup…</p>}
          {rollbackCleanupState === "unavailable" && <p role="status">The retained-generation cleanup preview could not be verified.</p>}
          {rollbackCleanupState === "ready" && rollbackCleanupPreview && (
            <div className="agent-mcp-managed__lifecycle">
              <p><strong>{rollbackReasonLabels[rollbackCleanupPreview.reason]}</strong></p>
              {rollbackCleanupPreview.availability === "available" && (
                <>
                  <ul>{rollbackCleanupPreview.effects.map((effect) => <li key={effect}>{rollbackCleanupEffectLabels[effect]}</li>)}</ul>
                  <button
                    className="button button--ghost"
                    disabled={!userPresenceAvailable || busy !== null || transport.cleanupMcpManagedLocalRollback === undefined}
                    onClick={() => void cleanupRollback()}
                    type="button"
                  >
                    {busy === "rollback-cleanup" ? "Verifying exact removal…" : "Remove retained generation"}
                  </button>
                </>
              )}
              <small>Cleanup preview · <code>{rollbackCleanupPreview.preview_digest.slice(0, 12)}</code> · revision {rollbackCleanupPreview.expected_revision}</small>
            </div>
          )}
        </section>
      )}

      <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-tools-title">
        <header>
          <span>
            <h4 id="agent-mcp-managed-tools-title">Reviewed tools</h4>
            <small>Local-only contracts from one closed probe. Reviewing a tool does not start a host or allow a call.</small>
          </span>
          <b>{server.tool_snapshot?.tool_count ?? 0}</b>
        </header>
        {server.tool_review_state === "probe_required" && (
          <p>No current tool snapshot exists. Complete the guarded compatibility check or verified local-package install first.</p>
        )}
        {toolState === "loading" && <p role="status">Loading the exact local tool contracts…</p>}
        {toolState === "unavailable" && (
          <div className="agent-mcp-managed__read-recovery" role="status">
            <p>The reviewed tools could not be verified. Project admission remains blocked.</p>
            {transport.getMcpManagedToolSnapshot && (
              <button className="button button--ghost" onClick={() => setToolAttempt((value) => value + 1)} type="button">
                Retry reviewed tools
              </button>
            )}
          </div>
        )}
        {toolState === "ready" && toolSnapshot && (
          <>
            <dl className="agent-mcp-managed__status-grid">
              <div><dt>Snapshot</dt><dd><code>{toolSnapshot.snapshot_id.slice(0, 12)}</code></dd></div>
              <div><dt>Source</dt><dd>{toolSnapshot.source.replaceAll("_", " ")}</dd></div>
              <div><dt>Protocol</dt><dd>{toolSnapshot.protocol_version}</dd></div>
              <div><dt>Reviewed</dt><dd>{new Date(toolSnapshot.reviewed_at).toLocaleString()}</dd></div>
            </dl>
            {toolSnapshot.tools.length === 0 ? (
              <p>This server declared no tools. It cannot be admitted to a project.</p>
            ) : (
              <ul className="agent-mcp-managed__tools">
                {toolSnapshot.tools.map((tool) => (
                  <li key={tool.tool_id}>
                    <span>
                      <strong>{tool.title ?? tool.name}</strong>
                      <code>{tool.name}</code>
                    </span>
                    {tool.description && <p>{tool.description}</p>}
                    <small>Model alias · <code>{tool.model_alias}</code></small>
                    <details>
                      <summary>Review exact input schema</summary>
                      <pre>{JSON.stringify(tool.input_schema, null, 2)}</pre>
                      <small>Contract · <code>{tool.contract_digest.slice(0, 12)}</code></small>
                    </details>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-projects-title">
        <header>
          <span>
            <h4 id="agent-mcp-managed-projects-title">Project admission</h4>
            <small>Choose one project, every inferred permission, and the exact reviewed tools it may see.</small>
          </span>
          <b>{server.project_bindings.filter((item) => item.enabled).length}</b>
        </header>
        {projectsState === "loading" && <p>Loading Agent projects…</p>}
        {projectsState === "unavailable" && (
          <div className="agent-mcp-managed__read-recovery" role="status">
            <p>Agent projects could not be loaded. No grant was changed and no fallback project was selected.</p>
            {transport.listAgentProjects && (
              <button className="button button--ghost" onClick={() => setProjectsAttempt((value) => value + 1)} type="button">
                Retry Agent projects
              </button>
            )}
          </div>
        )}
        {projectsState === "ready" && projects.length === 0 && <p>Create an Agent project before preparing a project-scoped MCP plan.</p>}
        {projectsState === "ready" && projects.length > 0 && (
          <div className="agent-mcp-managed__project-editor">
            <label>
              Agent project
              <select onChange={(event) => setSelectedProject(event.target.value)} value={selectedProject}>
                <option value="">Choose a project…</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.name}{project.project_id === preferredProjectId ? " · active chat" : ""}
                  </option>
                ))}
              </select>
            </label>
            {preferredProjectId !== null && !preferredProjectAvailable && (
              <p className="agent-mcp-managed__context-warning" role="alert">
                The active chat project is not available in the editable project list. No different project was selected automatically.
              </p>
            )}
            {selectedProject !== "" && (
              <p className="agent-mcp-managed__selection-note">
                {selectedProject === preferredProjectId
                  ? "Editing the active chat project."
                  : "Editing another project; the active chat keeps its own independent admission."}
                {selectedBinding
                  ? ` Current state: ${selectedBinding.admission_state.replaceAll("_", " ")} · revision ${selectedBinding.revision}.`
                  : " No saved admission exists for this project."}
              </p>
            )}
            <fieldset disabled={!selectedProject || busy !== null}>
              <legend>Required runtime permissions</legend>
              {server.required_permissions.map((permission) => (
                <label key={permission}>
                  <input
                    checked={grants.includes(permission)}
                    onChange={() => toggleGrant(permission)}
                    type="checkbox"
                  />
                  <span><strong>{permissionLabels[permission]}</strong><small>{permission.replaceAll("_", " ")}</small></span>
                </label>
              ))}
              {server.required_permissions.length === 0 && <p>No runtime authority was inferred from this Registry option.</p>}
            </fieldset>
            <div className="agent-mcp-managed__tool-selector">
              <label>
                Filter reviewed tools
                <input
                  disabled={!selectedProject || busy !== null || toolState !== "ready"}
                  onChange={(event) => setToolFilter(event.target.value)}
                  placeholder="Name or capability"
                  type="search"
                  value={toolFilter}
                />
              </label>
              <div aria-label="Reviewed tool selection actions" role="group">
                <button
                  className="button button--ghost"
                  disabled={!selectedProject || busy !== null || toolState !== "ready" || visibleReviewedTools.length === 0}
                  onClick={selectVisibleTools}
                  type="button"
                >
                  Select visible
                </button>
                <button
                  className="button button--ghost"
                  disabled={!selectedProject || busy !== null || admittedTools.length === 0}
                  onClick={clearTools}
                  type="button"
                >
                  Clear selected
                </button>
              </div>
              <small>{admittedTools.length} selected · {visibleReviewedTools.length} shown</small>
            </div>
            <fieldset disabled={!selectedProject || busy !== null || toolState !== "ready"}>
              <legend>Allowed reviewed tools</legend>
              {visibleReviewedTools.map((tool) => (
                <label key={tool.tool_id}>
                  <input
                    checked={admittedTools.includes(tool.tool_id)}
                    onChange={() => toggleTool(tool.tool_id)}
                    type="checkbox"
                  />
                  <span>
                    <strong>{tool.title ?? tool.name}</strong>
                    <small>{tool.name}</small>
                  </span>
                </label>
              ))}
              {toolState === "loading" && <p>Loading reviewed tools…</p>}
              {toolState === "unavailable" && <p>Tool review is unavailable; no admission can be saved.</p>}
              {toolState === "idle" && <p>Run the guarded compatibility check before choosing tools.</p>}
              {toolState === "ready" && toolSnapshot?.tools.length === 0 && <p>This snapshot contains no tools.</p>}
              {toolState === "ready" && toolSnapshot && toolSnapshot.tools.length > 0 && visibleReviewedTools.length === 0 && (
                <p>No reviewed tools match this filter.</p>
              )}
            </fieldset>
            <button
              className="button button--ghost"
              disabled={!selectedProject || !userPresenceAvailable || !allPermissionsGranted || admittedTools.length === 0
                || !projectSelectionChanged
                || toolState !== "ready" || busy !== null
                || transport.setMcpManagedProjectBinding === undefined}
              onClick={() => void saveProject()}
              type="button"
            >
              {busy === `project:${selectedProject}`
                ? "Confirming…"
                : projectSelectionChanged ? "Save project admission" : "Admission already current"}
            </button>
            {!userPresenceAvailable && <small>Open the native app window to confirm project permission changes.</small>}
          </div>
        )}
        <AgentMcpManagedRuntimePanel
          acceptanceEventHead={activeEventHead}
          binding={selectedBinding}
          onAcceptanceEvidence={onAcceptanceEvidence}
          onRuntimeChange={onRuntimeChange}
          projectId={selectedProject}
          server={server}
          transport={transport}
          userPresenceAvailable={userPresenceAvailable}
        />
        {server.project_bindings.length > 0 && (
          <ul className="agent-mcp-managed__bindings">
            {server.project_bindings.map((binding) => (
              <li key={binding.project_id}>
                <span>
                  <strong>{binding.project_name}</strong>
                  <small>{binding.admission_state === "admitted"
                    ? `${binding.admitted_tool_ids.length} admitted · runtime status shown above when selected`
                    : binding.admission_state === "review_required"
                      ? "Review required · no tool admission"
                      : "Disabled · no grants"}</small>
                </span>
                {binding.enabled && (
                  <button
                    className="button button--ghost"
                    disabled={!userPresenceAvailable || busy !== null || transport.setMcpManagedProjectBinding === undefined}
                    onClick={() => void disableProject(binding.project_id)}
                    type="button"
                  >
                    {busy === `disable:${binding.project_id}` ? "Confirming…" : "Disable plan"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-config-title">
        <header>
          <span>
            <h4 id="agent-mcp-managed-config-title">Configuration readiness</h4>
            <small>Only content-free state is durable. User values stay in Windows Credential Manager and are never returned to the API or model context.</small>
          </span>
          <b>{server.requirements.length}</b>
        </header>
        {declaredConfigurationRequirements.length > 0 && (
          <ul className="agent-mcp-managed__requirements">
            {declaredConfigurationRequirements.map((requirement) => (
              <li key={requirement.requirement_id}>
                <span><code>{requirement.name}</code><small>{requirement.location.replaceAll("_", " ")}</small></span>
                <strong>{requirementStateLabels[requirement.configuration_state]}</strong>
              </li>
            ))}
          </ul>
        )}
        {userConfigurationRequirements.length > 0 && (
          <div aria-label="Required configuration values" className="agent-mcp-managed__secrets">
            <p>
              Required non-secret values use the same OS-vault boundary as credentials because paths, tenant IDs, and other configuration can still be private.
            </p>
            {userConfigurationRequirements.map((requirement) => {
              const canStore = requirement.configuration_state === "value_required"
                || requirement.configuration_state === "value_store_failed";
              const canRemove = requirement.configuration_state === "value_stored"
                || requirement.configuration_state === "value_cleanup_required";
              const value = configurationValues[requirement.requirement_id] ?? "";
              return (
                <article key={requirement.requirement_id}>
                  <header>
                    <span>
                      <code>{requirement.name}</code>
                      <small>{requirement.location.replaceAll("_", " ")} · {requirement.format}</small>
                    </span>
                    <strong>{requirementStateLabels[requirement.configuration_state]}</strong>
                  </header>
                  {canStore ? (
                    <div>
                      <label>
                        Configuration value for {requirement.name}
                        {requirement.format === "boolean" ? (
                          <select
                            autoComplete="off"
                            disabled={secretVault.availability !== "available" || busy !== null}
                            onChange={(event) => setConfigurationValues((current) => ({ ...current, [requirement.requirement_id]: event.target.value }))}
                            value={value}
                          >
                            <option value="">Choose true or false</option>
                            <option value="true">true</option>
                            <option value="false">false</option>
                          </select>
                        ) : (
                          <input
                            autoComplete="off"
                            disabled={secretVault.availability !== "available" || busy !== null}
                            inputMode={requirement.format === "number" ? "decimal" : undefined}
                            maxLength={2048}
                            onChange={(event) => setConfigurationValues((current) => ({ ...current, [requirement.requirement_id]: event.target.value }))}
                            placeholder={requirement.format === "filepath" ? "Absolute path" : undefined}
                            spellCheck={false}
                            type="text"
                            value={value}
                          />
                        )}
                      </label>
                      <button
                        className="button button--ghost"
                        disabled={!userPresenceAvailable || secretVault.availability !== "available" || !value || busy !== null || transport.storeMcpManagedConfiguration === undefined}
                        onClick={() => void storeConfiguration(requirement.requirement_id)}
                        type="button"
                      >
                        {busy === `configuration:${requirement.requirement_id}`
                          ? "Confirming…"
                          : requirement.configuration_state === "value_store_failed"
                            ? "Retry configuration store"
                            : "Store configuration"}
                      </button>
                    </div>
                  ) : canRemove ? (
                    <button
                      className="button button--ghost"
                      disabled={!userPresenceAvailable || secretVault.availability !== "available" || busy !== null || transport.removeMcpManagedConfiguration === undefined}
                      onClick={() => void removeConfiguration(requirement.requirement_id)}
                      type="button"
                    >
                      {busy === `remove-configuration:${requirement.requirement_id}`
                        ? "Confirming…"
                        : requirement.configuration_state === "value_cleanup_required"
                          ? "Retry configuration cleanup"
                          : "Remove configuration"}
                    </button>
                  ) : (
                    <p>No new action is allowed while this OS-vault operation needs reconciliation.</p>
                  )}
                </article>
              );
            })}
          </div>
        )}
        {secretRequirements.length > 0 && (
          <div className="agent-mcp-managed__secrets">
            <p>
              Vault: {secretVault.availability === "available" ? "Windows Credential Manager available" : "unavailable"}.
              Values never enter the Agent database, API response, or model context.
            </p>
            {secretRequirements.map((requirement) => {
              const canStore = requirement.configuration_state === "secret_missing" || requirement.configuration_state === "secret_store_failed";
              const canRemove = requirement.configuration_state === "secret_stored" || requirement.configuration_state === "secret_cleanup_required";
              return (
                <article key={requirement.requirement_id}>
                  <header>
                    <span><code>{requirement.name}</code><small>{requirement.location.replaceAll("_", " ")}</small></span>
                    <strong>{requirementStateLabels[requirement.configuration_state]}</strong>
                  </header>
                  {canStore ? (
                    <div>
                      <label>
                        Credential value
                        <input
                          autoComplete="new-password"
                          disabled={secretVault.availability !== "available" || busy !== null}
                          maxLength={2048}
                          onChange={(event) => setSecretValues((current) => ({ ...current, [requirement.requirement_id]: event.target.value }))}
                          spellCheck={false}
                          type="password"
                          value={secretValues[requirement.requirement_id] ?? ""}
                        />
                      </label>
                      <button
                        className="button button--ghost"
                        disabled={!userPresenceAvailable || secretVault.availability !== "available" || !(secretValues[requirement.requirement_id] ?? "") || busy !== null || transport.storeMcpManagedSecret === undefined}
                        onClick={() => void storeSecret(requirement.requirement_id)}
                        type="button"
                      >
                        {busy === `secret:${requirement.requirement_id}`
                          ? "Confirming…"
                          : requirement.configuration_state === "secret_store_failed"
                            ? "Retry OS-vault store"
                            : "Store in OS vault"}
                      </button>
                    </div>
                  ) : canRemove ? (
                    <button
                      className="button button--ghost"
                      disabled={!userPresenceAvailable || secretVault.availability !== "available" || busy !== null || transport.removeMcpManagedSecret === undefined}
                      onClick={() => void removeSecret(requirement.requirement_id)}
                      type="button"
                    >
                      {busy === `remove-secret:${requirement.requirement_id}`
                        ? "Confirming…"
                        : requirement.configuration_state === "secret_cleanup_required"
                          ? "Retry OS-vault cleanup"
                          : "Remove from OS vault"}
                    </button>
                  ) : (
                    <p>No new action is allowed while this vault operation needs reconciliation.</p>
                  )}
                </article>
              );
            })}
          </div>
        )}
        {server.requirements.length === 0 && (
          <p>{server.option_kind === "local_package" && server.local_configuration_inspection === null
            ? "Package inputs are not yet known. Complete the non-executing package configuration checkpoint above before assuming this package needs no values."
            : "This reviewed option declares no configuration inputs."}</p>
        )}
      </section>

      <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-probe-title">
        <header>
          <span>
            <h4 id="agent-mcp-managed-probe-title">Compatibility check</h4>
            <small>{server.option_kind === "local_package"
              ? "The package install performs one hidden handshake and schema inspection, then verifies full process-tree cleanup."
              : "Handshake and tool schemas only. No tool call, result, persistent host, or package change."}</small>
          </span>
          <b>{server.last_probe ? "Verified" : "Not checked"}</b>
        </header>
        {server.last_probe && (
          <dl className="agent-mcp-managed__status-grid">
            <div><dt>Protocol</dt><dd>{server.last_probe.protocol_version}</dd></div>
            <div><dt>Tools declared</dt><dd>{server.last_probe.tool_count}</dd></div>
            <div><dt>Schema digest</dt><dd><code>{server.last_probe.schema_digest.slice(0, 12)}</code></dd></div>
            <div><dt>Duration</dt><dd>{server.last_probe.elapsed_ms} ms</dd></div>
            <div><dt>Connection</dt><dd>Closed after probe</dd></div>
            <div><dt>Checked</dt><dd>{new Date(server.last_probe.checked_at).toLocaleString()}</dd></div>
          </dl>
        )}
        {server.probe_action === "available_native_confirmation_required" && (
          <button
            className="button button--ghost"
            disabled={!userPresenceAvailable || busy !== null || transport.probeMcpManagedServer === undefined}
            onClick={() => void probeServer()}
            type="button"
          >
            {busy === "probe" ? "Checking and closing…" : server.last_probe ? "Check again" : "Run compatibility check"}
          </button>
        )}
        {server.probe_action === "unavailable_install_required" && (
          <p>The reviewed local package must pass guarded installation before its hidden stdio host can be checked.</p>
        )}
        {server.probe_action === "unavailable_configuration_required" && (
          <p>Complete every required value or OS-vault credential before connecting this endpoint.</p>
        )}
        {server.probe_action === "unavailable_option_unsupported" && (
          <p>This option has no fixed, secure, supported endpoint for a guarded check.</p>
        )}
        {server.probe_action === "not_applicable_verified_during_install" && (
          <p>The installed package already passed its guarded stdio handshake. Its process tree is verified stopped; installing it did not retain a host or grant tool authority.</p>
        )}
        {!userPresenceAvailable && server.probe_action === "available_native_confirmation_required" && (
          <small>Open the native Agent window to confirm this one outbound compatibility check.</small>
        )}
      </section>

      <section className="agent-mcp-managed__section" aria-labelledby="agent-mcp-managed-lifecycle-title">
        <header>
          <span>
            <h4 id="agent-mcp-managed-lifecycle-title">{server.installation_state === "cleanup_required" ? "Recovery preview" : "Lifecycle preview"}</h4>
            <small>Exact revision-bound effects shown before native confirmation.</small>
          </span>
          <b>{server.installation_state === "cleanup_required" ? "Recover" : lifecycleAction === "install"
            ? server.option_kind === "local_package" ? "Install" : "Activate"
            : "Remove"}</b>
        </header>
        {server.installation_state === "cleanup_required" && operationRecoveryState === "loading" && <p role="status">Loading the interrupted-operation recovery journal…</p>}
        {server.installation_state === "cleanup_required" && operationRecoveryApplies && operationRecoveryPreview && (
          <div className="agent-mcp-managed__lifecycle">
            <p><strong>{recoveryReasonLabels[operationRecoveryPreview.reason]}</strong></p>
            <p>Interrupted action · <strong>{operationRecoveryPreview.interrupted_action}</strong></p>
            <ul>
              {operationRecoveryPreview.effects.map((effect) => (
                <li key={effect}>{recoveryEffectLabels[effect]}</li>
              ))}
            </ul>
            <small>Preview digest · <code>{operationRecoveryPreview.preview_digest.slice(0, 12)}</code> · revision {operationRecoveryPreview.expected_revision}</small>
            {operationRecoveryPreview.availability === "available" && (
              <button
                className="button button--ghost"
                disabled={!userPresenceAvailable || busy !== null || transport.recoverMcpManagedLocalOperation === undefined}
                onClick={() => void recoverOperation()}
                type="button"
              >
                {busy === "operation-recovery" ? "Verifying filesystem state…" : `Recover interrupted ${operationRecoveryPreview.interrupted_action}`}
              </button>
            )}
            {!userPresenceAvailable && operationRecoveryPreview.availability === "available" && (
              <small>Open the native Agent window to confirm this exact recovery.</small>
            )}
          </div>
        )}
        {server.installation_state === "cleanup_required" && !operationRecoveryApplies && cleanupState === "loading" && operationRecoveryState !== "loading" && <p role="status">Loading the exact removal recovery preview…</p>}
        {server.installation_state === "cleanup_required" && !operationRecoveryApplies && cleanupState === "unavailable" && (
          <p role="status">The recovery preview could not be verified. The cleanup journal remains intact.</p>
        )}
        {server.installation_state === "cleanup_required" && !operationRecoveryApplies && cleanupState === "ready" && cleanupPreview && (
          <div className="agent-mcp-managed__lifecycle">
            <p><strong>{cleanupReasonLabels[cleanupPreview.reason]}</strong></p>
            <ul>
              {cleanupPreview.effects.map((effect) => (
                <li key={effect}>{cleanupEffectLabels[effect]}</li>
              ))}
            </ul>
            <small>Preview digest · <code>{cleanupPreview.preview_digest.slice(0, 12)}</code> · revision {cleanupPreview.expected_revision}</small>
            {cleanupPreview.availability === "available" && (
              <button
                className="button button--ghost"
                disabled={!userPresenceAvailable || busy !== null || transport.completeMcpManagedLocalCleanup === undefined}
                onClick={() => void completeCleanup()}
                type="button"
              >
                {busy === "cleanup" ? "Confirming exact recovery…" : "Complete interrupted removal"}
              </button>
            )}
            {!userPresenceAvailable && cleanupPreview.availability === "available" && (
              <small>Open the native Agent window to confirm this exact cleanup recovery.</small>
            )}
          </div>
        )}
        {server.installation_state !== "cleanup_required" && lifecycleState === "loading" && <p role="status">Loading the exact lifecycle preview…</p>}
        {server.installation_state !== "cleanup_required" && lifecycleState === "unavailable" && (
          <p role="status">The lifecycle preview could not be verified. No state was changed.</p>
        )}
        {server.installation_state !== "cleanup_required" && lifecycleState === "ready" && lifecyclePreview && (
          <div className="agent-mcp-managed__lifecycle">
            <p><strong>{lifecycleReasonLabels[lifecyclePreview.reason]}</strong></p>
            <ul>
              {lifecyclePreview.effects.map((effect) => (
                <li key={effect}>{lifecycleEffectLabels[effect]}</li>
              ))}
            </ul>
            <small>Preview digest · <code>{lifecyclePreview.preview_digest.slice(0, 12)}</code> · revision {lifecyclePreview.expected_revision}</small>
            {lifecyclePreview.availability === "available" && (
              <button
                className="button button--ghost"
                disabled={!userPresenceAvailable || busy !== null || transport.applyMcpManagedLifecycle === undefined}
                onClick={() => void applyLifecycle()}
                type="button"
              >
                {busy === `lifecycle:${lifecyclePreview.action}`
                  ? "Confirming exact preview…"
                  : lifecyclePreview.action === "install"
                    ? lifecyclePreview.installation_kind === "remote_activation"
                      ? "Activate remote plan"
                      : "Install local package"
                    : lifecyclePreview.installation_kind === "remote_activation"
                      ? "Remove remote activation"
                      : "Remove local package"}
              </button>
            )}
            {!userPresenceAvailable && lifecyclePreview.availability === "available" && (
              <small>Open the native Agent window to confirm this exact lifecycle change.</small>
            )}
          </div>
        )}
      </section>

      <aside className="agent-mcp-store__next-gate">
        <strong>Current-run hosting is explicit and every call is one-shot</strong>
        <p>Store-06c starts only an installed, admitted project host after its exact disclosure and native confirmation. It routes only reviewed aliases, revalidates authority again after a separate confirmation for every call, and removes the connection on Stop or app shutdown. Durable host-action receipts, broader configuration, and final management/chat polish remain Store-06d/06e.</p>
      </aside>
    </section>
  );
}
