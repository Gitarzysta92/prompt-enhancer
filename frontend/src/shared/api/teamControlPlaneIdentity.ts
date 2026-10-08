import type { AnalyticsScope, TeamDataOrigin } from "./teamControlPlaneSchema";

const TEAM_IDENTITY = /^[0-9a-f]{64}$/;

/** Opaque team identities are fixed-width lowercase hex, never account data. */
export function isTeamIdentity(value: unknown): value is string {
  return typeof value === "string" && TEAM_IDENTITY.test(value);
}

export function isNullableTeamIdentity(value: unknown): value is string | null {
  return value === null || isTeamIdentity(value);
}

/**
 * Exact scope-to-identity binding shared by capabilities, grants, aggregate
 * requests, and member requests. Team rows may retain their organization
 * parent, while organization rows may retain their team parent.
 */
export function teamScopeIdentityBindingIsCoherent(
  scope: AnalyticsScope,
  teamId: unknown,
  organizationId: unknown,
): boolean {
  if (!isNullableTeamIdentity(teamId) || !isNullableTeamIdentity(organizationId)) return false;
  if (scope === "me") return teamId === null && organizationId === null;
  if (scope === "team") return teamId !== null;
  return organizationId !== null;
}

export function memberAuditDestinationForOrigin(
  origin: TeamDataOrigin,
): "local_audit_log" | "team_control_plane" {
  return origin === "team_control_plane" ? "team_control_plane" : "local_audit_log";
}
