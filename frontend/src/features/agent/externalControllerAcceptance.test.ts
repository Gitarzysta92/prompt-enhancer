import { describe, expect, it } from "vitest";

import type {
  AgentControllerOwnership,
  AgentControllerOwnershipReleaseReceipt,
  AgentMcpConnection,
  AgentMcpConnectionList,
} from "../../shared/api/contracts";
import {
  advanceExternalControllerAcceptance,
  beginExternalControllerAcceptance,
  externalControllerAcceptanceBaselineIssue,
  externalControllerAcceptancePassed,
  observeExternalControllerAcceptance,
  type ExternalControllerAcceptanceRun,
} from "./externalControllerAcceptance";

const PRIMARY_ID = "a".repeat(32);
const TARGET_ID = "b".repeat(32);
const PROJECT_ID = "c".repeat(32);
const SESSION_ID = "d".repeat(32);
const OTHER_SESSION_ID = "e".repeat(32);
const ACTIVITY_EPOCH = "f".repeat(32);
const TEST_SEQUENCE = Symbol("synthetic tool sequence");
const TEST_ACTIVITY = Symbol("synthetic tool activity");
type TestActivity = {
  name: string;
  source: AgentMcpConnection["last_tool_source"];
  at: string;
  outcome: AgentMcpConnection["last_tool_outcome"];
};
type SequencedConnection = AgentMcpConnection & {
  [TEST_SEQUENCE]?: number;
  [TEST_ACTIVITY]?: TestActivity;
};

const primary: AgentMcpConnection = {
  contract_version: "agent-mcp-connection.v4",
  connection_id: PRIMARY_ID,
  label: "Synthetic primary controller",
  client_kind: "codex",
  created_at: "2026-09-04T10:00:00Z",
  updated_at: "2026-09-04T10:00:00Z",
  expires_at: "2026-12-04T10:00:00Z",
  last_used_at: null,
  last_tool_at: null,
  last_tool_name: null,
  last_tool_outcome: null,
  last_tool_source: null,
  last_auth_rejected_at: null,
  revoked_at: null,
  revision: 1,
  credential_revision: 1,
  allow_model_lifecycle: false,
  scope: {
    contract_version: "agent-mcp-scope.v1",
    state: "bound",
    project_id: PROJECT_ID,
    project_name: "Synthetic acceptance project",
    catalog_access: "project_only",
    chat_access: "project_only",
    workspace_access: "project_only",
    native_approval_inherited: false,
  },
  state: "active",
};

const target: AgentMcpConnection = {
  ...primary,
  connection_id: TARGET_ID,
  label: "Synthetic target controller",
  client_kind: "claude",
};

function list(
  connections: SequencedConnection[],
  ownerships: AgentControllerOwnership[] = [],
  activityEpoch = ACTIVITY_EPOCH,
): AgentMcpConnectionList {
  return {
    contract_version: "agent-mcp-management.v2",
    activity_epoch: activityEpoch,
    connections,
    active_count: connections.filter((connection) => connection.state === "active").length,
    controller_ownerships: {
      contract_version: "agent-controller-ownership-list.v1",
      ownerships,
      active_count: ownerships.length,
    },
    tool_activity_sequences: connections.map((connection) => {
      const activity = connection[TEST_ACTIVITY];
      return {
      contract_version: "agent-mcp-tool-activity-sequence.v1",
      connection_id: connection.connection_id,
      credential_revision: connection.credential_revision,
      sequence: connection[TEST_SEQUENCE] ?? 0,
      tool_name: activity?.name ?? null,
      tool_source: activity?.source ?? null,
      started_at: activity?.at ?? null,
      completed_at: activity?.outcome === null ? null : activity?.at ?? null,
      outcome: activity?.outcome ?? null,
    };
    }),
  };
}

function tool(
  connection: SequencedConnection,
  name: string,
  at: string,
  source: AgentMcpConnection["last_tool_source"] = "external_client",
  outcome: AgentMcpConnection["last_tool_outcome"] = "succeeded",
): SequencedConnection {
  return {
    ...connection,
    last_used_at: at,
    last_tool_at: at,
    last_tool_name: name,
    last_tool_outcome: outcome,
    last_tool_source: source,
    [TEST_SEQUENCE]: (connection[TEST_SEQUENCE] ?? 0) + 1,
    [TEST_ACTIVITY]: { name, source, at, outcome },
  };
}

function admitTool(
  connection: SequencedConnection,
  name: string,
  at: string,
): SequencedConnection {
  return {
    ...connection,
    [TEST_SEQUENCE]: (connection[TEST_SEQUENCE] ?? 0) + 1,
    [TEST_ACTIVITY]: {
      name,
      source: "external_client",
      at,
      outcome: null,
    },
  };
}

function ownership(overrides: Partial<AgentControllerOwnership> = {}): AgentControllerOwnership {
  return {
    contract_version: "agent-controller-ownership.v1",
    project_id: PROJECT_ID,
    project_name: "Synthetic acceptance project",
    session_id: SESSION_ID,
    session_title: "Synthetic acceptance chat",
    owner_connection_id: PRIMARY_ID,
    owner_label: "Synthetic primary controller",
    owner_client_kind: "codex",
    operation: "turn",
    state: "running",
    cursor: 1,
    last_seq: 1,
    approval_pending: false,
    ownership_started_at: "2026-09-04T10:03:00Z",
    owner_since: "2026-09-04T10:03:00Z",
    updated_at: "2026-09-04T10:03:01Z",
    revision: 2,
    handoff: null,
    native_approval_inherited: false,
    ...overrides,
  };
}

function observe(
  run: ExternalControllerAcceptanceRun,
  catalog: AgentMcpConnectionList,
): ExternalControllerAcceptanceRun {
  return observeExternalControllerAcceptance(run, catalog)!;
}

function toReconnectStatus(): {
  owner: AgentControllerOwnership;
  primaryConnection: AgentMcpConnection;
  run: ExternalControllerAcceptanceRun;
} {
  let primaryConnection = primary;
  let run = beginExternalControllerAcceptance(
    primaryConnection,
    list([primaryConnection, target]),
    PROJECT_ID,
    SESSION_ID,
  );
  primaryConnection = tool(primaryConnection, "agent_discover", "2026-09-04T10:01:00Z");
  run = observe(run, list([primaryConnection, target]));
  primaryConnection = tool(primaryConnection, "agent_catalog", "2026-09-04T10:02:00Z");
  run = observe(run, list([primaryConnection, target]));
  primaryConnection = tool(primaryConnection, "agent_turn", "2026-09-04T10:03:00Z");
  const firstOwner = ownership();
  run = observe(run, list([primaryConnection, target], [firstOwner]));
  run = observe(run, list([primaryConnection, target], [firstOwner]));
  primaryConnection = tool(primaryConnection, "agent_stop", "2026-09-04T10:04:00Z");
  run = observe(run, list([primaryConnection, target]));
  let reconnectOwner = ownership({
    ownership_started_at: "2026-09-04T10:05:00Z",
    owner_since: "2026-09-04T10:05:00Z",
    updated_at: "2026-09-04T10:05:01Z",
    cursor: 2,
    last_seq: 2,
  });
  run = observe(run, list([primaryConnection, target], [reconnectOwner]));
  primaryConnection = tool(primaryConnection, "agent_turn", "2026-09-04T10:06:00Z");
  reconnectOwner = {
    ...reconnectOwner,
    state: "reconnecting",
    cursor: 3,
    last_seq: 4,
    revision: 3,
    updated_at: "2026-09-04T10:06:00Z",
  };
  run = observe(run, list([primaryConnection, target], [reconnectOwner]));
  return { owner: reconnectOwner, primaryConnection, run };
}

describe("external controller acceptance ledger", () => {
  it("requires a clean exact live project/chat baseline", () => {
    expect(externalControllerAcceptanceBaselineIssue(
      primary,
      list([primary]),
      PROJECT_ID,
      null,
    )).toMatch(/Open one live Agent chat/);
    expect(externalControllerAcceptanceBaselineIssue(
      { ...primary, scope: { ...primary.scope, project_id: "f".repeat(32) } },
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    )).toMatch(/exact project/);
    expect(externalControllerAcceptanceBaselineIssue(
      primary,
      list([primary], [ownership()]),
      PROJECT_ID,
      SESSION_ID,
    )).toMatch(/Settle and release/);

    const run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    const serialized = JSON.stringify(run);
    expect(serialized).not.toContain(primary.label);
    expect(serialized).not.toContain(primary.scope.project_name!);
    expect(serialized).not.toMatch(/token|prompt|argument|result|path|configuration/iu);
  });

  it("completes the exact ordered two-controller lifecycle", () => {
    let { owner: currentOwner, primaryConnection, run } = toReconnectStatus();

    primaryConnection = tool(primaryConnection, "agent_control", "2026-09-04T10:07:00Z");
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    expect(run.phase).toBe("reconnect_wait");

    primaryConnection = tool(primaryConnection, "agent_wait", "2026-09-04T10:08:00Z");
    currentOwner = {
      ...currentOwner,
      cursor: 4,
      last_seq: 5,
      revision: 4,
      updated_at: "2026-09-04T10:08:00Z",
    };
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    expect(run.phase).toBe("handoff_offer");
    expect(run.completedSteps).toContain("reconnect");

    primaryConnection = tool(primaryConnection, "agent_control", "2026-09-04T10:09:00Z");
    currentOwner = {
      ...currentOwner,
      revision: 5,
      updated_at: "2026-09-04T10:09:00Z",
      handoff: {
        target_connection_id: TARGET_ID,
        target_label: "Synthetic target controller",
        target_client_kind: "claude",
        offered_at: "2026-09-04T10:09:00Z",
        expires_at: "2026-09-04T10:19:00Z",
      },
    };
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    expect(run.phase).toBe("handoff_accept");

    let targetConnection = tool(target, "agent_control", "2026-09-04T10:10:00Z");
    currentOwner = {
      ...currentOwner,
      owner_connection_id: TARGET_ID,
      owner_label: "Synthetic target controller",
      owner_client_kind: "claude",
      owner_since: "2026-09-04T10:10:00Z",
      updated_at: "2026-09-04T10:10:00Z",
      revision: 6,
      handoff: null,
    };
    run = observe(run, list([primaryConnection, targetConnection], [currentOwner]));
    expect(run.phase).toBe("revoke");
    expect(run.completedSteps).toContain("handoff");

    targetConnection = {
      ...targetConnection,
      state: "revoked",
      revoked_at: "2026-09-04T10:11:00Z",
      updated_at: "2026-09-04T10:11:00Z",
      revision: 2,
    };
    currentOwner = {
      ...currentOwner,
      state: "revoked",
      revision: 7,
      updated_at: "2026-09-04T10:11:00Z",
    };
    run = observe(run, list([primaryConnection, targetConnection], [currentOwner]));
    expect(run.phase).toBe("post_revoke_refusal");

    targetConnection = {
      ...targetConnection,
      last_auth_rejected_at: "2026-09-04T10:12:00Z",
    };
    run = observe(run, list([primaryConnection, targetConnection], [currentOwner]));
    expect(run.phase).toBe("cleanup");

    const release: AgentControllerOwnershipReleaseReceipt = {
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      released_connection_id: TARGET_ID,
      released_revision: 7,
      released_at: "2026-09-04T10:13:00Z",
      released_by: "native",
      session_settled: true,
      native_approval_inherited: false,
    };
    run = advanceExternalControllerAcceptance(run, {
      kind: "native_release",
      receipt: release,
    })!;

    expect(externalControllerAcceptancePassed(run)).toBe(true);
    expect(run.phase).toBe("complete");
    expect(run.completedSteps).toEqual([
      "connect",
      "discovery",
      "ownership",
      "stream",
      "stop",
      "reconnect",
      "handoff",
      "revoke",
      "refusal",
      "cleanup",
    ]);
  });

  it("credits ownership and streaming from an admitted in-flight turn", () => {
    let primaryConnection: SequencedConnection = primary;
    let run = beginExternalControllerAcceptance(
      primaryConnection,
      list([primaryConnection]),
      PROJECT_ID,
      SESSION_ID,
    );
    primaryConnection = tool(primaryConnection, "agent_discover", "2026-09-04T10:01:00Z");
    run = observe(run, list([primaryConnection]));
    primaryConnection = tool(primaryConnection, "agent_catalog", "2026-09-04T10:02:00Z");
    run = observe(run, list([primaryConnection]));
    primaryConnection = admitTool(primaryConnection, "agent_turn", "2026-09-04T10:03:00Z");
    run = observe(run, list([primaryConnection], [ownership()]));

    expect(run.phase).toBe("first_stop");
    expect(run.completedSteps).toEqual(["connect", "discovery", "ownership", "stream"]);
  });

  it("ignores stale and native-self-test receipts", () => {
    let run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    run = observe(run, list([tool(
      primary,
      "agent_discover",
      "2026-09-04T10:01:00Z",
      "native_self_test",
    )]));
    expect(run.phase).toBe("connect_discover");

    const baseline = tool(primary, "agent_discover", "2026-09-04T10:01:00Z");
    run = beginExternalControllerAcceptance(
      baseline,
      list([baseline]),
      PROJECT_ID,
      SESSION_ID,
    );
    run = observe(run, list([baseline]));
    expect(run.phase).toBe("connect_discover");
  });

  it("fails closed on credential rotation and cross-chat ownership", () => {
    let run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    run = observe(run, list([{ ...primary, credential_revision: 2, revision: 2 }]));
    expect(run.invalidReason).toBe("credential_changed");

    run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    run = observe(run, list([primary], [ownership({ session_id: OTHER_SESSION_ID })]));
    expect(run.invalidReason).toBe("cross_scope_ownership");
  });

  it("fails closed across a service restart or an unobserved activity gap", () => {
    let run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    run = observe(run, list([primary], [], "0".repeat(32)));
    expect(run.invalidReason).toBe("activity_epoch_changed");

    run = beginExternalControllerAcceptance(
      primary,
      list([primary]),
      PROJECT_ID,
      SESSION_ID,
    );
    const discover = tool(primary, "agent_discover", "2026-09-04T10:01:00Z");
    const skippedCatalog = tool(discover, "agent_catalog", "2026-09-04T10:02:00Z");
    run = observe(run, list([skippedCatalog]));
    expect(run.invalidReason).toBe("activity_gap");
  });

  it("rejects message resubmission during reconnect", () => {
    let { owner: currentOwner, primaryConnection, run } = toReconnectStatus();
    primaryConnection = tool(primaryConnection, "agent_turn", "2026-09-04T10:07:00Z");
    currentOwner = { ...currentOwner, revision: 4 };
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    expect(run.invalidReason).toBe("out_of_order");
  });

  it("detects a hidden reconnect resubmission even when a later status call is latest", () => {
    let { owner: currentOwner, primaryConnection, run } = toReconnectStatus();
    primaryConnection = tool(primaryConnection, "agent_turn", "2026-09-04T10:07:00Z");
    primaryConnection = tool(primaryConnection, "agent_control", "2026-09-04T10:08:00Z");
    currentOwner = { ...currentOwner, revision: 4 };
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    expect(run.invalidReason).toBe("activity_gap");
  });

  it("rejects a handoff to an inactive or cross-project target", () => {
    let { owner: currentOwner, primaryConnection, run } = toReconnectStatus();
    primaryConnection = tool(primaryConnection, "agent_control", "2026-09-04T10:07:00Z");
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    primaryConnection = tool(primaryConnection, "agent_wait", "2026-09-04T10:08:00Z");
    currentOwner = { ...currentOwner, cursor: 4, last_seq: 5, revision: 4 };
    run = observe(run, list([primaryConnection, target], [currentOwner]));
    primaryConnection = tool(primaryConnection, "agent_control", "2026-09-04T10:09:00Z");
    currentOwner = {
      ...currentOwner,
      revision: 5,
      handoff: {
        target_connection_id: TARGET_ID,
        target_label: "Synthetic target controller",
        target_client_kind: "claude",
        offered_at: "2026-09-04T10:09:00Z",
        expires_at: "2026-09-04T10:19:00Z",
      },
    };
    run = observe(run, list([primaryConnection, { ...target, state: "expired" }], [currentOwner]));
    expect(run.invalidReason).toBe("handoff_invalid");
  });

  it("requires a strictly post-revocation refusal and exact native release", () => {
    const release: AgentControllerOwnershipReleaseReceipt = {
      contract_version: "agent-controller-ownership.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      released_connection_id: TARGET_ID,
      released_revision: 7,
      released_at: "2026-09-04T10:13:00Z",
      released_by: "native",
      session_settled: true,
      native_approval_inherited: false,
    };
    const premature = advanceExternalControllerAcceptance(
      beginExternalControllerAcceptance(primary, list([primary]), PROJECT_ID, SESSION_ID),
      { kind: "native_release", receipt: release },
    )!;
    expect(premature.invalidReason).toBe("out_of_order");

    const cleanupRun: ExternalControllerAcceptanceRun = {
      ...beginExternalControllerAcceptance(primary, list([primary]), PROJECT_ID, SESSION_ID),
      phase: "cleanup",
      completedSteps: [
        "connect", "discovery", "ownership", "stream", "stop",
        "reconnect", "handoff", "revoke", "refusal",
      ],
      targetConnectionId: TARGET_ID,
      targetCredentialRevision: 1,
      revokedOwnershipRevision: 7,
      revokedAt: "2026-09-04T10:11:00Z",
      rejectedAfterRevokeAt: "2026-09-04T10:12:00Z",
    };
    const wrong = advanceExternalControllerAcceptance(cleanupRun, {
      kind: "native_release",
      receipt: { ...release, session_id: OTHER_SESSION_ID },
    })!;
    expect(wrong.invalidReason).toBe("release_invalid");
  });
});
