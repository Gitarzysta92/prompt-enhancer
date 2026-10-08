import type {
  AgentControllerOwnership,
  AgentControllerOwnershipReleaseReceipt,
  AgentMcpConnection,
  AgentMcpConnectionList,
} from "../../shared/api/contracts";

export type ExternalControllerAcceptanceStep =
  | "connect"
  | "discovery"
  | "ownership"
  | "stream"
  | "stop"
  | "reconnect"
  | "handoff"
  | "revoke"
  | "refusal"
  | "cleanup";

export type ExternalControllerAcceptancePhase =
  | "connect_discover"
  | "chat_discovery"
  | "first_claim"
  | "stream"
  | "first_stop"
  | "reconnect_claim"
  | "reconnect_incomplete"
  | "reconnect_status"
  | "reconnect_wait"
  | "handoff_offer"
  | "handoff_accept"
  | "revoke"
  | "post_revoke_refusal"
  | "cleanup"
  | "complete";

export type ExternalControllerAcceptanceInvalidReason =
  | "connection_missing"
  | "credential_changed"
  | "activity_epoch_changed"
  | "activity_gap"
  | "scope_changed"
  | "connection_inactive"
  | "cross_scope_ownership"
  | "out_of_order"
  | "evidence_invalid"
  | "ownership_lost"
  | "stream_not_observed"
  | "handoff_invalid"
  | "release_invalid";

export type ExternalControllerAcceptanceRun = {
  contractVersion: "external-controller-acceptance.v2";
  activityEpoch: string;
  primaryConnectionId: string;
  primaryCredentialRevision: number;
  primaryClientKind: AgentMcpConnection["client_kind"];
  projectId: string;
  sessionId: string;
  baselinePrimaryToolAt: string | null;
  baselinePrimaryToolSequence: number;
  baselinePrimaryAuthRejectedAt: string | null;
  lastPrimaryToolAt: string | null;
  lastPrimaryToolSequence: number;
  phase: ExternalControllerAcceptancePhase;
  completedSteps: ExternalControllerAcceptanceStep[];
  invalidReason: ExternalControllerAcceptanceInvalidReason | null;
  firstOwnershipStartedAt: string | null;
  firstOwnershipRevision: number | null;
  reconnectOwnershipStartedAt: string | null;
  reconnectCursor: number | null;
  reconnectRevision: number | null;
  targetConnectionId: string | null;
  targetCredentialRevision: number | null;
  targetBaselineToolAt: string | null;
  targetBaselineToolSequence: number | null;
  targetBaselineAuthRejectedAt: string | null;
  lastTargetToolAt: string | null;
  lastTargetToolSequence: number | null;
  handoffOfferedRevision: number | null;
  handoffAcceptedRevision: number | null;
  revokedOwnershipRevision: number | null;
  revokedAt: string | null;
  rejectedAfterRevokeAt: string | null;
  releaseReceiptAt: string | null;
};

export type ExternalControllerAcceptanceEvidence = {
  kind: "native_release";
  receipt: AgentControllerOwnershipReleaseReceipt;
};

function parsedTime(value: string | null): number | null {
  if (value === null) return null;
  const result = Date.parse(value);
  return Number.isFinite(result) ? result : null;
}

function newer(candidate: string | null, baseline: string | null): boolean {
  const candidateTime = parsedTime(candidate);
  if (candidateTime === null) return false;
  const baselineTime = parsedTime(baseline);
  return baselineTime === null || candidateTime > baselineTime;
}

function sameOrNewer(candidate: string, baseline: string): boolean {
  const candidateTime = parsedTime(candidate);
  const baselineTime = parsedTime(baseline);
  return candidateTime !== null && baselineTime !== null && candidateTime >= baselineTime;
}

function invalid(
  run: ExternalControllerAcceptanceRun,
  invalidReason: ExternalControllerAcceptanceInvalidReason,
): ExternalControllerAcceptanceRun {
  return { ...run, invalidReason };
}

function step(
  run: ExternalControllerAcceptanceRun,
  completed: ExternalControllerAcceptanceStep | null,
  phase: ExternalControllerAcceptancePhase,
  patch: Partial<ExternalControllerAcceptanceRun> = {},
): ExternalControllerAcceptanceRun {
  return {
    ...run,
    ...patch,
    phase,
    completedSteps: completed === null || run.completedSteps.includes(completed)
      ? run.completedSteps
      : [...run.completedSteps, completed],
    invalidReason: null,
  };
}

function connectionFor(
  catalog: AgentMcpConnectionList,
  connectionId: string,
): AgentMcpConnection | null {
  return catalog.connections.find((item) => item.connection_id === connectionId) ?? null;
}

function ownershipFor(
  catalog: AgentMcpConnectionList,
  sessionId: string,
): AgentControllerOwnership | null {
  return catalog.controller_ownerships.ownerships.find(
    (item) => item.session_id === sessionId,
  ) ?? null;
}

function exactScope(connection: AgentMcpConnection, projectId: string): boolean {
  return connection.scope.state === "bound"
    && connection.scope.project_id === projectId
    && connection.scope.catalog_access === "project_only"
    && connection.scope.chat_access === "project_only"
    && connection.scope.workspace_access === "project_only"
    && connection.scope.native_approval_inherited === false;
}

function exactOwnership(
  ownership: AgentControllerOwnership,
  run: ExternalControllerAcceptanceRun,
  ownerConnectionId: string,
): boolean {
  return ownership.project_id === run.projectId
    && ownership.session_id === run.sessionId
    && ownership.owner_connection_id === ownerConnectionId
    && ownership.operation === "turn"
    && ownership.native_approval_inherited === false;
}

type FreshTool = {
  kind: "external";
  sequence: number;
  at: string;
  name: string;
  outcome: AgentMcpConnection["last_tool_outcome"];
};

type ToolActivity = FreshTool | {
  kind: "none";
  sequence: number;
  at: string | null;
} | {
  kind: "gap";
  sequence: number;
  at: string | null;
} | {
  kind: "self_test";
  sequence: number;
  at: string | null;
};

function activitySequenceFor(
  catalog: AgentMcpConnectionList,
  connection: AgentMcpConnection,
): number | null {
  return catalog.tool_activity_sequences.find(
    (item) => item.connection_id === connection.connection_id
      && item.credential_revision === connection.credential_revision,
  )?.sequence ?? null;
}

function toolActivity(
  catalog: AgentMcpConnectionList,
  connection: AgentMcpConnection,
  baselineSequence: number,
): ToolActivity {
  const cursor = catalog.tool_activity_sequences.find(
    (item) => item.connection_id === connection.connection_id
      && item.credential_revision === connection.credential_revision,
  );
  const sequence = cursor?.sequence ?? null;
  if (sequence === null || sequence < baselineSequence || sequence > baselineSequence + 1) {
    return { kind: "gap", sequence: sequence ?? -1, at: cursor?.started_at ?? null };
  }
  if (sequence === baselineSequence) {
    return { kind: "none", sequence, at: cursor?.started_at ?? null };
  }
  if (
    cursor === undefined
    || cursor.started_at === null
    || cursor.tool_name === null
    || cursor.tool_source === null
  ) return { kind: "gap", sequence, at: cursor?.started_at ?? null };
  if (cursor.tool_source === "native_self_test") {
    return { kind: "self_test", sequence, at: cursor.started_at };
  }
  if (cursor.tool_source !== "external_client") {
    return { kind: "gap", sequence, at: cursor.started_at };
  }
  return {
    kind: "external",
    sequence,
    at: cursor.started_at,
    name: cursor.tool_name,
    outcome: cursor.outcome,
  };
}

function expectedTool(
  run: ExternalControllerAcceptanceRun,
  activity: ToolActivity,
  name: string,
): ExternalControllerAcceptanceRun | null {
  if (activity.kind === "none") return null;
  if (activity.kind === "gap") return invalid(run, "activity_gap");
  if (activity.kind === "self_test") return null;
  if (activity.name !== name) return invalid(run, "out_of_order");
  if (activity.outcome === null) return null;
  if (activity.outcome !== "succeeded") return invalid(run, "evidence_invalid");
  return run;
}

function expectedInFlightTurn(
  run: ExternalControllerAcceptanceRun,
  activity: ToolActivity,
): ExternalControllerAcceptanceRun | null {
  if (activity.kind === "none") return null;
  if (activity.kind === "gap") return invalid(run, "activity_gap");
  if (activity.kind === "self_test") return null;
  if (activity.name !== "agent_turn") return invalid(run, "out_of_order");
  if (activity.outcome === "failed") return invalid(run, "evidence_invalid");
  return run;
}

export function externalControllerAcceptanceBaselineIssue(
  connection: AgentMcpConnection,
  catalog: AgentMcpConnectionList,
  projectId: string | null,
  sessionId: string | null,
): string | null {
  if (projectId === null || sessionId === null) {
    return "Open one live Agent chat inside a saved project before beginning this proof.";
  }
  if (connection.state !== "active") {
    return "Choose an active direct connection. Expired, revoked, and missing-scope credentials cannot begin a proof.";
  }
  if (!exactScope(connection, projectId)) {
    return "The connection must be bound to the exact project of the open live chat.";
  }
  if (activitySequenceFor(catalog, connection) === null) {
    return "The controller activity cursor is unavailable. Refresh the current app instance before beginning this proof.";
  }
  if (catalog.controller_ownerships.ownerships.some(
    (item) => item.session_id === sessionId || item.owner_connection_id === connection.connection_id,
  )) {
    return "Settle and release this connection's existing external control before beginning a new proof.";
  }
  return null;
}

export function beginExternalControllerAcceptance(
  connection: AgentMcpConnection,
  catalog: AgentMcpConnectionList,
  projectId: string,
  sessionId: string,
): ExternalControllerAcceptanceRun {
  const issue = externalControllerAcceptanceBaselineIssue(
    connection,
    catalog,
    projectId,
    sessionId,
  );
  if (issue !== null) throw new Error(issue);
  const baselinePrimaryToolSequence = activitySequenceFor(catalog, connection);
  if (baselinePrimaryToolSequence === null) {
    throw new Error("The controller activity cursor is unavailable.");
  }
  return {
    contractVersion: "external-controller-acceptance.v2",
    activityEpoch: catalog.activity_epoch,
    primaryConnectionId: connection.connection_id,
    primaryCredentialRevision: connection.credential_revision,
    primaryClientKind: connection.client_kind,
    projectId,
    sessionId,
    baselinePrimaryToolAt: connection.last_tool_at,
    baselinePrimaryToolSequence,
    baselinePrimaryAuthRejectedAt: connection.last_auth_rejected_at,
    lastPrimaryToolAt: connection.last_tool_at,
    lastPrimaryToolSequence: baselinePrimaryToolSequence,
    phase: "connect_discover",
    completedSteps: [],
    invalidReason: null,
    firstOwnershipStartedAt: null,
    firstOwnershipRevision: null,
    reconnectOwnershipStartedAt: null,
    reconnectCursor: null,
    reconnectRevision: null,
    targetConnectionId: null,
    targetCredentialRevision: null,
    targetBaselineToolAt: null,
    targetBaselineToolSequence: null,
    targetBaselineAuthRejectedAt: null,
    lastTargetToolAt: null,
    lastTargetToolSequence: null,
    handoffOfferedRevision: null,
    handoffAcceptedRevision: null,
    revokedOwnershipRevision: null,
    revokedAt: null,
    rejectedAfterRevokeAt: null,
    releaseReceiptAt: null,
  };
}

function primaryInvalidReason(
  run: ExternalControllerAcceptanceRun,
  primary: AgentMcpConnection | null,
): ExternalControllerAcceptanceInvalidReason | null {
  if (primary === null) return "connection_missing";
  if (primary.credential_revision !== run.primaryCredentialRevision) return "credential_changed";
  if (!exactScope(primary, run.projectId)) return "scope_changed";
  if (primary.state !== "active") return "connection_inactive";
  return null;
}

function targetInvalidReason(
  run: ExternalControllerAcceptanceRun,
  target: AgentMcpConnection | null,
  allowRevoked: boolean,
): ExternalControllerAcceptanceInvalidReason | null {
  if (target === null) return "connection_missing";
  if (target.credential_revision !== run.targetCredentialRevision) return "credential_changed";
  if (!exactScope(target, run.projectId)) return "scope_changed";
  if (allowRevoked ? !["active", "revoked"].includes(target.state) : target.state !== "active") {
    return "connection_inactive";
  }
  return null;
}

function sameOwnershipRun(
  ownership: AgentControllerOwnership,
  run: ExternalControllerAcceptanceRun,
  ownerConnectionId: string,
  startedAt: string | null,
): boolean {
  return exactOwnership(ownership, run, ownerConnectionId)
    && startedAt !== null
    && ownership.ownership_started_at === startedAt;
}

export function observeExternalControllerAcceptance(
  run: ExternalControllerAcceptanceRun | null,
  catalog: AgentMcpConnectionList,
): ExternalControllerAcceptanceRun | null {
  if (run === null || run.invalidReason !== null || run.phase === "complete") return run;
  if (catalog.activity_epoch !== run.activityEpoch) {
    return invalid(run, "activity_epoch_changed");
  }

  const primary = connectionFor(catalog, run.primaryConnectionId);
  const primaryIssue = primaryInvalidReason(run, primary);
  if (primaryIssue !== null) return invalid(run, primaryIssue);
  if (primary === null) return invalid(run, "connection_missing");

  if (catalog.controller_ownerships.ownerships.some(
    (item) => item.owner_connection_id === run.primaryConnectionId && item.session_id !== run.sessionId,
  )) return invalid(run, "cross_scope_ownership");

  const ownership = ownershipFor(catalog, run.sessionId);
  const primaryActivity = toolActivity(catalog, primary, run.lastPrimaryToolSequence);
  if (primaryActivity.kind === "gap") return invalid(run, "activity_gap");
  if (primaryActivity.kind === "self_test") {
    return {
      ...run,
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
    };
  }

  if (run.phase === "connect_discover") {
    const expected = expectedTool(run, primaryActivity, "agent_discover");
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    return step(run, "connect", "chat_discovery", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
    });
  }

  if (run.phase === "chat_discovery") {
    const expected = expectedTool(run, primaryActivity, "agent_catalog");
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    // The scoped catalog call proves project-only discovery. The exact chat is
    // not credited until the following ownership row binds that same session.
    return step(run, null, "first_claim", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
    });
  }

  if (run.phase === "first_claim") {
    const expected = expectedInFlightTurn(run, primaryActivity);
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    if (ownership === null) return run;
    if (!exactOwnership(ownership, run, run.primaryConnectionId)) {
      return invalid(run, "cross_scope_ownership");
    }
    if (!(["claimed", "running"] as const).includes(ownership.state as "claimed" | "running")) {
      return invalid(run, "stream_not_observed");
    }
    const discovered = step(run, "discovery", "first_claim");
    const owned = step(discovered, "ownership", "stream", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
      firstOwnershipStartedAt: ownership.ownership_started_at,
      firstOwnershipRevision: ownership.revision,
    });
    return ownership.state === "running" && !ownership.approval_pending
      ? step(owned, "stream", "first_stop")
      : owned;
  }

  if (run.phase === "stream") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    if (ownership === null) return invalid(run, "ownership_lost");
    if (!sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.firstOwnershipStartedAt,
    )) return invalid(run, "cross_scope_ownership");
    if (ownership.state === "claimed") return run;
    if (ownership.state !== "running" || ownership.approval_pending) {
      return invalid(run, "stream_not_observed");
    }
    return step(run, "stream", "first_stop");
  }

  if (run.phase === "first_stop") {
    const expected = expectedTool(run, primaryActivity, "agent_stop");
    if (expected !== null && expected.invalidReason !== null) return expected;
    if (ownership !== null && !sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.firstOwnershipStartedAt,
    )) return invalid(run, "cross_scope_ownership");
    if (expected === null || ownership !== null) return run;
    return step(run, "stop", "reconnect_claim", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
    });
  }

  if (run.phase === "reconnect_claim") {
    const expected = expectedInFlightTurn(run, primaryActivity);
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    if (ownership === null) return run;
    if (!exactOwnership(ownership, run, run.primaryConnectionId)) {
      return invalid(run, "cross_scope_ownership");
    }
    if (
      run.firstOwnershipStartedAt === null
      || !newer(ownership.ownership_started_at, run.firstOwnershipStartedAt)
    ) return invalid(run, "evidence_invalid");
    if (ownership.state === "claimed") return run;
    if (ownership.state === "running") {
      return step(run, null, "reconnect_incomplete", {
        lastPrimaryToolAt: primaryActivity.at,
        lastPrimaryToolSequence: primaryActivity.sequence,
        reconnectOwnershipStartedAt: ownership.ownership_started_at,
        reconnectCursor: ownership.cursor,
        reconnectRevision: ownership.revision,
      });
    }
    if (ownership.state === "reconnecting") {
      return step(run, null, "reconnect_status", {
        lastPrimaryToolAt: primaryActivity.at,
        lastPrimaryToolSequence: primaryActivity.sequence,
        reconnectOwnershipStartedAt: ownership.ownership_started_at,
        reconnectCursor: ownership.cursor,
        reconnectRevision: ownership.revision,
      });
    }
    return invalid(run, "stream_not_observed");
  }

  if (run.phase === "reconnect_incomplete") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    if (ownership === null) return invalid(run, "ownership_lost");
    if (!sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.reconnectOwnershipStartedAt,
    )) return invalid(run, "cross_scope_ownership");
    if (ownership.state === "running") return run;
    if (ownership.state !== "reconnecting") return invalid(run, "evidence_invalid");
    return step(run, null, "reconnect_status", {
      reconnectCursor: ownership.cursor,
      reconnectRevision: ownership.revision,
    });
  }

  if (run.phase === "reconnect_status") {
    if (ownership === null) return invalid(run, "ownership_lost");
    if (!sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.reconnectOwnershipStartedAt,
    ) || ownership.state !== "reconnecting") return invalid(run, "evidence_invalid");
    const expected = expectedTool(run, primaryActivity, "agent_control");
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    if (
      ownership.cursor !== run.reconnectCursor
      || ownership.revision !== run.reconnectRevision
    ) return invalid(run, "evidence_invalid");
    return step(run, null, "reconnect_wait", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
    });
  }

  if (run.phase === "reconnect_wait") {
    if (ownership === null) return invalid(run, "ownership_lost");
    if (!sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.reconnectOwnershipStartedAt,
    )) return invalid(run, "cross_scope_ownership");
    const expected = expectedTool(run, primaryActivity, "agent_wait");
    if (expected === null || expected.invalidReason !== null) return expected ?? run;
    if (
      ownership.state !== "reconnecting"
      || run.reconnectCursor === null
      || ownership.cursor < run.reconnectCursor
      || run.reconnectRevision === null
      || ownership.revision <= run.reconnectRevision
    ) return invalid(run, "evidence_invalid");
    return step(run, "reconnect", "handoff_offer", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
      reconnectCursor: ownership.cursor,
      reconnectRevision: ownership.revision,
    });
  }

  if (run.phase === "handoff_offer") {
    if (ownership === null) return invalid(run, "ownership_lost");
    if (!sameOwnershipRun(
      ownership,
      run,
      run.primaryConnectionId,
      run.reconnectOwnershipStartedAt,
    )) return invalid(run, "cross_scope_ownership");
    const expected = expectedTool(run, primaryActivity, "agent_control");
    if (expected !== null && expected.invalidReason !== null) return expected;
    if (ownership.handoff === null || expected === null) return run;
    const target = connectionFor(catalog, ownership.handoff.target_connection_id);
    if (
      target === null
      || target.connection_id === run.primaryConnectionId
      || target.state !== "active"
      || !exactScope(target, run.projectId)
      || (run.reconnectRevision !== null && ownership.revision <= run.reconnectRevision)
      || catalog.controller_ownerships.ownerships.some(
        (item) => item.owner_connection_id === target.connection_id && item.session_id !== run.sessionId,
      )
    ) return invalid(run, "handoff_invalid");
    const targetBaselineToolSequence = activitySequenceFor(catalog, target);
    if (targetBaselineToolSequence === null) return invalid(run, "evidence_invalid");
    return step(run, null, "handoff_accept", {
      lastPrimaryToolAt: primaryActivity.at,
      lastPrimaryToolSequence: primaryActivity.sequence,
      targetConnectionId: target.connection_id,
      targetCredentialRevision: target.credential_revision,
      targetBaselineToolAt: target.last_tool_at,
      targetBaselineToolSequence,
      targetBaselineAuthRejectedAt: target.last_auth_rejected_at,
      lastTargetToolAt: target.last_tool_at,
      lastTargetToolSequence: targetBaselineToolSequence,
      handoffOfferedRevision: ownership.revision,
    });
  }

  if (run.phase === "handoff_accept") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    const target = run.targetConnectionId === null
      ? null
      : connectionFor(catalog, run.targetConnectionId);
    const targetIssue = targetInvalidReason(run, target, false);
    if (targetIssue !== null) return invalid(run, targetIssue);
    if (target === null || ownership === null) return invalid(run, "handoff_invalid");
    if (run.lastTargetToolSequence === null) return invalid(run, "evidence_invalid");
    const targetActivity = toolActivity(catalog, target, run.lastTargetToolSequence);
    if (targetActivity.kind === "gap") return invalid(run, "activity_gap");
    if (targetActivity.kind === "self_test") {
      return {
        ...run,
        lastTargetToolAt: targetActivity.at,
        lastTargetToolSequence: targetActivity.sequence,
      };
    }
    const expected = expectedTool(run, targetActivity, "agent_control");
    if (expected !== null && expected.invalidReason !== null) return expected;
    if (ownership.owner_connection_id === run.primaryConnectionId && ownership.handoff !== null) {
      return run;
    }
    if (!sameOwnershipRun(
      ownership,
      run,
      target.connection_id,
      run.reconnectOwnershipStartedAt,
    ) || ownership.handoff !== null) return invalid(run, "handoff_invalid");
    if (expected === null) return run;
    if (
      run.handoffOfferedRevision === null
      || ownership.revision <= run.handoffOfferedRevision
      || ownership.approval_pending
    ) return invalid(run, "handoff_invalid");
    return step(run, "handoff", "revoke", {
      lastTargetToolAt: targetActivity.at,
      lastTargetToolSequence: targetActivity.sequence,
      handoffAcceptedRevision: ownership.revision,
    });
  }

  if (run.phase === "revoke") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    const target = run.targetConnectionId === null
      ? null
      : connectionFor(catalog, run.targetConnectionId);
    const targetIssue = targetInvalidReason(run, target, true);
    if (targetIssue !== null) return invalid(run, targetIssue);
    if (target === null) return invalid(run, "connection_missing");
    if (run.lastTargetToolSequence === null) return invalid(run, "evidence_invalid");
    const targetActivity = toolActivity(catalog, target, run.lastTargetToolSequence);
    if (targetActivity.kind === "gap") return invalid(run, "activity_gap");
    if (targetActivity.kind === "external") return invalid(run, "out_of_order");
    if (targetActivity.kind === "self_test") {
      return {
        ...run,
        lastTargetToolAt: targetActivity.at,
        lastTargetToolSequence: targetActivity.sequence,
      };
    }
    if (target.state === "active") return run;
    if (
      target.state !== "revoked"
      || target.revoked_at === null
      || ownership === null
      || !sameOwnershipRun(
        ownership,
        run,
        target.connection_id,
        run.reconnectOwnershipStartedAt,
      )
      || ownership.state !== "revoked"
      || run.handoffAcceptedRevision === null
      || ownership.revision <= run.handoffAcceptedRevision
    ) return invalid(run, "evidence_invalid");
    return step(run, "revoke", "post_revoke_refusal", {
      revokedAt: target.revoked_at,
      revokedOwnershipRevision: ownership.revision,
    });
  }

  if (run.phase === "post_revoke_refusal") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    const target = run.targetConnectionId === null
      ? null
      : connectionFor(catalog, run.targetConnectionId);
    const targetIssue = targetInvalidReason(run, target, true);
    if (targetIssue !== null) return invalid(run, targetIssue);
    if (target === null || ownership === null || target.state !== "revoked") {
      return invalid(run, "ownership_lost");
    }
    if (run.lastTargetToolSequence === null) return invalid(run, "evidence_invalid");
    const targetActivity = toolActivity(catalog, target, run.lastTargetToolSequence);
    if (targetActivity.kind === "gap") return invalid(run, "activity_gap");
    if (targetActivity.kind === "external") return invalid(run, "out_of_order");
    if (targetActivity.kind === "self_test") return invalid(run, "out_of_order");
    if (!sameOwnershipRun(
      ownership,
      run,
      target.connection_id,
      run.reconnectOwnershipStartedAt,
    ) || ownership.state !== "revoked") return invalid(run, "evidence_invalid");
    if (
      run.revokedAt === null
      || !newer(target.last_auth_rejected_at, run.revokedAt)
      || !newer(target.last_auth_rejected_at, run.targetBaselineAuthRejectedAt)
    ) return run;
    return step(run, "refusal", "cleanup", {
      rejectedAfterRevokeAt: target.last_auth_rejected_at,
    });
  }

  if (run.phase === "cleanup") {
    if (primaryActivity.kind === "external") return invalid(run, "out_of_order");
    const target = run.targetConnectionId === null
      ? null
      : connectionFor(catalog, run.targetConnectionId);
    const targetIssue = targetInvalidReason(run, target, true);
    if (targetIssue !== null) return invalid(run, targetIssue);
    if (target === null || run.lastTargetToolSequence === null) {
      return invalid(run, "evidence_invalid");
    }
    const targetActivity = toolActivity(catalog, target, run.lastTargetToolSequence);
    if (targetActivity.kind === "gap") return invalid(run, "activity_gap");
    if (targetActivity.kind !== "none") return invalid(run, "out_of_order");
    if (ownership === null) return invalid(run, "ownership_lost");
    if (
      run.targetConnectionId === null
      || !sameOwnershipRun(
        ownership,
        run,
        run.targetConnectionId,
        run.reconnectOwnershipStartedAt,
      )
      || ownership.state !== "revoked"
    ) return invalid(run, "evidence_invalid");
    return run;
  }

  return run;
}

export function advanceExternalControllerAcceptance(
  run: ExternalControllerAcceptanceRun | null,
  evidence: ExternalControllerAcceptanceEvidence,
): ExternalControllerAcceptanceRun | null {
  if (run === null || run.invalidReason !== null || run.phase === "complete") return run;
  if (run.phase !== "cleanup") return invalid(run, "out_of_order");
  const receipt = evidence.receipt;
  if (
    run.targetConnectionId === null
    || run.revokedOwnershipRevision === null
    || receipt.contract_version !== "agent-controller-ownership.v1"
    || receipt.project_id !== run.projectId
    || receipt.session_id !== run.sessionId
    || receipt.released_connection_id !== run.targetConnectionId
    || receipt.released_revision < run.revokedOwnershipRevision
    || receipt.released_by !== "native"
    || receipt.session_settled !== true
    || receipt.native_approval_inherited !== false
    || run.rejectedAfterRevokeAt === null
    || !sameOrNewer(receipt.released_at, run.rejectedAfterRevokeAt)
  ) return invalid(run, "release_invalid");
  return step(run, "cleanup", "complete", { releaseReceiptAt: receipt.released_at });
}

export function externalControllerAcceptancePassed(
  run: ExternalControllerAcceptanceRun,
): boolean {
  return run.phase === "complete"
    && run.invalidReason === null
    && run.completedSteps.length === 10;
}

export function externalControllerAcceptanceStepPassed(
  run: ExternalControllerAcceptanceRun,
  stepName: ExternalControllerAcceptanceStep,
): boolean {
  return run.completedSteps.includes(stepName);
}
