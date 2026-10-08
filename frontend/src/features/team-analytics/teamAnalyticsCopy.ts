import type {
  AnalyticsScope,
  MemberVisibilityGrant,
  MemberVisibilityReason,
  ReadinessActionKind,
  ReadinessCard,
  ReadinessCardId,
  ReadinessReason,
  ReadinessState,
  ScopeAccess,
  ScopeAccessReason,
  TeamDataOrigin,
} from "../../shared/api/teamControlPlane";
import type { ControlPlaneReadinessGap } from "../../shared/api/contracts";
import type { RuntimeDataMode, RuntimeServiceState } from "../../shared/platform/runtimeMode";

/**
 * One UI copy catalog for every reason code the team control-plane port can
 * emit. Copy is exhaustive over the port's unions so a new reason code fails
 * type-checking here instead of rendering an empty explanation. Every sentence
 * describes what is true in the current runtime; none promises a service.
 */
export const SCOPE_LABELS: Readonly<Record<AnalyticsScope, string>> = {
  me: "Me",
  team: "Team",
  organization: "Organization",
};

export const SCOPE_DESCRIPTIONS: Readonly<Record<AnalyticsScope, string>> = {
  me: "Your own sessions on this installation.",
  team: "Aggregate over a consented team cohort. Aggregates only; no member ranking.",
  organization: "Aggregate over several teams. Aggregates only; no team or member ranking.",
};

export const SCOPE_REASON_COPY: Readonly<Record<ScopeAccessReason, string>> = {
  granted: "Allowed in this runtime.",
  personal_scope_served_locally: "Your personal analytics are served locally by the project workspace; this page shows readiness only.",
  local_runtime_has_no_team_service: "This runtime has no team control plane, so no cohort exists and nothing is synced.",
  development_control_plane_incomplete: "The default-off development boundary answered, but its reported gaps keep every cohort and member value closed.",
  team_sync_not_configured: "A team control plane exists but is not configured for this installation.",
  role_insufficient: "The current role (fixture) does not permit this scope.",
  organization_policy_disabled: "Organization analytics are disabled by policy (fixture).",
  consent_required: "This scope needs your explicit consent before any aggregate is shown.",
};

export function scopeAccessCopy(access: ScopeAccess): string {
  const state = access.state === "allowed" ? "Allowed" : access.state === "denied" ? "Not permitted" : "Unavailable";
  return `${state} · ${SCOPE_REASON_COPY[access.reason]}`;
}

export const MEMBER_VISIBILITY_REASON_COPY: Readonly<Record<MemberVisibilityReason, string>> = {
  granted_with_member_consent: "An explicit grant and member consent allow this view; every member listed consented individually.",
  permission_not_granted: "No permission grants individual member visibility. Aggregates only.",
  member_consent_missing: "Members have not consented to individual visibility. Aggregates only.",
  cohort_below_minimum: "The cohort is below the minimum size for individual visibility.",
  development_control_plane_incomplete: "The development boundary answered, but it has no approved member-publication path. Aggregates and member rows stay closed.",
  unavailable_in_runtime: "No team control plane exists in this runtime, so there are no members to show.",
};

export function memberVisibilityAuditCopy(grant: MemberVisibilityGrant): string {
  if (grant.state !== "allowed") return MEMBER_VISIBILITY_REASON_COPY[grant.reason];
  const audit = grant.audit;
  const issued = audit.granted_by_role === null ? "an unrecorded role" : audit.granted_by_role;
  const logging = audit.access_logged
    ? `Opening this view is written to the ${audit.log_destination === "team_control_plane" ? "team control plane audit log" : "local audit log"}.`
    : "Opening this view is not written to an audit log.";
  const expiry = audit.expires_at === null ? "The grant has no recorded expiry." : `The grant expires ${shortUtcDate(audit.expires_at)}.`;
  return `${MEMBER_VISIBILITY_REASON_COPY[grant.reason]} Granted by ${issued}${audit.granted_at === null ? "" : ` on ${shortUtcDate(audit.granted_at)}`}. ${expiry} ${logging}`;
}

export const READINESS_TITLES: Readonly<Record<ReadinessCardId, string>> = {
  local: "Local analysis",
  team_sync: "Team sync",
  deep_analysis: "Deep analysis",
  billing: "Billing & plan",
};

export const READINESS_STATE_LABELS: Readonly<Record<ReadinessState, string>> = {
  ready: "Ready",
  partial: "Partial",
  checking: "Checking",
  not_configured: "Not configured",
  unavailable: "Unavailable",
};

export const READINESS_REASON_COPY: Readonly<Record<ReadinessReason, string>> = {
  synthetic_fixture: "Fictional in-memory fixtures are loaded. No local source, provider history, or account is read in this preview.",
  loopback_service_checking: "The loopback service health check has not answered yet.",
  loopback_service_available: "The loopback service answered its health check. Source consent and indexing stay separate explicit actions in Data sources.",
  loopback_service_unavailable: "The loopback service did not answer. Personal analytics stay local and nothing is sent anywhere.",
  no_team_sync_service_in_this_build: "No team sync service exists in this build. Nothing is uploaded, no cohort is joined, and no account is signed in.",
  development_control_plane_incomplete: "The default-off loopback development boundary answered, but it reports blocking identity, producer, disclosure, durability, and governance gaps. No team value is published.",
  team_sync_not_configured: "A team control plane exists but is not configured for this installation.",
  deep_analysis_not_in_synthetic_preview: "Local model lanes are not part of the synthetic preview; the deep-analysis pipeline runs only in the local loopback build.",
  deep_analysis_not_verified_by_this_view: "Local model lanes are configured in Methods & models and observed in Analysis jobs; this view does not verify installed models or hardware.",
  no_billing_service_in_this_build: "No billing, plan, or entitlement service exists in this build. Nothing is metered or charged.",
};

export const READINESS_ACTION_LABELS: Readonly<Record<ReadinessActionKind, string | null>> = {
  none: null,
  open_local_sources: "Open Data sources",
  open_job_centre: "Open Analysis jobs",
  open_methods_and_models: "Open Methods & models",
};

export const ORIGIN_LABELS: Readonly<Record<TeamDataOrigin, string>> = {
  synthetic_fixture: "Synthetic fixture · fictional cohort",
  local_loopback: "Local loopback runtime",
  team_control_plane: "Team control plane",
};

/** Exhaustive, user-facing copy for the exact backend gap vocabulary. */
export const CONTROL_PLANE_GAP_COPY: Readonly<Record<ControlPlaneReadinessGap, string>> = {
  production_identity_provider_missing: "No production identity provider binds real accounts to tenant roles.",
  production_signature_algorithm_missing: "The development signature algorithm is not approved for production devices.",
  production_database_adapter_missing: "No durable multi-tenant database adapter with enforced row isolation exists.",
  credential_lifecycle_incomplete: "Credential issuance, rotation, expiry, and recovery are incomplete.",
  out_of_band_provisioning_only: "Organizations, seats, and grants can only be provisioned inside the development process.",
  remote_transport_not_implemented: "No off-machine transport is implemented; the service remains loopback-only.",
  billing_not_implemented: "Billing and entitlement verification are not implemented.",
  producer_pipeline_not_connected: "Local metric receipts are not connected to the signed snapshot producer.",
  disclosure_control_unreviewed: "Stable cohorts, overlap controls, and an atomic query budget are not approved.",
  durable_recipient_delivery_not_implemented: "Recipient delivery and acknowledgements are not durable across process restarts.",
  backup_and_replica_erasure_not_implemented: "Deletion is not yet proven across backups and replicas.",
  governance_review_pending: "Real-person team sharing still requires governance and owner approval.",
};

/** The local card is derived from the runtime the shell actually observed, never from a fixture claim. */
export function localReadinessCard(
  runtimeMode: RuntimeDataMode,
  serviceState: RuntimeServiceState,
  checkedAt: string | null,
): ReadinessCard {
  if (runtimeMode === "synthetic_demo") {
    return { id: "local", state: "ready", reason: "synthetic_fixture", checked_at: checkedAt, action: { kind: "none", enabled: false } };
  }
  if (serviceState === "checking") {
    return { id: "local", state: "checking", reason: "loopback_service_checking", checked_at: null, action: { kind: "open_local_sources", enabled: false } };
  }
  if (serviceState === "available") {
    return { id: "local", state: "ready", reason: "loopback_service_available", checked_at: checkedAt, action: { kind: "open_local_sources", enabled: true } };
  }
  return { id: "local", state: "unavailable", reason: "loopback_service_unavailable", checked_at: checkedAt, action: { kind: "open_local_sources", enabled: true } };
}

const READINESS_ORDER: readonly ReadinessCardId[] = ["local", "team_sync", "deep_analysis", "billing"];

/** Merge port-reported cards with the runtime-derived local card in a fixed order. */
export function orderedReadinessCards(
  portCards: readonly ReadinessCard[],
  local: ReadinessCard,
): ReadinessCard[] {
  return READINESS_ORDER.map((id) => {
    if (id === "local") return local;
    return portCards.find((card) => card.id === id) ?? {
      id,
      state: "unavailable",
      reason: id === "team_sync"
        ? "no_team_sync_service_in_this_build"
        : id === "billing"
          ? "no_billing_service_in_this_build"
          : "deep_analysis_not_verified_by_this_view",
      checked_at: null,
      action: { kind: "none", enabled: false },
    };
  });
}

export function shortUtcDate(value: string | null): string {
  if (value === null) return "date unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "date unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}
