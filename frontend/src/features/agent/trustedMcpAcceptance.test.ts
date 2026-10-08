import { describe, expect, it } from "vitest";

import type { AgentEvent, McpManagedProjectBinding, McpManagedServer } from "../../shared/api/contracts";
import {
  syntheticMcpManagedLocalLifecycleReceipt,
  syntheticMcpManagedLocalRollbackReceipt,
  syntheticMcpManagedLocalRollbackCleanupReceipt,
  syntheticMcpManagedLocalUninstallReceipt,
  syntheticMcpManagedLocalUpdateReceipt,
  syntheticMcpManagedServer,
  syntheticMcpManagedToolSnapshot,
} from "../../shared/api/mcpManagedServer.test-support";
import {
  syntheticMcpManagedHostBinding,
  syntheticMcpManagedHostStatus,
  syntheticReadyMcpManagedHostStatus,
} from "../../shared/api/mcpManagedRuntime.test-support";
import {
  advanceTrustedMcpAcceptance,
  beginTrustedMcpAcceptance,
  observeTrustedMcpAgentEvents,
  trustedMcpBaselineIssue,
  type TrustedMcpAcceptanceRun,
} from "./trustedMcpAcceptance";

const MANAGEMENT = "9".repeat(32);
const PROJECT = "f".repeat(32);
const SESSION = "e".repeat(32);
const INITIAL_PLAN = "d".repeat(64);
const PERMISSIONS = [
  "process_spawn",
  "filesystem_read",
  "filesystem_write",
  "credential_use",
] as const;

function baseline(): McpManagedServer {
  return syntheticMcpManagedServer({
    management_id: MANAGEMENT,
    option_label: "MCPB release",
    registry_type: "mcpb",
    package_identifier: "https://example.invalid/synthetic.mcpb",
    runtime_hint: "node",
    requirements: [],
    revision: 2,
    install_action: "available_native_confirmation_required",
  });
}

function projectBinding(snapshotId: string): McpManagedProjectBinding {
  return {
    project_id: PROJECT,
    project_name: "Synthetic project",
    enabled: true,
    required_permissions: [...PERMISSIONS],
    granted_permissions: [...PERMISSIONS],
    admitted_tool_ids: ["1".repeat(32)],
    tool_snapshot_id: snapshotId,
    admission_state: "admitted",
    effective_state: "inactive_host_unavailable",
    created_at: "2040-01-01T10:03:00Z",
    updated_at: "2040-01-01T10:03:00Z",
    revision: 1,
  };
}

function event(seq: number, kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return {
    seq,
    kind,
    at: "2040-01-01T10:04:00Z",
    attachments: [],
    ...extra,
  };
}

function acceptedToolEvents(alias: string): AgentEvent[] {
  const callId = "synthetic-call";
  const approvalId = "a".repeat(32);
  const descriptor = {
    contract_version: "agent-mcp-tool.v1" as const,
    source: "managed_mcp" as const,
    server_title: "Synthetic Files",
    tool_name: "synthetic_tool_1",
    tool_title: "Synthetic tool 1",
    model_alias: alias,
    every_call_requires_native_approval: true as const,
  };
  return [
    event(6, "tool_call", { call_id: callId, tool: alias, arguments: {} }),
    event(7, "approval_required", { call_id: callId, tool: alias, approval_id: approvalId, mcp_tool: descriptor }),
    event(8, "approval_resolved", { call_id: callId, tool: alias, approval_id: approvalId, ok: true, mcp_tool: descriptor }),
    event(9, "tool_result", {
      call_id: callId,
      tool: alias,
      ok: true,
      tool_state: "succeeded",
      mcp_tool: descriptor,
      execution_receipt: {
        contract_version: "agent-tool-execution.v1",
        elapsed_ms: 10,
        timing_source: "server_monotonic.v1",
        approval_state: "approved",
        evidence_state: "untracked_external_effect",
      },
      mcp_result: {
        contract_version: "agent-mcp-tool-result.v1",
        managed_call_id: "b".repeat(32),
        outcome: "succeeded",
        content_mode: "text",
        result_bytes: 12,
        result_digest: "c".repeat(64),
        error_code: null,
        cleanup_verified: true,
        arguments_persisted: false,
        result_text_persisted: false,
        reusable_approval_persisted: false,
      },
    }),
  ];
}

function throughAdmission(): {
  run: TrustedMcpAcceptanceRun;
  admitted: McpManagedServer;
  alias: string;
} {
  let run = beginTrustedMcpAcceptance(baseline(), PROJECT, SESSION, 5);
  const install = syntheticMcpManagedLocalLifecycleReceipt();
  run = advanceTrustedMcpAcceptance(run, { kind: "lifecycle", receipt: install })!;
  const snapshot = syntheticMcpManagedToolSnapshot({
    management_id: MANAGEMENT,
    snapshot_id: install.server.tool_snapshot!.snapshot_id,
    plan_revision: INITIAL_PLAN,
    source: "local_package_probe",
    source_tree_digest: install.server.local_package_evidence!.tree_digest,
    source_manifest_digest: install.server.local_package_evidence!.manifest_digest,
  });
  const admitted = {
    ...install.server,
    revision: 4,
    project_bindings: [projectBinding(snapshot.snapshot_id)],
  };
  run = advanceTrustedMcpAcceptance(run, {
    kind: "project_admission",
    projectId: PROJECT,
    server: admitted,
    toolSnapshot: snapshot,
  })!;
  return { run, admitted, alias: snapshot.tools[0].model_alias };
}

describe("trusted MCP lifecycle acceptance", () => {
  it("starts only from an install-ready, authority-free local MCPB plan in a live project chat", () => {
    expect(trustedMcpBaselineIssue(baseline(), PROJECT, SESSION)).toBeNull();
    expect(trustedMcpBaselineIssue(baseline(), PROJECT, null)).toMatch(/live Agent chat/);
    expect(trustedMcpBaselineIssue(syntheticMcpManagedServer(), PROJECT, SESSION)).toMatch(/local MCPB/);
    expect(trustedMcpBaselineIssue({ ...baseline(), process_tree_cleanup: "unconfirmed" }, PROJECT, SESSION)).toMatch(/idle/);
    expect(trustedMcpBaselineIssue({
      ...baseline(),
      rollback_generation: syntheticMcpManagedLocalUpdateReceipt().server.rollback_generation,
    }, PROJECT, SESSION)).toMatch(/rollback package evidence/);

    const run = beginTrustedMcpAcceptance(baseline(), PROJECT, SESSION, 5);
    expect(run.phase).toBe("install");
    expect(run.completedSteps).toEqual(["baseline"]);
    expect(run.eventFloor).toBe(5);
  });

  it("proves one exact install, admission, host call, cleanup, update, rollback and uninstall sequence", () => {
    const admittedStage = throughAdmission();
    let run = admittedStage.run;
    expect(run.phase).toBe("host_start");
    expect(run.admittedModelAliases).toEqual([admittedStage.alias]);

    const hostBinding = syntheticMcpManagedHostBinding({
      management_id: MANAGEMENT,
      project_id: PROJECT,
      server_revision: admittedStage.admitted.revision,
      project_binding_revision: admittedStage.admitted.project_bindings[0].revision,
      plan_revision: INITIAL_PLAN,
      option_kind: "local_package",
      transport: "stdio",
      tool_snapshot_id: admittedStage.admitted.tool_snapshot!.snapshot_id,
      admitted_tool_ids: admittedStage.admitted.project_bindings[0].admitted_tool_ids,
      granted_permissions: [...PERMISSIONS],
    });
    const ready = syntheticReadyMcpManagedHostStatus({ binding: hostBinding });
    run = advanceTrustedMcpAcceptance(run, { eventFloor: 5, kind: "host_started", status: ready })!;
    expect(run.phase).toBe("tool_call");

    run = observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: SESSION,
      events: acceptedToolEvents(admittedStage.alias),
    })!;
    expect(run.phase).toBe("host_stop");

    const stopped = syntheticMcpManagedHostStatus({
      management_id: MANAGEMENT,
      project_id: PROJECT,
      reason: "stopped_by_owner",
      cleanup_state: "verified",
      stopped_at: "2040-01-01T10:05:00Z",
    });
    run = advanceTrustedMcpAcceptance(run, { kind: "host_stopped", status: stopped })!;
    expect(run.phase).toBe("update");

    const update = syntheticMcpManagedLocalUpdateReceipt({
      server: { ...syntheticMcpManagedLocalUpdateReceipt().server, revision: 5 },
    });
    run = advanceTrustedMcpAcceptance(run, { kind: "update", receipt: update })!;
    expect(run.phase).toBe("rollback");

    const rollback = syntheticMcpManagedLocalRollbackReceipt({
      server: { ...syntheticMcpManagedLocalRollbackReceipt().server, revision: 6 },
    });
    run = advanceTrustedMcpAcceptance(run, { kind: "rollback", receipt: rollback })!;
    expect(run.phase).toBe("rollback_cleanup");

    const prematureUninstall = syntheticMcpManagedLocalUninstallReceipt({
      server: { ...syntheticMcpManagedLocalUninstallReceipt().server, revision: 7 },
    });
    expect(advanceTrustedMcpAcceptance(run, {
      kind: "lifecycle",
      receipt: prematureUninstall,
    })?.invalidReason).toBe("out_of_order");
    const retainedCleanup = syntheticMcpManagedLocalRollbackCleanupReceipt({
      server: { ...rollback.server, revision: 7 },
    });
    expect(advanceTrustedMcpAcceptance(run, {
      kind: "rollback_cleanup",
      receipt: retainedCleanup,
    })?.invalidReason).toBe("evidence_invalid");

    const cleanup = syntheticMcpManagedLocalRollbackCleanupReceipt({
      server: { ...rollback.server, revision: 7, rollback_generation: null },
    });
    run = advanceTrustedMcpAcceptance(run, { kind: "rollback_cleanup", receipt: cleanup })!;
    expect(run.phase).toBe("uninstall");

    const uninstall = syntheticMcpManagedLocalUninstallReceipt({
      server: { ...syntheticMcpManagedLocalUninstallReceipt().server, revision: 8 },
    });
    run = advanceTrustedMcpAcceptance(run, { kind: "lifecycle", receipt: uninstall })!;
    expect(run.phase).toBe("complete");
    expect(run.invalidReason).toBeNull();
    expect(run.completedSteps).toEqual([
      "baseline",
      "install",
      "project_admission",
      "host_start",
      "tool_call",
      "host_stop",
      "update",
      "rollback",
      "rollback_cleanup",
      "uninstall",
    ]);
    expect(run.hostInstanceId).toBeNull();
    expect(run.toolSnapshotId).toBeNull();
  });

  it("ignores other scopes and invalidates a future same-server action instead of reordering evidence", () => {
    const run = beginTrustedMcpAcceptance(baseline(), PROJECT, SESSION, 5);
    const other = syntheticMcpManagedLocalLifecycleReceipt({
      server: { ...syntheticMcpManagedLocalLifecycleReceipt().server, management_id: "8".repeat(32) },
    });
    expect(advanceTrustedMcpAcceptance(run, { kind: "lifecycle", receipt: other })).toBe(run);

    const future = syntheticMcpManagedLocalUpdateReceipt({
      server: { ...syntheticMcpManagedLocalUpdateReceipt().server, revision: 5 },
    });
    const invalid = advanceTrustedMcpAcceptance(run, { kind: "update", receipt: future })!;
    expect(invalid.phase).toBe("install");
    expect(invalid.invalidReason).toBe("out_of_order");
  });

  it("does not accept historical, cross-session, denied, or cleanup-unverified MCP calls", () => {
    const admittedStage = throughAdmission();
    const hostBinding = syntheticMcpManagedHostBinding({
      management_id: MANAGEMENT,
      project_id: PROJECT,
      server_revision: admittedStage.admitted.revision,
      project_binding_revision: 1,
      plan_revision: INITIAL_PLAN,
      option_kind: "local_package",
      transport: "stdio",
      tool_snapshot_id: admittedStage.admitted.tool_snapshot!.snapshot_id,
      admitted_tool_ids: ["1".repeat(32)],
      granted_permissions: [...PERMISSIONS],
    });
    let run = advanceTrustedMcpAcceptance(admittedStage.run, {
      eventFloor: 5,
      kind: "host_started",
      status: syntheticReadyMcpManagedHostStatus({ binding: hostBinding }),
    })!;
    const valid = acceptedToolEvents(admittedStage.alias);

    expect(observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: "1".repeat(32),
      events: valid,
    })).toBe(run);
    expect(observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: SESSION,
      events: valid.map((item) => ({ ...item, seq: item.seq - 5 })),
    })).toBe(run);
    expect(observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: SESSION,
      events: valid.map((item) => item.kind === "tool_result"
        ? { ...item, mcp_result: { ...item.mcp_result!, cleanup_verified: false } }
        : item),
    })).toBe(run);
    expect(observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: SESSION,
      events: valid.map((item) => item.kind === "approval_resolved"
        ? { ...item, ok: false }
        : item),
    })).toBe(run);

    run = observeTrustedMcpAgentEvents(run, {
      projectId: PROJECT,
      sessionId: SESSION,
      events: valid,
    })!;
    const unconfirmedStop = syntheticMcpManagedHostStatus({
      management_id: MANAGEMENT,
      project_id: PROJECT,
      reason: "cleanup_unconfirmed",
      cleanup_state: "unconfirmed",
      error_code: "mcp_host_cleanup_unconfirmed",
    });
    const invalid = advanceTrustedMcpAcceptance(run, { kind: "host_stopped", status: unconfirmedStop })!;
    expect(invalid.invalidReason).toBe("evidence_invalid");
    expect(invalid.completedSteps).not.toContain("host_stop");
  });
});
