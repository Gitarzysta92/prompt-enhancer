import type { PromptEnhancerTransport } from "./contracts";
import { parseControlPlaneReadiness } from "./controlPlaneReadiness";
import {
  TEAM_CONTROL_PLANE_PORT_VERSION,
  TeamControlPlaneError,
  type TeamAggregateRequest,
  type TeamCapabilityReport,
  type TeamControlPlanePort,
  type TeamMemberVisibilityRequest,
} from "./teamControlPlaneSchema";

const LOCAL_RUNTIME_PRINCIPAL_ID = "90".repeat(32);

type ReadinessTransport = Pick<PromptEnhancerTransport, "getControlPlaneReadiness">;

function transportStatus(error: unknown): number | null {
  return typeof error === "object"
    && error !== null
    && "status" in error
    && typeof error.status === "number"
    && Number.isInteger(error.status)
    ? error.status
    : null;
}

/**
 * Honest adapter for runtimes without any team control plane. It never
 * fabricates a cohort: personal metrics stay in the local project workspace,
 * and team, organization, sync, and billing report themselves as absent.
 */
export function createUnavailableTeamControlPlanePort(
  now: () => string = () => new Date().toISOString(),
): TeamControlPlanePort {
  const capabilities = (): TeamCapabilityReport => ({
    port_version: TEAM_CONTROL_PLANE_PORT_VERSION,
    origin: "local_loopback",
    principal_id: LOCAL_RUNTIME_PRINCIPAL_ID,
    scopes: [
      { principal_id: LOCAL_RUNTIME_PRINCIPAL_ID, scope: "me", state: "allowed", reason: "personal_scope_served_locally", cohort_label: null, cohort_id: null, team_id: null, organization_id: null, aggregate_query_id: null },
      { principal_id: LOCAL_RUNTIME_PRINCIPAL_ID, scope: "team", state: "unavailable", reason: "local_runtime_has_no_team_service", cohort_label: null, cohort_id: null, team_id: null, organization_id: null, aggregate_query_id: null },
      { principal_id: LOCAL_RUNTIME_PRINCIPAL_ID, scope: "organization", state: "unavailable", reason: "local_runtime_has_no_team_service", cohort_label: null, cohort_id: null, team_id: null, organization_id: null, aggregate_query_id: null },
    ],
    member_visibility: {
      principal_id: LOCAL_RUNTIME_PRINCIPAL_ID,
      grant_id: null,
      scope: null,
      cohort_id: null,
      team_id: null,
      organization_id: null,
      state: "unavailable",
      reason: "unavailable_in_runtime",
      audit: { granted_by_role: null, granted_at: null, expires_at: null, access_logged: false, log_destination: null },
    },
    readiness: [
      { id: "local", state: "checking", reason: "loopback_service_checking", checked_at: null, action: { kind: "open_local_sources", enabled: true } },
      { id: "team_sync", state: "unavailable", reason: "no_team_sync_service_in_this_build", checked_at: now(), action: { kind: "none", enabled: false } },
      { id: "deep_analysis", state: "not_configured", reason: "deep_analysis_not_verified_by_this_view", checked_at: now(), action: { kind: "open_job_centre", enabled: true } },
      { id: "billing", state: "unavailable", reason: "no_billing_service_in_this_build", checked_at: now(), action: { kind: "none", enabled: false } },
    ],
    control_plane_readiness: null,
    checked_at: now(),
  });
  return {
    portVersion: TEAM_CONTROL_PLANE_PORT_VERSION,
    origin: "local_loopback",
    principalId: LOCAL_RUNTIME_PRINCIPAL_ID,
    async getCapabilities() {
      return capabilities();
    },
    async getAggregate(request: TeamAggregateRequest) {
      throw new TeamControlPlaneError(
        "scope_not_served_by_this_runtime",
        `No team control plane serves the ${request.scope} scope in this runtime.`,
      );
    },
    async getMemberVisibility(_request: TeamMemberVisibilityRequest) {
      throw new TeamControlPlaneError("member_visibility_unavailable", "Member visibility is unavailable in this runtime.");
    },
  };
}

/**
 * Readiness-aware local adapter. It can observe only the default-off
 * development boundary; no data credential or team/member read path exists.
 */
export function createLocalLoopbackTeamControlPlanePort(
  transport: ReadinessTransport,
  now: () => string = () => new Date().toISOString(),
): TeamControlPlanePort {
  const unavailable = createUnavailableTeamControlPlanePort(now);
  return {
    ...unavailable,
    async getCapabilities(signal?: AbortSignal) {
      const base = await unavailable.getCapabilities(signal);
      try {
        const backendReadiness = parseControlPlaneReadiness(
          await transport.getControlPlaneReadiness(signal),
        );
        signal?.throwIfAborted();
        return {
          ...base,
          scopes: base.scopes.map((access) => access.scope === "me" ? access : {
            ...access,
            reason: "development_control_plane_incomplete" as const,
          }),
          member_visibility: {
            ...base.member_visibility,
            reason: "development_control_plane_incomplete" as const,
          },
          readiness: base.readiness.map((card) => card.id === "team_sync" ? {
            ...card,
            reason: "development_control_plane_incomplete" as const,
          } : card),
          control_plane_readiness: backendReadiness,
        };
      } catch (error) {
        signal?.throwIfAborted();
        if (transportStatus(error) === 404 || error instanceof TypeError) return base;
        throw error;
      }
    },
  };
}
