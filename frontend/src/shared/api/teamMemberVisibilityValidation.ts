import {
  TEAM_REVIEWED_METRIC_CONTRACTS,
  teamControlPlaneResponseMatchesPort,
  type AnalyticsScope,
  type MemberVisibilityGrant,
  type ScopeAccess,
  type TeamControlPlanePort,
  type TeamMemberVisibilityPage,
  type TeamMemberVisibilityRequest,
} from "./teamControlPlaneSchema";
import {
  teamMemberVisibilityGrantIsValid,
} from "./teamControlPlaneValidation";
import {
  isTeamIdentity,
  memberAuditDestinationForOrigin,
  teamScopeIdentityBindingIsCoherent,
} from "./teamControlPlaneIdentity";

const REVIEWED_MEMBER_METRICS = new Map(TEAM_REVIEWED_METRIC_CONTRACTS.map((contract) => [contract.metric_key, contract]));

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function parseableInstant(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

export function teamMemberVisibilityRequestsEqual(left: unknown, right: TeamMemberVisibilityRequest): left is TeamMemberVisibilityRequest {
  return isRecord(left)
    && left.principal_id === right.principal_id
    && left.scope === right.scope
    && left.cohort_id === right.cohort_id
    && left.team_id === right.team_id
    && left.organization_id === right.organization_id
    && left.grant_id === right.grant_id;
}

export function teamMemberVisibilityRequestForAccess(
  scope: AnalyticsScope,
  access: ScopeAccess | null,
  grant: MemberVisibilityGrant,
): TeamMemberVisibilityRequest | null {
  if (
    scope === "me"
    || access === null
    || access.scope !== scope
    || access.state !== "allowed"
    || access.cohort_id === null
    || grant.grant_id === null
    || access.principal_id !== grant.principal_id
  ) return null;
  const request: TeamMemberVisibilityRequest = {
    principal_id: access.principal_id,
    scope,
    cohort_id: access.cohort_id,
    team_id: access.team_id,
    organization_id: access.organization_id,
    grant_id: grant.grant_id,
  };
  if (
    !isTeamIdentity(request.principal_id)
    || !isTeamIdentity(request.cohort_id)
    || !teamScopeIdentityBindingIsCoherent(request.scope, request.team_id, request.organization_id)
  ) {
    return null;
  }
  return request;
}

export function memberVisibilityGrantIsUsable(
  grant: MemberVisibilityGrant,
  request: TeamMemberVisibilityRequest | null,
  expectedPrincipalId: string,
  now = Date.now(),
): boolean {
  const expiry = grant.audit.expires_at === null ? Number.NaN : Date.parse(grant.audit.expires_at);
  const grantedAt = grant.audit.granted_at === null ? Number.NaN : Date.parse(grant.audit.granted_at);
  return request !== null
    && isTeamIdentity(expectedPrincipalId)
    && request.principal_id === expectedPrincipalId
    && teamMemberVisibilityGrantIsValid(grant)
    && grant.state === "allowed"
    && grant.reason === "granted_with_member_consent"
    && grant.grant_id !== null
    && isTeamIdentity(grant.grant_id)
    && grant.grant_id === request.grant_id
    && grant.principal_id === request.principal_id
    && isTeamIdentity(request.principal_id)
    && isTeamIdentity(request.grant_id)
    && grant.scope === request.scope
    && grant.cohort_id === request.cohort_id
    && isTeamIdentity(request.cohort_id)
    && grant.team_id === request.team_id
    && grant.organization_id === request.organization_id
    && typeof grant.audit.granted_by_role === "string"
    && grant.audit.granted_by_role.trim() !== ""
    && Number.isFinite(grantedAt)
    && grant.audit.access_logged === true
    && (grant.audit.log_destination === "local_audit_log" || grant.audit.log_destination === "team_control_plane")
    && Number.isFinite(expiry)
    && grantedAt < expiry
    && grantedAt <= now
    && expiry > now;
}

export function memberVisibilityGrantsEqual(left: unknown, right: MemberVisibilityGrant): left is MemberVisibilityGrant {
  return isRecord(left)
    && isRecord(left.audit)
    && left.principal_id === right.principal_id
    && left.grant_id === right.grant_id
    && left.scope === right.scope
    && left.cohort_id === right.cohort_id
    && left.team_id === right.team_id
    && left.organization_id === right.organization_id
    && left.state === right.state
    && left.reason === right.reason
    && left.audit.granted_by_role === right.audit.granted_by_role
    && left.audit.granted_at === right.audit.granted_at
    && left.audit.expires_at === right.audit.expires_at
    && left.audit.access_logged === right.audit.access_logged
    && left.audit.log_destination === right.audit.log_destination;
}

export function snapshotMemberVisibilityGrant(grant: MemberVisibilityGrant): MemberVisibilityGrant {
  return { ...grant, audit: { ...grant.audit } };
}

export function snapshotTeamMemberVisibilityRequest(request: TeamMemberVisibilityRequest): TeamMemberVisibilityRequest {
  return { ...request };
}

export function memberVisibilityGrantIdentity(grant: MemberVisibilityGrant): string {
  // JSON string escaping makes this canonical field tuple injective even when
  // arbitrary string fields themselves contain delimiters such as "|".
  return JSON.stringify({
    principal_id: grant.principal_id,
    grant_id: grant.grant_id,
    scope: grant.scope,
    cohort_id: grant.cohort_id,
    team_id: grant.team_id,
    organization_id: grant.organization_id,
    state: grant.state,
    reason: grant.reason,
    audit: {
      granted_by_role: grant.audit.granted_by_role,
      granted_at: grant.audit.granted_at,
      expires_at: grant.audit.expires_at,
      access_logged: grant.audit.access_logged,
      log_destination: grant.audit.log_destination,
    },
  });
}

function memberMetricIsValid(value: unknown): boolean {
  if (!isRecord(value) || typeof value.metric_key !== "string") return false;
  const contract = REVIEWED_MEMBER_METRICS.get(value.metric_key);
  if (
    contract === undefined
    || value.definition_version !== contract.definition_version
    || value.provenance !== "measured_typed"
    || (value.value_state !== "known"
      && value.value_state !== "unknown"
      && value.value_state !== "not_applicable"
      && value.value_state !== "abstained")
    || (value.newest_receipt_at !== null && !parseableInstant(value.newest_receipt_at))
  ) return false;
  if (value.value_state === "known") {
    return nonNegativeInteger(value.numerator)
      && nonNegativeInteger(value.denominator)
      && value.denominator > 0
      && value.numerator <= value.denominator
      && typeof value.numeric_value === "number"
      && Number.isFinite(value.numeric_value)
      && value.numeric_value >= 0
      && value.numeric_value <= 1
      && Math.abs(value.numeric_value - value.numerator / value.denominator) <= 1e-9;
  }
  return value.numerator === null
    && value.denominator === null
    && value.numeric_value === null
    && value.newest_receipt_at === null;
}

function memberRowsAreValid(members: unknown): boolean {
  if (!Array.isArray(members)) return false;
  const ids = new Set<string>();
  const handles = new Set<string>();
  let previousId: string | null = null;
  for (const member of members) {
    if (
      !isRecord(member)
      ||
      typeof member.member_id !== "string"
      || !isTeamIdentity(member.member_id)
      || ids.has(member.member_id)
      || typeof member.display_handle !== "string"
      || member.display_handle.trim() === ""
      || handles.has(member.display_handle)
      || member.consent !== "granted"
      || (previousId !== null && previousId >= member.member_id)
      || !Array.isArray(member.metrics)
      || member.metrics.length !== TEAM_REVIEWED_METRIC_CONTRACTS.length
      || !member.metrics.every(memberMetricIsValid)
    ) return false;
    const metricKeys = member.metrics.map((metric) => (metric as Record<string, unknown>).metric_key);
    if (new Set(metricKeys).size !== TEAM_REVIEWED_METRIC_CONTRACTS.length
      || !TEAM_REVIEWED_METRIC_CONTRACTS.every((contract) => metricKeys.includes(contract.metric_key))) return false;
    ids.add(member.member_id);
    handles.add(member.display_handle);
    previousId = member.member_id;
  }
  return true;
}

/** Full fail-closed runtime validator for the member page. It validates the
 * exact request/grant plus every row and metric before React can retain or
 * render the payload. */
export function memberVisibilityPageIsValid(
  page: unknown,
  requestedGrant: MemberVisibilityGrant,
  requested: TeamMemberVisibilityRequest,
  port: TeamControlPlanePort,
): page is TeamMemberVisibilityPage {
  return isRecord(page)
    && teamControlPlaneResponseMatchesPort(page, port)
    && teamMemberVisibilityRequestsEqual(page.request, requested)
    && memberVisibilityGrantsEqual(page.grant, requestedGrant)
    && memberVisibilityGrantIsUsable(page.grant, requested, port.principalId)
    && page.ordering === "stable_member_id"
    && nonNegativeInteger(page.withheld_member_count)
    && memberRowsAreValid(page.members)
    && page.grant.audit.log_destination === memberAuditDestinationForOrigin(port.origin);
}
