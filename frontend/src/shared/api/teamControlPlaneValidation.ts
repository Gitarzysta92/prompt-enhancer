import {
  ANALYTICS_SCOPES,
  TEAM_REVIEWED_METRIC_CONTRACTS,
  teamControlPlaneResponseMatchesPort,
  type AnalyticsScope,
  type MemberVisibilityGrant,
  type MetricDirection,
  type ReadinessActionKind,
  type ReadinessCard,
  type ReadinessCardId,
  type ReadinessReason,
  type ReadinessState,
  type ScopeAccess,
  type ScopeAccessReason,
  type ScopeAccessState,
  type TeamAggregateRequest,
  type TeamAggregateSnapshot,
  type TeamAggregateWindow,
  type TeamCapabilityReport,
  type TeamControlPlanePort,
  type TeamMetricAggregate,
} from "./teamControlPlaneSchema";
import {
  isTeamIdentity,
  memberAuditDestinationForOrigin,
  teamScopeIdentityBindingIsCoherent,
} from "./teamControlPlaneIdentity";
import { controlPlaneReadinessIsValid } from "./controlPlaneReadiness";

const METRIC_KEY = /^[a-z][a-z0-9_.-]*$/;

const REVIEWED_METRIC_BY_KEY = new Map(
  TEAM_REVIEWED_METRIC_CONTRACTS.map((contract) => [contract.metric_key, contract]),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function nullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || nonNegativeInteger(value);
}

function boundedNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function parseableInstant(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function scopeReasonMatches(scope: AnalyticsScope, state: ScopeAccessState, reason: ScopeAccessReason): boolean {
  switch (reason) {
    case "granted": return state === "allowed";
    case "personal_scope_served_locally": return scope === "me" && state === "allowed";
    case "local_runtime_has_no_team_service": return scope !== "me" && state === "unavailable";
    case "development_control_plane_incomplete": return scope !== "me" && state === "unavailable";
    case "team_sync_not_configured": return scope !== "me" && state === "unavailable";
    case "role_insufficient": return scope !== "me" && state === "denied";
    case "organization_policy_disabled": return scope === "organization" && (state === "denied" || state === "unavailable");
    case "consent_required": return scope !== "me" && state === "denied";
    default: return false;
  }
}

function scopeAccessIsValid(value: unknown): value is ScopeAccess {
  if (!isRecord(value)) return false;
  const scope = value.scope;
  const state = value.state;
  const reason = value.reason;
  if (
    !isTeamIdentity(value.principal_id)
    ||
    (scope !== "me" && scope !== "team" && scope !== "organization")
    || (state !== "allowed" && state !== "denied" && state !== "unavailable")
    || (reason !== "granted"
      && reason !== "personal_scope_served_locally"
      && reason !== "local_runtime_has_no_team_service"
      && reason !== "development_control_plane_incomplete"
      && reason !== "team_sync_not_configured"
      && reason !== "role_insufficient"
      && reason !== "organization_policy_disabled"
      && reason !== "consent_required")
    || !scopeReasonMatches(scope, state, reason)
  ) return false;
  if (state !== "allowed") {
    return value.cohort_label === null
      && value.cohort_id === null
      && value.team_id === null
      && value.organization_id === null
      && value.aggregate_query_id === null;
  }
  if (reason === "personal_scope_served_locally") {
    return value.cohort_label === null
      && value.cohort_id === null
      && value.team_id === null
      && value.organization_id === null
      && value.aggregate_query_id === null;
  }
  if (
    !nonEmptyString(value.cohort_label)
    || !isTeamIdentity(value.cohort_id)
    || !isTeamIdentity(value.aggregate_query_id)
    || !teamScopeIdentityBindingIsCoherent(scope, value.team_id, value.organization_id)
  ) return false;
  return true;
}

/** Complete structural grant validator. Authorization still requires an exact
 * active request and an unexpired grant at the moment of reveal. */
export function teamMemberVisibilityGrantIsValid(value: unknown): value is MemberVisibilityGrant {
  if (!isRecord(value) || !isRecord(value.audit)) return false;
  const audit = value.audit;
  if (!isTeamIdentity(value.principal_id)) return false;
  if (value.state === "allowed") {
    if (
      value.reason !== "granted_with_member_consent"
      || (value.scope !== "team" && value.scope !== "organization")
      || !isTeamIdentity(value.grant_id)
      || !isTeamIdentity(value.cohort_id)
      || !teamScopeIdentityBindingIsCoherent(value.scope, value.team_id, value.organization_id)
      || !nonEmptyString(audit.granted_by_role)
      || !parseableInstant(audit.granted_at)
      || !parseableInstant(audit.expires_at)
      || Date.parse(audit.granted_at) >= Date.parse(audit.expires_at)
      || audit.access_logged !== true
      || (audit.log_destination !== "local_audit_log" && audit.log_destination !== "team_control_plane")
    ) return false;
    return true;
  }
  if (value.state !== "denied" && value.state !== "unavailable") return false;
  const reasonMatches = value.state === "denied"
    ? value.reason === "permission_not_granted"
      || value.reason === "member_consent_missing"
      || value.reason === "cohort_below_minimum"
    : value.reason === "unavailable_in_runtime"
      || value.reason === "development_control_plane_incomplete";
  return reasonMatches
    && value.grant_id === null
    && value.scope === null
    && value.cohort_id === null
    && value.team_id === null
    && value.organization_id === null
    && audit.granted_by_role === null
    && audit.granted_at === null
    && audit.expires_at === null
    && audit.access_logged === false
    && audit.log_destination === null;
}

const READINESS_REASON_CONTRACT: Readonly<Record<ReadinessReason, {
  id: ReadinessCardId;
  state: ReadinessState;
  action: ReadinessActionKind;
  enabled: boolean;
  checked: "required" | "absent";
}>> = {
  synthetic_fixture: { id: "local", state: "ready", action: "none", enabled: false, checked: "required" },
  loopback_service_checking: { id: "local", state: "checking", action: "open_local_sources", enabled: true, checked: "absent" },
  loopback_service_available: { id: "local", state: "ready", action: "open_local_sources", enabled: true, checked: "required" },
  loopback_service_unavailable: { id: "local", state: "unavailable", action: "open_local_sources", enabled: true, checked: "required" },
  no_team_sync_service_in_this_build: { id: "team_sync", state: "unavailable", action: "none", enabled: false, checked: "required" },
  development_control_plane_incomplete: { id: "team_sync", state: "unavailable", action: "none", enabled: false, checked: "required" },
  team_sync_not_configured: { id: "team_sync", state: "not_configured", action: "none", enabled: false, checked: "required" },
  deep_analysis_not_in_synthetic_preview: { id: "deep_analysis", state: "unavailable", action: "open_methods_and_models", enabled: true, checked: "required" },
  deep_analysis_not_verified_by_this_view: { id: "deep_analysis", state: "not_configured", action: "open_job_centre", enabled: true, checked: "required" },
  no_billing_service_in_this_build: { id: "billing", state: "unavailable", action: "none", enabled: false, checked: "required" },
};

function readinessCardIsValid(value: unknown): value is ReadinessCard {
  if (!isRecord(value) || !isRecord(value.action) || typeof value.reason !== "string") return false;
  const contract = READINESS_REASON_CONTRACT[value.reason as ReadinessReason];
  if (contract === undefined) return false;
  return value.id === contract.id
    && value.state === contract.state
    && value.action.kind === contract.action
    && value.action.enabled === contract.enabled
    && (contract.checked === "required" ? parseableInstant(value.checked_at) : value.checked_at === null);
}

/** Fail-closed capability validator used before scope, grant, or readiness data
 * can enter component state. */
export function teamCapabilityReportIsValid(
  value: unknown,
  port: Pick<TeamControlPlanePort, "origin" | "portVersion" | "principalId">,
): value is TeamCapabilityReport {
  if (
    !isRecord(value)
    || !teamControlPlaneResponseMatchesPort(value, port)
    || !isTeamIdentity(value.principal_id)
    || !parseableInstant(value.checked_at)
    || !Array.isArray(value.scopes)
    || value.scopes.length !== ANALYTICS_SCOPES.length
    || !value.scopes.every(scopeAccessIsValid)
    || !teamMemberVisibilityGrantIsValid(value.member_visibility)
    || !Array.isArray(value.readiness)
    || value.readiness.length !== 4
    || !value.readiness.every(readinessCardIsValid)
    || !(value.control_plane_readiness === null
      || controlPlaneReadinessIsValid(value.control_plane_readiness))
  ) return false;
  const scopeNames = value.scopes.map((access) => access.scope);
  if (new Set(scopeNames).size !== ANALYTICS_SCOPES.length
    || !ANALYTICS_SCOPES.every((scope) => scopeNames.includes(scope))) return false;
  const readinessIds = value.readiness.map((card) => card.id);
  if (new Set(readinessIds).size !== 4
    || !(["local", "team_sync", "deep_analysis", "billing"] as const).every((id) => readinessIds.includes(id))) return false;
  const queryBearingScopes = value.scopes.filter((access) => access.state === "allowed" && access.cohort_id !== null);
  const cohortIds = queryBearingScopes.map((access) => access.cohort_id as string);
  const queryIds = queryBearingScopes.map((access) => access.aggregate_query_id as string);
  if (new Set(cohortIds).size !== cohortIds.length || new Set(queryIds).size !== queryIds.length) return false;
  const grant = value.member_visibility;
  if (!value.scopes.every((access) => access.principal_id === value.principal_id)
    || grant.principal_id !== value.principal_id) return false;
  const backendReadiness = value.control_plane_readiness;
  if (backendReadiness !== null) {
    if (value.origin !== "local_loopback") return false;
    if (!value.scopes
      .filter((access) => access.scope !== "me")
      .every((access) => access.state === "unavailable"
        && access.reason === "development_control_plane_incomplete")) return false;
    if (grant.state !== "unavailable"
      || grant.reason !== "development_control_plane_incomplete") return false;
  } else if (
    value.scopes.some((access) => access.reason === "development_control_plane_incomplete")
    || grant.reason === "development_control_plane_incomplete"
  ) return false;
  if (grant.state !== "allowed") return true;
  const expectedAuditDestination = memberAuditDestinationForOrigin(port.origin);
  if (grant.audit.log_destination !== expectedAuditDestination) return false;
  const access = value.scopes.find((candidate) => candidate.scope === grant.scope);
  return access?.state === "allowed"
    && access.principal_id === grant.principal_id
    && access.cohort_id === grant.cohort_id
    && access.team_id === grant.team_id
    && access.organization_id === grant.organization_id;
}

export function teamAggregateRequestsEqual(
  left: unknown,
  right: TeamAggregateRequest,
): left is TeamAggregateRequest {
  return isRecord(left)
    && left.principal_id === right.principal_id
    && left.scope === right.scope
    && left.cohort_id === right.cohort_id
    && left.team_id === right.team_id
    && left.organization_id === right.organization_id
    && left.query_id === right.query_id;
}

function validAggregateRequest(request: TeamAggregateRequest): boolean {
  if (
    !isTeamIdentity(request.principal_id)
    || !ANALYTICS_SCOPES.includes(request.scope)
    || !isTeamIdentity(request.cohort_id)
    || !isTeamIdentity(request.query_id)
    || !teamScopeIdentityBindingIsCoherent(request.scope, request.team_id, request.organization_id)
  ) return false;
  return true;
}

/** Build the only aggregate request authorized by a capability row. */
export function teamAggregateRequestForAccess(access: ScopeAccess): TeamAggregateRequest | null {
  if (
    access.state !== "allowed"
    || !isTeamIdentity(access.principal_id)
    || access.cohort_id === null
    || access.aggregate_query_id === null
    || !isTeamIdentity(access.cohort_id)
    || !isTeamIdentity(access.aggregate_query_id)
    || !teamScopeIdentityBindingIsCoherent(access.scope, access.team_id, access.organization_id)
  ) return null;
  return {
    principal_id: access.principal_id,
    scope: access.scope,
    cohort_id: access.cohort_id,
    team_id: access.team_id,
    organization_id: access.organization_id,
    query_id: access.aggregate_query_id,
  };
}

function validMetricAggregate(value: unknown): value is TeamMetricAggregate {
  if (!isRecord(value)) return false;
  const provenance = value.provenance;
  const state = value.value_state;
  const reviewed = typeof value.metric_key === "string" ? REVIEWED_METRIC_BY_KEY.get(value.metric_key) : undefined;
  const suppressed = state === "suppressed_small_cohort" || state === "suppressed_privacy_policy";
  const validState = state === "known"
    || suppressed
    || state === "withheld_not_comparable"
    || state === "unknown"
    || state === "not_applicable"
    || state === "abstained"
    || state === "unavailable";
  if (
    typeof value.metric_key !== "string" || !METRIC_KEY.test(value.metric_key)
    || reviewed === undefined
    || !nonNegativeInteger(value.definition_version) || value.definition_version < 1
    || value.definition_version !== reviewed.definition_version
    || (value.direction !== "higher_is_better" && value.direction !== "lower_is_better")
    || value.direction !== reviewed.direction
    || (provenance !== "measured_typed" && provenance !== "experimental_model")
    || !validState
  ) return false;

  if (suppressed) {
    if (
      (state === "suppressed_small_cohort" && value.suppression_reason !== "small_cohort")
      || (state === "suppressed_privacy_policy"
        && value.suppression_reason !== "overlap_or_differencing"
        && value.suppression_reason !== "query_identity_mismatch")
    ) return false;
  } else if (value.suppression_reason !== null) return false;

  const numerator = value.numerator;
  const denominator = value.denominator;
  const numeric = value.numeric_value;
  if (state === "known") {
    if (!boundedNumber(numeric)) return false;
    if (provenance === "measured_typed") {
      if (
        typeof numerator !== "number" || !nonNegativeInteger(numerator)
        || typeof denominator !== "number" || !nonNegativeInteger(denominator) || denominator <= 0
        || numerator > denominator
        || Math.abs(numeric - numerator / denominator) > 1e-9
      ) return false;
    } else if (!(
      (numerator === null && denominator === null)
      || (typeof numerator === "number" && nonNegativeInteger(numerator)
        && typeof denominator === "number" && nonNegativeInteger(denominator)
        && denominator > 0 && numerator <= denominator
        && Math.abs(numeric - numerator / denominator) <= 1e-9)
    )) return false;
  } else if (numerator !== null || denominator !== null || numeric !== null) return false;

  const cohort = value.cohort;
  const missingness = value.missingness;
  if (
    !isRecord(cohort)
    || !nullableNonNegativeInteger(cohort.member_count)
    || !nullableNonNegativeInteger(cohort.session_count)
    || !nonNegativeInteger(cohort.minimum_member_count) || cohort.minimum_member_count < 1
    || !nonNegativeInteger(cohort.minimum_contributor_count) || cohort.minimum_contributor_count < 1
    || !isRecord(missingness)
    || !nullableNonNegativeInteger(missingness.members_with_value)
    || !nullableNonNegativeInteger(missingness.members_in_cohort)
    || !nullableNonNegativeInteger(missingness.sessions_without_receipt)
  ) return false;
  if (
    missingness.members_with_value !== null
    && (cohort.member_count === null
      || missingness.members_with_value > cohort.member_count
      || missingness.members_with_value < cohort.minimum_contributor_count)
  ) return false;
  if (missingness.members_in_cohort !== cohort.member_count) return false;
  if (
    missingness.sessions_without_receipt !== null
    && (cohort.session_count === null || missingness.sessions_without_receipt > cohort.session_count)
  ) return false;
  if (state === "known" && missingness.members_with_value === null) return false;
  if (state === "known" && cohort.member_count !== null && cohort.member_count < cohort.minimum_member_count) return false;
  if (suppressed && (missingness.members_with_value !== null || missingness.sessions_without_receipt !== null)) return false;

  const comparability = value.comparability;
  if (!isRecord(comparability) || !Array.isArray(comparability.definition_versions)) return false;
  if (
    comparability.state !== "comparable"
    && comparability.state !== "mixed_definition_versions"
    && comparability.state !== "mixed_windows"
    && comparability.state !== "not_comparable"
  ) return false;
  const versions = comparability.definition_versions;
  if (
    versions.length === 0
    || versions.some((version) => !nonNegativeInteger(version) || version < 1)
    || new Set(versions).size !== versions.length
    || !versions.includes(value.definition_version)
    || (comparability.state === "comparable" && (versions.length !== 1 || versions[0] !== value.definition_version))
    || (comparability.state === "mixed_definition_versions" && versions.length < 2)
    || ((state === "withheld_not_comparable") !== (comparability.state !== "comparable"))
  ) return false;

  const freshness = value.freshness;
  if (
    !isRecord(freshness)
    || (freshness.newest_receipt_at !== null && !parseableInstant(freshness.newest_receipt_at))
    || (freshness.oldest_receipt_at !== null && !parseableInstant(freshness.oldest_receipt_at))
    || !nullableNonNegativeInteger(freshness.stale_member_count)
    || !nonNegativeInteger(freshness.stale_after_days) || freshness.stale_after_days < 1
  ) return false;
  if (
    freshness.newest_receipt_at !== null
    && freshness.oldest_receipt_at !== null
    && Date.parse(freshness.oldest_receipt_at) > Date.parse(freshness.newest_receipt_at)
  ) return false;
  if (
    freshness.stale_member_count !== null
    && (cohort.member_count === null
      || freshness.stale_member_count > cohort.member_count
      || (missingness.members_with_value !== null && freshness.stale_member_count > missingness.members_with_value))
  ) return false;
  if ((freshness.newest_receipt_at === null) !== (freshness.oldest_receipt_at === null)) return false;
  if (suppressed && (
    freshness.newest_receipt_at !== null
    || freshness.oldest_receipt_at !== null
    || freshness.stale_member_count !== null
  )) return false;

  const uncertainty = value.uncertainty;
  if (!isRecord(uncertainty)) return false;
  if (uncertainty.kind === "not_estimated") {
    if (uncertainty.method !== null || uncertainty.low !== null || uncertainty.high !== null) return false;
  } else if (uncertainty.kind === "interval") {
    if (
      (uncertainty.method !== "wilson_95" && uncertainty.method !== "model_range_90")
      || !boundedNumber(uncertainty.low)
      || !boundedNumber(uncertainty.high)
      || uncertainty.low > uncertainty.high
      || !boundedNumber(numeric)
      || numeric < uncertainty.low
      || numeric > uncertainty.high
      || (provenance === "measured_typed" && uncertainty.method !== "wilson_95")
      || (provenance === "experimental_model" && uncertainty.method !== "model_range_90")
      || state !== "known"
    ) return false;
  } else return false;
  return true;
}

/**
 * Strict fail-closed aggregate response validator. It checks the immutable
 * query identity plus publication-shape, count, fraction, interval,
 * suppression, and comparability invariants before any value can render.
 */
export function teamAggregateSnapshotIsValid(
  value: unknown,
  request: TeamAggregateRequest,
  port: Pick<TeamControlPlanePort, "origin" | "portVersion" | "principalId">,
): value is TeamAggregateSnapshot {
  if (
    !isRecord(value)
    || !validAggregateRequest(request)
    || request.principal_id !== port.principalId
    || !teamControlPlaneResponseMatchesPort(value, port)
    || !teamAggregateRequestsEqual(value.request, request)
    || value.scope !== request.scope
    || typeof value.cohort_label !== "string" || value.cohort_label.trim() === ""
    || value.publication_policy !== "aggregate_only_no_ranking_no_universal_score"
    || value.calibration !== "uncalibrated_exact_fractions"
    || !parseableInstant(value.generated_at)
    || !isRecord(value.window)
    || typeof value.window.label !== "string" || value.window.label.trim() === ""
    || !parseableInstant(value.window.started_at)
    || !parseableInstant(value.window.ended_at)
    || Date.parse(value.window.started_at) > Date.parse(value.window.ended_at)
    || Date.parse(value.generated_at) < Date.parse(value.window.ended_at)
    || !Array.isArray(value.metrics) || value.metrics.length === 0
    || !value.metrics.every(validMetricAggregate)
  ) return false;
  const validatedWindow = value.window as unknown as TeamAggregateWindow;
  const windowStart = Date.parse(validatedWindow.started_at);
  const windowEnd = Date.parse(validatedWindow.ended_at);
  const identities = value.metrics.map((metric) => JSON.stringify([metric.metric_key, metric.provenance]));
  if (new Set(identities).size !== identities.length) return false;
  const first = value.metrics[0].cohort;
  if (!value.metrics.every((metric) =>
    metric.cohort.member_count === first.member_count
    && metric.cohort.session_count === first.session_count
    && metric.cohort.minimum_member_count === first.minimum_member_count
    && metric.cohort.minimum_contributor_count === first.minimum_contributor_count
    && (metric.freshness.oldest_receipt_at === null
      || (Date.parse(metric.freshness.oldest_receipt_at) >= windowStart
        && Date.parse(metric.freshness.oldest_receipt_at) <= windowEnd))
    && (metric.freshness.newest_receipt_at === null
      || (Date.parse(metric.freshness.newest_receipt_at) >= windowStart
        && Date.parse(metric.freshness.newest_receipt_at) <= windowEnd)))) return false;
  const metricDefinitions = new Map<string, { definitionVersion: number; direction: MetricDirection; measured: boolean }>();
  for (const metric of value.metrics) {
    const existing = metricDefinitions.get(metric.metric_key);
    if (existing === undefined) {
      metricDefinitions.set(metric.metric_key, {
        definitionVersion: metric.definition_version,
        direction: metric.direction,
        measured: metric.provenance === "measured_typed",
      });
      continue;
    }
    if (existing.definitionVersion !== metric.definition_version || existing.direction !== metric.direction) return false;
    if (metric.provenance === "measured_typed") existing.measured = true;
  }
  const measuredByKey = new Map(
    value.metrics
      .filter((metric) => metric.provenance === "measured_typed")
      .map((metric) => [metric.metric_key, metric]),
  );
  return value.metrics.every((metric) => {
    if (metric.provenance !== "experimental_model") return true;
    const measured = measuredByKey.get(metric.metric_key);
    if (measured === undefined || metricDefinitions.get(metric.metric_key)?.measured !== true) return false;
    if (measured.value_state === "suppressed_small_cohort" || measured.value_state === "suppressed_privacy_policy") {
      return metric.value_state === measured.value_state
        && metric.suppression_reason === measured.suppression_reason;
    }
    if (measured.value_state === "withheld_not_comparable") {
      return metric.value_state === "withheld_not_comparable"
        && metric.comparability.state === measured.comparability.state
        && JSON.stringify(metric.comparability.definition_versions) === JSON.stringify(measured.comparability.definition_versions);
    }
    return true;
  });
}
