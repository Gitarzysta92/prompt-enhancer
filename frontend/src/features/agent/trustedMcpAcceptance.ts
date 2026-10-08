import type {
  AgentEvent,
  McpManagedHostStatus,
  McpManagedLifecycleReceipt,
  McpManagedLocalRollbackCleanupReceipt,
  McpManagedLocalRollbackReceipt,
  McpManagedLocalUpdateReceipt,
  McpManagedServer,
  McpManagedToolSnapshot,
} from "../../shared/api/contracts";

export type TrustedMcpAcceptancePhase =
  | "install"
  | "project_admission"
  | "host_start"
  | "tool_call"
  | "host_stop"
  | "update"
  | "rollback"
  | "rollback_cleanup"
  | "uninstall"
  | "complete";

export type TrustedMcpAcceptanceInvalidReason =
  | "evidence_invalid"
  | "out_of_order";

export type TrustedMcpAcceptanceStep =
  | "baseline"
  | Exclude<TrustedMcpAcceptancePhase, "complete">;

export type TrustedMcpAcceptanceRun = {
  contractVersion: "trusted-mcp-acceptance.v1";
  managementId: string;
  projectId: string;
  sessionId: string;
  serverTitle: string;
  initialPlanRevision: string;
  currentPlanRevision: string;
  serverRevision: number;
  eventFloor: number;
  toolSnapshotId: string | null;
  admittedToolIds: string[];
  admittedModelAliases: string[];
  hostInstanceId: string | null;
  phase: TrustedMcpAcceptancePhase;
  completedSteps: TrustedMcpAcceptanceStep[];
  invalidReason: TrustedMcpAcceptanceInvalidReason | null;
};

export type TrustedMcpAcceptanceEvidence =
  | { kind: "lifecycle"; receipt: McpManagedLifecycleReceipt }
  | {
      kind: "project_admission";
      projectId: string;
      server: McpManagedServer;
      toolSnapshot: McpManagedToolSnapshot;
    }
  | { eventFloor: number; kind: "host_started"; status: McpManagedHostStatus }
  | { kind: "host_stopped"; status: McpManagedHostStatus }
  | { kind: "update"; receipt: McpManagedLocalUpdateReceipt }
  | { kind: "rollback"; receipt: McpManagedLocalRollbackReceipt }
  | { kind: "rollback_cleanup"; receipt: McpManagedLocalRollbackCleanupReceipt };

const ORDERED_PHASES: readonly Exclude<TrustedMcpAcceptancePhase, "complete">[] = [
  "install",
  "project_admission",
  "host_start",
  "tool_call",
  "host_stop",
  "update",
  "rollback",
  "rollback_cleanup",
  "uninstall",
];

export function trustedMcpBaselineIssue(
  server: McpManagedServer,
  projectId: string | null,
  sessionId: string | null,
): string | null {
  if (projectId === null || sessionId === null) {
    return "Open one live Agent chat inside a saved project before beginning this proof.";
  }
  if (server.option_kind !== "local_package" || server.registry_type !== "mcpb") {
    return "This proof requires an exact local MCPB package plan.";
  }
  if (server.installation_state !== "not_installed" || server.installation_kind !== "none") {
    return "Begin with the reviewed package not installed. Remove it cleanly before starting a new proof.";
  }
  if (server.installed_plan_revision !== null
    || server.installed_at !== null
    || server.local_package_evidence !== null
    || server.last_probe !== null
    || server.tool_snapshot !== null
    || server.rollback_generation !== null) {
    return "Begin only after current and rollback package evidence has been removed cleanly.";
  }
  if (server.install_action !== "available_native_confirmation_required") {
    return "Finish the package inspection, required configuration, and install readiness checks first.";
  }
  if (server.operation_state !== "idle"
    || server.process_tree_cleanup === "unconfirmed"
    || server.host_state !== "not_started"
    || server.tool_routing_state !== "inactive") {
    return "The managed plan must be idle with no host, routing authority, or unconfirmed cleanup.";
  }
  return null;
}

export function beginTrustedMcpAcceptance(
  server: McpManagedServer,
  projectId: string,
  sessionId: string,
  eventFloor: number,
): TrustedMcpAcceptanceRun {
  const issue = trustedMcpBaselineIssue(server, projectId, sessionId);
  if (issue !== null) throw new Error(issue);
  return {
    contractVersion: "trusted-mcp-acceptance.v1",
    managementId: server.management_id,
    projectId,
    sessionId,
    serverTitle: server.server_title,
    initialPlanRevision: server.plan_revision,
    currentPlanRevision: server.plan_revision,
    serverRevision: server.revision,
    eventFloor,
    toolSnapshotId: null,
    admittedToolIds: [],
    admittedModelAliases: [],
    hostInstanceId: null,
    phase: "install",
    completedSteps: ["baseline"],
    invalidReason: null,
  };
}

function managementIdFor(evidence: TrustedMcpAcceptanceEvidence): string {
  if (evidence.kind === "host_started" || evidence.kind === "host_stopped") {
    return evidence.status.management_id;
  }
  if (evidence.kind === "project_admission") return evidence.server.management_id;
  return evidence.receipt.server.management_id;
}

function evidencePhase(
  evidence: TrustedMcpAcceptanceEvidence,
): Exclude<TrustedMcpAcceptancePhase, "tool_call" | "complete"> {
  if (evidence.kind === "lifecycle") return evidence.receipt.action;
  if (evidence.kind === "project_admission") return "project_admission";
  if (evidence.kind === "host_started") return "host_start";
  if (evidence.kind === "host_stopped") return "host_stop";
  return evidence.kind;
}

function invalid(run: TrustedMcpAcceptanceRun, reason: TrustedMcpAcceptanceInvalidReason) {
  return { ...run, invalidReason: reason };
}

function step(
  run: TrustedMcpAcceptanceRun,
  completed: Exclude<TrustedMcpAcceptancePhase, "complete">,
  next: TrustedMcpAcceptancePhase,
  patch: Partial<TrustedMcpAcceptanceRun> = {},
): TrustedMcpAcceptanceRun {
  return {
    ...run,
    ...patch,
    completedSteps: run.completedSteps.includes(completed)
      ? run.completedSteps
      : [...run.completedSteps, completed],
    phase: next,
    invalidReason: null,
  };
}

function authorityAbsent(receipt: {
  connection_retained: false;
  endpoint_connected: false;
  persistent_host_started: false;
  tool_authority_granted: false;
}): boolean {
  return receipt.connection_retained === false
    && receipt.endpoint_connected === false
    && receipt.persistent_host_started === false
    && receipt.tool_authority_granted === false;
}

function installedServerIsClean(server: McpManagedServer): boolean {
  return server.installation_state === "installed"
    && server.installation_kind === "local_package"
    && server.operation_state === "idle"
    && server.host_state === "not_started"
    && server.tool_routing_state === "inactive"
    && server.process_tree_cleanup === "verified"
    && server.local_package_evidence !== null
    && server.last_probe !== null
    && server.last_probe.connection_state === "closed_after_probe"
    && server.last_probe.process_tree_cleanup === "verified"
    && server.last_probe.tool_authority_granted === false
    && server.tool_review_state === "reviewable"
    && server.tool_snapshot !== null;
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const leftSorted = [...left].sort();
  const rightSorted = [...right].sort();
  return leftSorted.every((value, index) => value === rightSorted[index]);
}

function installValid(run: TrustedMcpAcceptanceRun, receipt: McpManagedLifecycleReceipt): boolean {
  return receipt.action === "install"
    && receipt.installation_kind === "local_package"
    && receipt.package_changed
    && receipt.process_started
    && receipt.process_tree_cleanup === "verified"
    && authorityAbsent(receipt)
    && receipt.server.management_id === run.managementId
    && receipt.server.plan_revision === run.initialPlanRevision
    && receipt.server.revision > run.serverRevision
    && installedServerIsClean(receipt.server);
}

function admissionValid(
  run: TrustedMcpAcceptanceRun,
  evidence: Extract<TrustedMcpAcceptanceEvidence, { kind: "project_admission" }>,
): { aliases: string[]; snapshotId: string } | null {
  const { projectId, server, toolSnapshot } = evidence;
  const binding = server.project_bindings.find((item) => item.project_id === projectId);
  if (projectId !== run.projectId
    || server.management_id !== run.managementId
    || server.plan_revision !== run.currentPlanRevision
    || server.revision <= run.serverRevision
    || !installedServerIsClean(server)
    || toolSnapshot.management_id !== run.managementId
    || toolSnapshot.plan_revision !== run.currentPlanRevision
    || toolSnapshot.snapshot_id !== server.tool_snapshot?.snapshot_id
    || binding === undefined
    || !binding.enabled
    || binding.admission_state !== "admitted"
    || binding.tool_snapshot_id !== toolSnapshot.snapshot_id
    || binding.admitted_tool_ids.length === 0) return null;
  const admitted = new Set(binding.admitted_tool_ids);
  const aliases = toolSnapshot.tools
    .filter((tool) => admitted.has(tool.tool_id))
    .map((tool) => tool.model_alias);
  if (admitted.size !== binding.admitted_tool_ids.length
    || aliases.length !== admitted.size
    || new Set(aliases).size !== aliases.length
    || !sameStrings(binding.required_permissions, server.required_permissions)
    || !sameStrings(binding.granted_permissions, server.required_permissions)) return null;
  return { aliases: [...aliases].sort(), snapshotId: toolSnapshot.snapshot_id };
}

function hostStartValid(run: TrustedMcpAcceptanceRun, status: McpManagedHostStatus): boolean {
  const binding = status.binding;
  return status.management_id === run.managementId
    && status.project_id === run.projectId
    && status.state === "ready"
    && status.reason === "healthy"
    && status.instance_id !== null
    && status.process_started
    && status.cleanup_state === "pending"
    && status.host_lease_active
    && status.error_code === null
    && status.tool_calls_available
    && status.tool_routing_state === "project_scoped_fresh_approval"
    && binding !== null
    && binding.management_id === run.managementId
    && binding.project_id === run.projectId
    && binding.server_revision === run.serverRevision
    && binding.plan_revision === run.currentPlanRevision
    && binding.option_kind === "local_package"
    && binding.transport === "stdio"
    && binding.tool_snapshot_id === run.toolSnapshotId
    && sameStrings(binding.admitted_tool_ids, run.admittedToolIds)
    && binding.tool_calls_available
    && binding.tool_routing_state === "project_scoped_fresh_approval";
}

function hostStopValid(run: TrustedMcpAcceptanceRun, status: McpManagedHostStatus): boolean {
  return status.management_id === run.managementId
    && status.project_id === run.projectId
    && status.state === "not_started"
    && (status.reason === "stopped_by_owner" || status.reason === "owner_stop")
    && !status.process_started
    && status.cleanup_state === "verified"
    && !status.host_lease_active
    && !status.tool_calls_available
    && status.tool_routing_state === "inactive"
    && status.error_code === null;
}

function updateValid(run: TrustedMcpAcceptanceRun, receipt: McpManagedLocalUpdateReceipt): boolean {
  const server = receipt.server;
  return receipt.package_changed
    && receipt.process_started
    && receipt.process_tree_cleanup === "verified"
    && receipt.rollback_generation_retained
    && authorityAbsent(receipt)
    && server.management_id === run.managementId
    && server.revision > run.serverRevision
    && server.plan_revision !== run.currentPlanRevision
    && server.installed_plan_revision === server.plan_revision
    && server.rollback_generation !== null
    && installedServerIsClean(server);
}

function rollbackValid(run: TrustedMcpAcceptanceRun, receipt: McpManagedLocalRollbackReceipt): boolean {
  const server = receipt.server;
  return receipt.package_changed
    && !receipt.process_started
    && receipt.process_tree_cleanup === "not_applicable"
    && receipt.rollback_generation_retained
    && authorityAbsent(receipt)
    && server.management_id === run.managementId
    && server.revision > run.serverRevision
    && server.plan_revision === run.initialPlanRevision
    && server.installed_plan_revision === server.plan_revision
    && server.rollback_generation !== null
    && installedServerIsClean(server);
}

function rollbackCleanupValid(
  run: TrustedMcpAcceptanceRun,
  receipt: McpManagedLocalRollbackCleanupReceipt,
): boolean {
  const server = receipt.server;
  return receipt.action === "cleanup_rollback_generation"
    && !receipt.process_started
    && !receipt.rollback_generation_retained
    && authorityAbsent(receipt)
    && server.management_id === run.managementId
    && server.revision > run.serverRevision
    && server.plan_revision === run.currentPlanRevision
    && server.installed_plan_revision === server.plan_revision
    && server.rollback_generation === null
    && installedServerIsClean(server);
}

function uninstallValid(run: TrustedMcpAcceptanceRun, receipt: McpManagedLifecycleReceipt): boolean {
  const server = receipt.server;
  return receipt.action === "uninstall"
    && receipt.installation_kind === "local_package"
    && receipt.package_changed
    && !receipt.process_started
    && receipt.process_tree_cleanup === "not_applicable"
    && authorityAbsent(receipt)
    && server.management_id === run.managementId
    && server.revision > run.serverRevision
    && server.installation_state === "not_installed"
    && server.installation_kind === "none"
    && server.operation_state === "idle"
    && server.installed_plan_revision === null
    && server.installed_at === null
    && server.host_state === "not_started"
    && server.tool_routing_state === "inactive"
    && server.process_tree_cleanup === "not_applicable"
    && server.local_package_evidence === null
    && server.last_probe === null
    && server.tool_snapshot === null
    && server.rollback_generation === null;
}

export function advanceTrustedMcpAcceptance(
  run: TrustedMcpAcceptanceRun | null,
  evidence: TrustedMcpAcceptanceEvidence,
): TrustedMcpAcceptanceRun | null {
  if (run === null || run.invalidReason !== null || run.phase === "complete") return run;
  if (managementIdFor(evidence) !== run.managementId) return run;
  if ((evidence.kind === "project_admission" && evidence.projectId !== run.projectId)
    || ((evidence.kind === "host_started" || evidence.kind === "host_stopped")
      && evidence.status.project_id !== run.projectId)) return run;

  const actualPhase = evidencePhase(evidence);
  if (actualPhase !== run.phase) {
    const actualIndex = ORDERED_PHASES.indexOf(actualPhase);
    const expectedIndex = ORDERED_PHASES.indexOf(run.phase as Exclude<TrustedMcpAcceptancePhase, "complete">);
    return actualIndex < expectedIndex ? run : invalid(run, "out_of_order");
  }

  if (evidence.kind === "lifecycle" && evidence.receipt.action === "install") {
    if (!installValid(run, evidence.receipt)) return invalid(run, "evidence_invalid");
    return step(run, "install", "project_admission", {
      currentPlanRevision: evidence.receipt.server.plan_revision,
      serverRevision: evidence.receipt.server.revision,
      toolSnapshotId: evidence.receipt.server.tool_snapshot!.snapshot_id,
    });
  }
  if (evidence.kind === "project_admission") {
    const admitted = admissionValid(run, evidence);
    if (admitted === null) return invalid(run, "evidence_invalid");
    return step(run, "project_admission", "host_start", {
      admittedModelAliases: admitted.aliases,
      admittedToolIds: [...evidence.server.project_bindings
        .find((item) => item.project_id === evidence.projectId)!.admitted_tool_ids].sort(),
      serverRevision: evidence.server.revision,
      toolSnapshotId: admitted.snapshotId,
    });
  }
  if (evidence.kind === "host_started") {
    if (!hostStartValid(run, evidence.status)) return invalid(run, "evidence_invalid");
    return step(run, "host_start", "tool_call", {
      eventFloor: Math.max(run.eventFloor, evidence.eventFloor),
      hostInstanceId: evidence.status.instance_id,
    });
  }
  if (evidence.kind === "host_stopped") {
    if (!hostStopValid(run, evidence.status)) return invalid(run, "evidence_invalid");
    return step(run, "host_stop", "update", { hostInstanceId: null });
  }
  if (evidence.kind === "update") {
    if (!updateValid(run, evidence.receipt)) return invalid(run, "evidence_invalid");
    return step(run, "update", "rollback", {
      currentPlanRevision: evidence.receipt.server.plan_revision,
      serverRevision: evidence.receipt.server.revision,
      toolSnapshotId: evidence.receipt.server.tool_snapshot!.snapshot_id,
    });
  }
  if (evidence.kind === "rollback") {
    if (!rollbackValid(run, evidence.receipt)) return invalid(run, "evidence_invalid");
    return step(run, "rollback", "rollback_cleanup", {
      currentPlanRevision: evidence.receipt.server.plan_revision,
      serverRevision: evidence.receipt.server.revision,
      toolSnapshotId: evidence.receipt.server.tool_snapshot!.snapshot_id,
    });
  }
  if (evidence.kind === "rollback_cleanup") {
    if (!rollbackCleanupValid(run, evidence.receipt)) return invalid(run, "evidence_invalid");
    return step(run, "rollback_cleanup", "uninstall", {
      serverRevision: evidence.receipt.server.revision,
      toolSnapshotId: evidence.receipt.server.tool_snapshot!.snapshot_id,
    });
  }
  if (evidence.kind === "lifecycle" && evidence.receipt.action === "uninstall") {
    if (!uninstallValid(run, evidence.receipt)) return invalid(run, "evidence_invalid");
    return step(run, "uninstall", "complete", {
      serverRevision: evidence.receipt.server.revision,
      toolSnapshotId: null,
      admittedToolIds: [],
      admittedModelAliases: [],
      hostInstanceId: null,
    });
  }
  return invalid(run, "evidence_invalid");
}

function successfulFreshMcpCall(run: TrustedMcpAcceptanceRun, events: readonly AgentEvent[]): boolean {
  const aliases = new Set(run.admittedModelAliases);
  const calls = new Map<string, AgentEvent[]>();
  for (const event of events) {
    if (event.seq <= run.eventFloor || event.call_id === null || event.call_id === undefined) continue;
    const bucket = calls.get(event.call_id) ?? [];
    bucket.push(event);
    calls.set(event.call_id, bucket);
  }
  for (const call of calls.values()) {
    const request = call.find((event) => event.kind === "tool_call");
    const approval = call.find((event) => event.kind === "approval_required");
    const resolution = call.find((event) => event.kind === "approval_resolved");
    const result = call.find((event) => event.kind === "tool_result");
    const alias = result?.tool ?? request?.tool ?? null;
    const descriptor = result?.mcp_tool ?? resolution?.mcp_tool ?? approval?.mcp_tool ?? null;
    const receipt = result?.mcp_result ?? null;
    if (request === undefined || approval === undefined || resolution === undefined || result === undefined
      || alias === null || !aliases.has(alias)
      || request.tool !== alias || approval.tool !== alias || resolution.tool !== alias
      || !(request.seq < approval.seq && approval.seq < resolution.seq && resolution.seq < result.seq)
      || approval.approval_id === null || approval.approval_id === undefined
      || resolution.approval_id !== approval.approval_id || resolution.ok !== true
      || result.ok !== true || result.tool_state !== "succeeded"
      || result.execution_receipt?.approval_state !== "approved"
      || descriptor === null
      || descriptor.source !== "managed_mcp"
      || descriptor.server_title !== run.serverTitle
      || descriptor.model_alias !== alias
      || !descriptor.every_call_requires_native_approval
      || receipt === null || receipt.outcome !== "succeeded" || !receipt.cleanup_verified
      || receipt.arguments_persisted || receipt.result_text_persisted || receipt.reusable_approval_persisted) continue;
    return true;
  }
  return false;
}

export function observeTrustedMcpAgentEvents(
  run: TrustedMcpAcceptanceRun | null,
  observation: {
    events: readonly AgentEvent[];
    projectId: string | null;
    sessionId: string | null;
  },
): TrustedMcpAcceptanceRun | null {
  if (run === null || run.invalidReason !== null || run.phase !== "tool_call") return run;
  if (observation.projectId !== run.projectId || observation.sessionId !== run.sessionId) return run;
  return successfulFreshMcpCall(run, observation.events)
    ? step(run, "tool_call", "host_stop")
    : run;
}

export function trustedMcpStepPassed(
  run: TrustedMcpAcceptanceRun,
  stepName: TrustedMcpAcceptanceStep,
): boolean {
  return run.completedSteps.includes(stepName);
}
