import type { ControlPlaneReadiness } from "./contracts";

/**
 * Typed frontend port for a FUTURE canonical team control plane.
 *
 * Nothing in the shipped backend implements the aggregate/member methods. The
 * dashboard consumes the contract only through honest runtime adapters:
 *
 * - a synthetic in-memory fixture (development preview, fictional cohort);
 * - a local adapter that can observe exact development-readiness blockers but
 *   rejects every aggregate/member read, with an unavailable fallback when
 *   the optional readiness route is not mounted.
 *
 * Design rules carried by the types themselves:
 * - Team and organization views are aggregates over a cohort. Individual
 *   member rows exist only behind an explicit visibility grant.
 * - No ranking, leaderboard, or single employee/developer score can be
 *   expressed: aggregates carry cohort size, missingness, comparability,
 *   freshness, and uncertainty instead.
 * - Missing values stay unknown. Suppressed small cohorts stay suppressed.
 * - Every payload states its origin so a fixture can never be mistaken for a
 *   live account, sync, billing, or calibrated measurement.
 */
export const TEAM_CONTROL_PLANE_PORT_VERSION = "team-control-plane-port.v0" as const;

export type AnalyticsScope = "me" | "team" | "organization";

export const ANALYTICS_SCOPES: readonly AnalyticsScope[] = ["me", "team", "organization"];

export type TeamDataOrigin = "synthetic_fixture" | "local_loopback" | "team_control_plane";

export type ScopeAccessState = "allowed" | "denied" | "unavailable";

export type ScopeAccessReason =
  | "granted"
  | "personal_scope_served_locally"
  | "local_runtime_has_no_team_service"
  | "development_control_plane_incomplete"
  | "team_sync_not_configured"
  | "role_insufficient"
  | "organization_policy_disabled"
  | "consent_required";

export interface ScopeAccess {
  /** Opaque authorization principal; never a username, email, or account id. */
  principal_id: string;
  scope: AnalyticsScope;
  state: ScopeAccessState;
  reason: ScopeAccessReason;
  /** Human-safe cohort label supplied by the control plane; never a person's name. */
  cohort_label: string | null;
  /** Opaque pseudonymous identifiers bind grants and requests to one exact cohort. */
  cohort_id: string | null;
  team_id: string | null;
  organization_id: string | null;
  /** Immutable server-issued identity for the aggregate query in this scope. */
  aggregate_query_id: string | null;
}

export interface TeamAggregateRequest {
  principal_id: string;
  scope: AnalyticsScope;
  cohort_id: string;
  team_id: string | null;
  organization_id: string | null;
  query_id: string;
}

export type MemberVisibilityState = "allowed" | "denied" | "unavailable";

export type MemberVisibilityReason =
  | "granted_with_member_consent"
  | "permission_not_granted"
  | "member_consent_missing"
  | "cohort_below_minimum"
  | "development_control_plane_incomplete"
  | "unavailable_in_runtime";

export interface MemberVisibilityAudit {
  /** Role that issued the grant (never an identity), or null when no grant exists. */
  granted_by_role: string | null;
  granted_at: string | null;
  expires_at: string | null;
  /** True when opening the member view is written to an audit log. */
  access_logged: boolean;
  log_destination: "local_audit_log" | "team_control_plane" | null;
}

export interface MemberVisibilityGrant {
  /** Opaque principal to whom this grant was issued. */
  principal_id: string;
  /** Opaque grant and target identities; null means no usable grant exists. */
  grant_id: string | null;
  scope: Exclude<AnalyticsScope, "me"> | null;
  cohort_id: string | null;
  team_id: string | null;
  organization_id: string | null;
  state: MemberVisibilityState;
  reason: MemberVisibilityReason;
  audit: MemberVisibilityAudit;
}

export interface TeamMemberVisibilityRequest {
  principal_id: string;
  scope: Exclude<AnalyticsScope, "me">;
  cohort_id: string;
  team_id: string | null;
  organization_id: string | null;
  grant_id: string;
}

export type ReadinessCardId = "local" | "team_sync" | "deep_analysis" | "billing";

export type ReadinessState = "ready" | "partial" | "checking" | "not_configured" | "unavailable";

export type ReadinessReason =
  | "synthetic_fixture"
  | "loopback_service_checking"
  | "loopback_service_available"
  | "loopback_service_unavailable"
  | "no_team_sync_service_in_this_build"
  | "development_control_plane_incomplete"
  | "team_sync_not_configured"
  | "deep_analysis_not_in_synthetic_preview"
  | "deep_analysis_not_verified_by_this_view"
  | "no_billing_service_in_this_build";

export type ReadinessActionKind =
  | "none"
  | "open_local_sources"
  | "open_job_centre"
  | "open_methods_and_models";

export interface ReadinessCard {
  id: ReadinessCardId;
  state: ReadinessState;
  reason: ReadinessReason;
  checked_at: string | null;
  action: { kind: ReadinessActionKind; enabled: boolean };
}

export interface TeamCapabilityReport {
  port_version: typeof TEAM_CONTROL_PLANE_PORT_VERSION;
  origin: TeamDataOrigin;
  /** Opaque subject of every capability, request, and grant in this report. */
  principal_id: string;
  scopes: readonly ScopeAccess[];
  member_visibility: MemberVisibilityGrant;
  readiness: readonly ReadinessCard[];
  /** Exact default-off backend readiness, or null when that route did not answer. */
  control_plane_readiness: ControlPlaneReadiness | null;
  checked_at: string;
}

export type MetricDirection = "higher_is_better" | "lower_is_better";

/**
 * Aggregate value states. Suppression is a deliberate refusal to publish a
 * value that could re-identify a member; its typed reason distinguishes a
 * directly small cohort from overlap/differencing or identity protection.
 * `withheld_not_comparable` refuses a ratio-of-sums across incompatible
 * definitions or windows. Neither is unknown and neither is zero.
 */
export type TeamMetricValueState =
  | "known"
  | "suppressed_small_cohort"
  | "suppressed_privacy_policy"
  | "withheld_not_comparable"
  | "unknown"
  | "not_applicable"
  | "abstained"
  | "unavailable";

/** Measured typed receipts and experimental model ranges never merge silently. */
export type TeamMetricProvenance = "measured_typed" | "experimental_model";

export interface TeamMetricCohort {
  member_count: number | null;
  session_count: number | null;
  /** Minimum size of the described cohort itself. */
  minimum_member_count: number;
  /** Minimum distinct contributing members required to publish a value/count. */
  minimum_contributor_count: number;
}

export interface TeamMetricMissingness {
  members_with_value: number | null;
  members_in_cohort: number | null;
  sessions_without_receipt: number | null;
}

export type TeamMetricComparabilityState =
  | "comparable"
  | "mixed_definition_versions"
  | "mixed_windows"
  | "not_comparable";

export interface TeamMetricComparability {
  state: TeamMetricComparabilityState;
  definition_versions: readonly number[];
}

export interface TeamMetricFreshness {
  newest_receipt_at: string | null;
  oldest_receipt_at: string | null;
  stale_member_count: number | null;
  stale_after_days: number;
}

/**
 * `wilson_95` is a sampling interval on an exact measured fraction.
 * `model_range_90` is the central 90% range of an experimental model estimate;
 * it is a model judgment, never measured evidence, and is only valid together
 * with `provenance: "experimental_model"`.
 */
export interface TeamMetricUncertainty {
  kind: "interval" | "not_estimated";
  method: "wilson_95" | "model_range_90" | null;
  low: number | null;
  high: number | null;
}

export interface TeamMetricAggregate {
  metric_key: string;
  definition_version: number;
  direction: MetricDirection;
  value_state: TeamMetricValueState;
  /** Exact reason a value is suppressed; null for every published/non-suppressed state. */
  suppression_reason: TeamMetricSuppressionReason | null;
  /** Ratio-of-sums numerator across the cohort; never an average of member percentages. */
  numerator: number | null;
  denominator: number | null;
  numeric_value: number | null;
  provenance: TeamMetricProvenance;
  cohort: TeamMetricCohort;
  missingness: TeamMetricMissingness;
  comparability: TeamMetricComparability;
  freshness: TeamMetricFreshness;
  uncertainty: TeamMetricUncertainty;
}

export type TeamMetricSuppressionReason =
  | "small_cohort"
  | "overlap_or_differencing"
  | "query_identity_mismatch";

export interface TeamAggregateWindow {
  label: string;
  started_at: string;
  ended_at: string;
}

export interface TeamAggregateSnapshot {
  port_version: typeof TEAM_CONTROL_PLANE_PORT_VERSION;
  origin: TeamDataOrigin;
  principal_id: string;
  /** Exact immutable scope/cohort query evaluated for this response. */
  request: TeamAggregateRequest;
  scope: AnalyticsScope;
  cohort_label: string;
  window: TeamAggregateWindow;
  generated_at: string;
  /** Aggregates are the only shape this port can publish for a cohort. */
  publication_policy: "aggregate_only_no_ranking_no_universal_score";
  calibration: "uncalibrated_exact_fractions";
  /**
   * One entry per (metric_key, provenance). A measured entry and an
   * experimental entry for the same key stay separate rows; consumers must
   * never blend them into one value.
   */
  metrics: readonly TeamMetricAggregate[];
}

export interface TeamMemberMetricCell {
  metric_key: string;
  definition_version: number;
  value_state: "known" | "unknown" | "not_applicable" | "abstained";
  numerator: number | null;
  denominator: number | null;
  numeric_value: number | null;
  provenance: TeamMetricProvenance;
  newest_receipt_at: string | null;
}

export interface TeamMemberRow {
  /** Pseudonymous member identifier (64 lowercase hex characters). */
  member_id: string;
  /** Neutral fixture handle such as "Member 03"; never a real name or account. */
  display_handle: string;
  consent: "granted" | "withheld";
  metrics: readonly TeamMemberMetricCell[];
}

export interface TeamMemberVisibilityPage {
  port_version: typeof TEAM_CONTROL_PLANE_PORT_VERSION;
  origin: TeamDataOrigin;
  principal_id: string;
  /** Exact authorization request the server evaluated for this page. */
  request: TeamMemberVisibilityRequest;
  grant: MemberVisibilityGrant;
  /** Rows are ordered by member identifier only; the port never orders by value. */
  ordering: "stable_member_id";
  members: readonly TeamMemberRow[];
  /** Members who withheld consent are counted, never listed. */
  withheld_member_count: number;
}

export type TeamControlPlaneErrorCode =
  | "scope_not_allowed"
  | "scope_not_served_by_this_runtime"
  | "member_visibility_not_granted"
  | "member_visibility_unavailable";

export class TeamControlPlaneError extends Error {
  readonly code: TeamControlPlaneErrorCode;

  constructor(code: TeamControlPlaneErrorCode, message: string) {
    super(message);
    this.name = "TeamControlPlaneError";
    this.code = code;
  }
}

export function isTeamControlPlaneError(value: unknown): value is TeamControlPlaneError {
  return value instanceof TeamControlPlaneError;
}

export interface TeamControlPlanePort {
  readonly portVersion: typeof TEAM_CONTROL_PLANE_PORT_VERSION;
  readonly origin: TeamDataOrigin;
  /** Immutable opaque principal for which this adapter was composed. */
  readonly principalId: string;
  getCapabilities(signal?: AbortSignal): Promise<TeamCapabilityReport>;
  getAggregate(request: TeamAggregateRequest, signal?: AbortSignal): Promise<TeamAggregateSnapshot>;
  getMemberVisibility(request: TeamMemberVisibilityRequest, signal?: AbortSignal): Promise<TeamMemberVisibilityPage>;
}

export interface TeamControlPlaneStampedResponse {
  port_version: typeof TEAM_CONTROL_PLANE_PORT_VERSION;
  origin: TeamDataOrigin;
  principal_id: string;
}

/**
 * A payload is usable only when its immutable version, origin, and opaque
 * principal match the exact port that returned it. In particular, a
 * local-loopback declaration can never launder a synthetic fixture response
 * or another principal's cached payload into an active surface.
 */
export function teamControlPlaneResponseMatchesPort(
  response: unknown,
  port: Pick<TeamControlPlanePort, "origin" | "portVersion" | "principalId">,
): boolean {
  return typeof response === "object"
    && response !== null
    && "port_version" in response
    && "origin" in response
    && "principal_id" in response
    && response.port_version === port.portVersion
    && response.origin === port.origin
    && response.principal_id === port.principalId;
}

export interface TeamReviewedMetricContract {
  metric_key: string;
  definition_version: number;
  direction: MetricDirection;
}

/** Exact reviewed metric contracts accepted by the v0 team port. A new key or
 * version requires an explicit frontend/port review rather than rendering by
 * accident. */
export const TEAM_REVIEWED_METRIC_CONTRACTS: readonly TeamReviewedMetricContract[] = [
  { metric_key: "prompt.task_definition_coverage", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "prompt.problem_evidence_quality", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "prompt.context_sufficiency", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "prompt.constraint_precision", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "prompt.acceptance_testability", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "prompt.deliverable_contract", definition_version: 3, direction: "higher_is_better" },
  { metric_key: "collaboration.ambiguity_resolution", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "collaboration.clarification_yield", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "collaboration.exploration_conversion", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "collaboration.scope_change_discipline", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "collaboration.rework_candidate_rate", definition_version: 2, direction: "lower_is_better" },
  { metric_key: "logic.decomposition_coverage", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "logic.decision_rationale_coverage", definition_version: 3, direction: "higher_is_better" },
  { metric_key: "logic.open_loop_closure", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "outcome.verification_strategy_adequacy", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "logic.hypothesis_test_linkage", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "logic.requirement_action_traceability", definition_version: 3, direction: "higher_is_better" },
  { metric_key: "outcome.agent_claim_grounding", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "outcome.first_pass_verification", definition_version: 2, direction: "higher_is_better" },
  { metric_key: "outcome.verified_requirement_coverage", definition_version: 2, direction: "higher_is_better" },
];
