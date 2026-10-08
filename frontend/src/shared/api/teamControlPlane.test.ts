import { describe, expect, it } from "vitest";
import {
  TEAM_CONTROL_PLANE_PORT_VERSION,
  isTeamIdentity,
  isTeamControlPlaneError,
  memberAuditDestinationForOrigin,
  teamAggregateRequestForAccess,
  teamAggregateSnapshotIsValid,
  teamCapabilityReportIsValid,
  teamControlPlaneResponseMatchesPort,
  teamScopeIdentityBindingIsCoherent,
  wilsonInterval,
  type TeamControlPlanePort,
  type AnalyticsScope,
  type TeamAggregateRequest,
  type TeamAggregateSnapshot,
  type TeamMemberVisibilityRequest,
  type TeamMetricAggregate,
} from "./teamControlPlane";
import {
  SYNTHETIC_TEAM_MEMBER_IDS,
  SYNTHETIC_TEAM_METRIC_SEEDS,
  StickyContributionDisclosurePolicy,
  createSyntheticTeamControlPlanePort,
  createUnavailableTeamControlPlanePort,
  teamMetricHasValue,
} from "./teamControlPlaneSynthetic";
import {
  composeTeamControlPlanePort,
  createTeamControlPlanePortForRuntime,
  teamControlPlanePortForOverlay,
} from "./teamControlPlaneRuntime";

const PSEUDONYM = /^[a-f0-9]{64}$/;
const INVALID_VISIBILITY_REQUEST: TeamMemberVisibilityRequest = {
  principal_id: "7".repeat(64),
  scope: "team",
  cohort_id: "0".repeat(64),
  team_id: "1".repeat(64),
  organization_id: "2".repeat(64),
  grant_id: "3".repeat(64),
};
const INVALID_AGGREGATE_REQUEST: TeamAggregateRequest = {
  principal_id: "7".repeat(64),
  scope: "team",
  cohort_id: "0".repeat(64),
  team_id: "1".repeat(64),
  organization_id: "2".repeat(64),
  query_id: "3".repeat(64),
};

async function aggregateRequest(port: TeamControlPlanePort, scope: AnalyticsScope): Promise<TeamAggregateRequest> {
  const report = await port.getCapabilities();
  const access = report.scopes.find((candidate) => candidate.scope === scope);
  const request = access === undefined ? null : teamAggregateRequestForAccess(access);
  if (request === null) throw new Error(`fixture aggregate request ${scope} is unavailable`);
  return request;
}

async function visibilityRequest(port: TeamControlPlanePort): Promise<TeamMemberVisibilityRequest> {
  const report = await port.getCapabilities();
  const team = report.scopes.find((scope) => scope.scope === "team")!;
  return {
    principal_id: report.principal_id,
    scope: "team",
    cohort_id: team.cohort_id!,
    team_id: team.team_id,
    organization_id: team.organization_id,
    grant_id: report.member_visibility.grant_id!,
  };
}

function byKey(metrics: readonly TeamMetricAggregate[], key: string, provenance: TeamMetricAggregate["provenance"] = "measured_typed") {
  const metric = metrics.find((candidate) => candidate.metric_key === key && candidate.provenance === provenance);
  if (metric === undefined) throw new Error(`fixture metric ${key} (${provenance}) is missing`);
  return metric;
}

describe("team control-plane identity bindings", () => {
  const identity = "ab".repeat(32);

  it.each([
    ["me", null, null, true],
    ["me", identity, null, false],
    ["me", null, identity, false],
    ["team", identity, null, true],
    ["team", identity, identity, true],
    ["team", null, identity, false],
    ["organization", null, identity, true],
    ["organization", identity, identity, true],
    ["organization", identity, null, false],
    ["team", "not-an-opaque-id", identity, false],
  ] as const)("binds %s scope to the exact legal identity shape", (scope, teamId, organizationId, expected) => {
    expect(teamScopeIdentityBindingIsCoherent(scope, teamId, organizationId)).toBe(expected);
  });

  it("keeps identity and audit-origin rules available through the stable façade", () => {
    expect(isTeamIdentity(identity)).toBe(true);
    expect(isTeamIdentity(identity.toUpperCase())).toBe(false);
    expect(memberAuditDestinationForOrigin("synthetic_fixture")).toBe("local_audit_log");
    expect(memberAuditDestinationForOrigin("local_loopback")).toBe("local_audit_log");
    expect(memberAuditDestinationForOrigin("team_control_plane")).toBe("team_control_plane");
  });
});

describe("teamMetricHasValue compatibility export", () => {
  it.each([
    ["known", true],
    ["suppressed_small_cohort", false],
    ["suppressed_privacy_policy", false],
    ["withheld_not_comparable", false],
    ["unknown", false],
    ["not_applicable", false],
    ["abstained", false],
    ["unavailable", false],
  ] as const)("maps %s to %s through the historical synthetic-module import", (state, expected) => {
    expect(teamMetricHasValue(state)).toBe(expected);
  });
});

describe("wilsonInterval", () => {
  it("bounds every fraction inside [0, 1] and refuses invalid inputs", () => {
    const interval = wilsonInterval(41, 57)!;
    expect(interval.low).toBeGreaterThan(0.58);
    expect(interval.low).toBeLessThan(41 / 57);
    expect(interval.high).toBeGreaterThan(41 / 57);
    expect(interval.high).toBeLessThan(0.83);
    expect(wilsonInterval(0, 3)!.low).toBeCloseTo(0, 10);
    expect(wilsonInterval(3, 3)!.high).toBeCloseTo(1, 10);
    expect(wilsonInterval(1, 0)).toBeNull();
    expect(wilsonInterval(4, 3)).toBeNull();
    expect(wilsonInterval(-1, 3)).toBeNull();
    expect(wilsonInterval(Number.NaN, 3)).toBeNull();
  });
});

describe("team control-plane response stamps", () => {
  it("requires both the exact origin and port version", () => {
    const port = createSyntheticTeamControlPlanePort();
    expect(teamControlPlaneResponseMatchesPort({
      origin: "synthetic_fixture",
      port_version: TEAM_CONTROL_PLANE_PORT_VERSION,
      principal_id: port.principalId,
    }, port)).toBe(true);
    expect(teamControlPlaneResponseMatchesPort({
      origin: "local_loopback",
      port_version: TEAM_CONTROL_PLANE_PORT_VERSION,
      principal_id: port.principalId,
    }, port)).toBe(false);
    expect(teamControlPlaneResponseMatchesPort({
      origin: "synthetic_fixture",
      port_version: "team-control-plane-port.invalid" as typeof TEAM_CONTROL_PLANE_PORT_VERSION,
      principal_id: port.principalId,
    }, port)).toBe(false);
    expect(teamControlPlaneResponseMatchesPort({
      origin: "synthetic_fixture",
      port_version: TEAM_CONTROL_PLANE_PORT_VERSION,
      principal_id: "aa".repeat(32),
    }, port)).toBe(false);
  });

  it.each([
    "duplicate scope",
    "incoherent scope reason",
    "invalid allowed identity",
    "grant binding mismatch",
    "report principal mismatch",
    "scope principal mismatch",
    "grant principal mismatch",
    "missing audit role",
    "invalid audit destination",
    "duplicate readiness card",
    "incoherent readiness state",
    "invalid checked timestamp",
  ] as const)("rejects a malformed capability report: %s", async (failure) => {
    const port = createSyntheticTeamControlPlanePort();
    const malformed = structuredClone(await port.getCapabilities());
    const team = malformed.scopes.find((scope) => scope.scope === "team")!;
    if (failure === "duplicate scope") {
      malformed.scopes = [malformed.scopes[0], malformed.scopes[0], malformed.scopes[2]];
    } else if (failure === "incoherent scope reason") {
      team.reason = "personal_scope_served_locally";
    } else if (failure === "invalid allowed identity") {
      team.aggregate_query_id = "not-an-identity";
    } else if (failure === "grant binding mismatch") {
      malformed.member_visibility.cohort_id = "fa".repeat(32);
    } else if (failure === "report principal mismatch") {
      malformed.principal_id = "fd".repeat(32);
    } else if (failure === "scope principal mismatch") {
      team.principal_id = "fb".repeat(32);
    } else if (failure === "grant principal mismatch") {
      malformed.member_visibility.principal_id = "fc".repeat(32);
    } else if (failure === "missing audit role") {
      malformed.member_visibility.audit.granted_by_role = null;
    } else if (failure === "invalid audit destination") {
      malformed.member_visibility.audit.log_destination = "team_control_plane";
    } else if (failure === "duplicate readiness card") {
      malformed.readiness = [malformed.readiness[0], malformed.readiness[0], malformed.readiness[2], malformed.readiness[3]];
    } else if (failure === "incoherent readiness state") {
      malformed.readiness[1].state = "ready";
    } else {
      malformed.checked_at = "not-a-timestamp";
    }
    expect(teamCapabilityReportIsValid(malformed, port)).toBe(false);
  });
});

describe("synthetic team control-plane port", () => {
  it("reports permission-aware scopes, an explicit member grant, and honest readiness", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const report = await port.getCapabilities();
    expect(teamCapabilityReportIsValid(report, port)).toBe(true);
    expect(report.port_version).toBe(TEAM_CONTROL_PLANE_PORT_VERSION);
    expect(report.origin).toBe("synthetic_fixture");
    expect(report.scopes.map((scope) => [scope.scope, scope.state])).toEqual([
      ["me", "allowed"],
      ["team", "allowed"],
      ["organization", "denied"],
    ]);
    expect(report.member_visibility.state).toBe("allowed");
    expect(report.member_visibility.grant_id).toMatch(PSEUDONYM);
    expect(report.member_visibility.scope).toBe("team");
    expect(report.member_visibility.audit.access_logged).toBe(true);
    const readiness = Object.fromEntries(report.readiness.map((card) => [card.id, card]));
    expect(readiness.local.reason).toBe("synthetic_fixture");
    expect(readiness.team_sync.state).toBe("unavailable");
    expect(readiness.team_sync.action.enabled).toBe(false);
    expect(readiness.billing.state).toBe("unavailable");
    expect(readiness.billing.reason).toBe("no_billing_service_in_this_build");
    expect(readiness.deep_analysis.state).toBe("unavailable");
  });

  it("publishes aggregate-only cohort metrics with every non-numeric state kept off the value axis", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const request = await aggregateRequest(port, "team");
    const snapshot = await port.getAggregate(request);
    expect(teamAggregateSnapshotIsValid(snapshot, request, port)).toBe(true);
    expect(snapshot.publication_policy).toBe("aggregate_only_no_ranking_no_universal_score");
    expect(snapshot.calibration).toBe("uncalibrated_exact_fractions");
    expect(snapshot.origin).toBe("synthetic_fixture");
    const measured = snapshot.metrics.filter((metric) => metric.provenance === "measured_typed");
    expect(measured.map((metric) => metric.metric_key)).toEqual(SYNTHETIC_TEAM_METRIC_SEEDS.map((seed) => seed.key));

    const known = byKey(snapshot.metrics, "prompt.task_definition_coverage");
    expect(known.value_state).toBe("known");
    expect(known.numeric_value).toBeCloseTo(41 / 57);
    expect(known.uncertainty.method).toBe("wilson_95");
    expect(known.uncertainty.low).not.toBeNull();
    expect(known.cohort.member_count).toBe(SYNTHETIC_TEAM_MEMBER_IDS.length);

    const suppressed = byKey(snapshot.metrics, "prompt.constraint_precision");
    expect(suppressed.value_state).toBe("suppressed_small_cohort");
    expect(suppressed.suppression_reason).toBe("small_cohort");
    expect(suppressed.numeric_value).toBeNull();
    expect(suppressed.numerator).toBeNull();
    expect(suppressed.cohort.member_count).toBe(SYNTHETIC_TEAM_MEMBER_IDS.length);
    expect(suppressed.cohort.minimum_contributor_count).toBe(3);
    expect(suppressed.missingness.members_with_value).toBeNull();
    expect(suppressed.missingness.sessions_without_receipt).toBeNull();

    const withheld = byKey(snapshot.metrics, "prompt.deliverable_contract");
    expect(withheld.value_state).toBe("withheld_not_comparable");
    expect(withheld.comparability.state).toBe("mixed_definition_versions");
    expect(withheld.numeric_value).toBeNull();

    expect(byKey(snapshot.metrics, "collaboration.exploration_conversion").value_state).toBe("not_applicable");
    expect(byKey(snapshot.metrics, "collaboration.exploration_conversion").missingness.sessions_without_receipt).toBe(0);
    expect(byKey(snapshot.metrics, "collaboration.scope_change_discipline").value_state).toBe("abstained");
    expect(byKey(snapshot.metrics, "logic.hypothesis_test_linkage").value_state).toBe("unknown");

    for (const metric of measured) {
      if (metric.value_state !== "known") {
        expect(metric.numeric_value).toBeNull();
        expect(metric.uncertainty.kind).toBe("not_estimated");
      }
    }
  });

  it.each([
    "cross-cohort identity",
    "cross-principal identity",
    "response principal mismatch",
    "duplicate metric identity",
    "out-of-bounds value",
    "incoherent fraction",
    "impossible count",
    "sub-k contributor disclosure",
    "stale count exceeds contributors",
    "inverted interval",
    "value outside interval",
    "suppression contradiction",
    "comparability contradiction",
    "known row marked non-comparable",
    "cross-provenance definition mismatch",
    "orphan experimental row",
    "unreviewed definition version",
    "model leak beside suppression",
    "model leak beside withholding",
    "receipt outside window",
  ] as const)("strictly rejects a malformed aggregate: %s", async (failure) => {
    const port = createSyntheticTeamControlPlanePort();
    const request = await aggregateRequest(port, "team");
    const valid = await port.getAggregate(request);
    const malformed = structuredClone(valid) as TeamAggregateSnapshot;
    if (failure === "cross-cohort identity") {
      malformed.request = { ...malformed.request, cohort_id: "fa".repeat(32) };
    } else if (failure === "cross-principal identity") {
      malformed.request = { ...malformed.request, principal_id: "fb".repeat(32) };
    } else if (failure === "response principal mismatch") {
      malformed.principal_id = "fc".repeat(32);
    } else if (failure === "duplicate metric identity") {
      (malformed.metrics as TeamMetricAggregate[]).push(structuredClone(malformed.metrics[0]));
    } else if (failure === "out-of-bounds value") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).numeric_value = 1.2;
    } else if (failure === "incoherent fraction") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).numerator = 40;
    } else if (failure === "impossible count") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).missingness.members_with_value = 6;
    } else if (failure === "sub-k contributor disclosure") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).missingness.members_with_value = 2;
    } else if (failure === "stale count exceeds contributors") {
      (byKey(malformed.metrics, "prompt.acceptance_testability") as TeamMetricAggregate).freshness.stale_member_count = 5;
    } else if (failure === "inverted interval") {
      const uncertainty = (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).uncertainty;
      uncertainty.low = 0.9;
      uncertainty.high = 0.2;
    } else if (failure === "value outside interval") {
      const uncertainty = (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).uncertainty;
      uncertainty.low = 0.8;
      uncertainty.high = 0.9;
    } else if (failure === "suppression contradiction") {
      (byKey(malformed.metrics, "prompt.constraint_precision") as TeamMetricAggregate).suppression_reason = "overlap_or_differencing";
    } else if (failure === "comparability contradiction") {
      const metric = byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate;
      metric.comparability = { state: "comparable", definition_versions: [metric.definition_version, metric.definition_version + 1] };
    } else if (failure === "known row marked non-comparable") {
      const metric = byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate;
      metric.comparability = { state: "mixed_windows", definition_versions: [metric.definition_version] };
    } else if (failure === "cross-provenance definition mismatch") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage", "experimental_model") as TeamMetricAggregate).definition_version += 1;
    } else if (failure === "orphan experimental row") {
      malformed.metrics = malformed.metrics.filter((metric) => !(
        metric.metric_key === "prompt.task_definition_coverage" && metric.provenance === "measured_typed"
      ));
    } else if (failure === "unreviewed definition version") {
      (byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate).definition_version = 999;
    } else if (failure === "model leak beside suppression") {
      const leaked = structuredClone(byKey(malformed.metrics, "prompt.task_definition_coverage", "experimental_model"));
      leaked.metric_key = "prompt.constraint_precision";
      leaked.definition_version = 2;
      (malformed.metrics as TeamMetricAggregate[]).push(leaked);
    } else if (failure === "model leak beside withholding") {
      const leaked = structuredClone(byKey(malformed.metrics, "prompt.task_definition_coverage", "experimental_model"));
      leaked.metric_key = "prompt.deliverable_contract";
      leaked.definition_version = 3;
      (malformed.metrics as TeamMetricAggregate[]).push(leaked);
    } else {
      const metric = byKey(malformed.metrics, "prompt.task_definition_coverage") as TeamMetricAggregate;
      metric.freshness.oldest_receipt_at = "2039-12-30T08:00:00Z";
      metric.freshness.newest_receipt_at = "2039-12-31T08:00:00Z";
    }
    expect(teamAggregateSnapshotIsValid(malformed, request, port)).toBe(false);
  });

  it("rejects an invalid expected query even when a response echoes it exactly", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const request = await aggregateRequest(port, "team");
    const snapshot = await port.getAggregate(request);
    const invalid = { ...request, query_id: "not-a-pseudonymous-query" };
    const echoed = { ...snapshot, request: invalid };
    expect(teamAggregateSnapshotIsValid(echoed, invalid, port)).toBe(false);
  });

  it("applies an explicit sticky, overlap-aware contributor disclosure threshold", () => {
    const policy = new StickyContributionDisclosurePolicy();
    const query = (queryId: string, contributorIds: readonly string[]) => policy.decide({
      family: "example.metric:v1:window-a",
      queryId,
      contributorIds,
      minimumContributorCount: 3,
    });

    expect(query("direct-sub-k", ["example-a", "example-b"])).toEqual({ state: "suppressed", suppressionReason: "small_cohort" });
    // A suppressed immutable query never flips to released after its inputs change.
    expect(query("direct-sub-k", ["example-a", "example-b", "example-c", "example-d"])).toEqual({ state: "suppressed", suppressionReason: "query_identity_mismatch" });

    expect(query("released", ["example-a", "example-b", "example-c"])).toEqual({ state: "released", suppressionReason: null });
    expect(query("released", ["example-a", "example-b", "example-c"])).toEqual({ state: "released", suppressionReason: null });
    // Reusing a released identity with changed membership fails closed.
    expect(query("released", ["example-a", "example-b", "example-c", "example-d"])).toEqual({ state: "suppressed", suppressionReason: "query_identity_mismatch" });

    const history = new StickyContributionDisclosurePolicy();
    const decideHistory = (queryId: string, contributorIds: readonly string[]) => history.decide({
      family: "example.history:v1:window-a",
      queryId,
      contributorIds,
      minimumContributorCount: 3,
    });
    expect(decideHistory("released", ["example-a", "example-b", "example-c"])).toEqual({ state: "released", suppressionReason: null });
    expect(decideHistory("released", ["example-a", "example-b", "example-c", "example-d"])).toEqual({ state: "suppressed", suppressionReason: "query_identity_mismatch" });
    // The original released set remains in disclosure history after fail-closed reuse.
    expect(decideHistory("later", ["example-a", "example-b", "example-c", "example-e"])).toEqual({ state: "suppressed", suppressionReason: "overlap_or_differencing" });

    const overlap = new StickyContributionDisclosurePolicy();
    const decideOverlap = (queryId: string, contributorIds: readonly string[]) => overlap.decide({
      family: "example.other:v1:window-a",
      queryId,
      contributorIds,
      minimumContributorCount: 3,
    });
    expect(decideOverlap("scope-a", ["example-a", "example-b", "example-c", "example-d"])).toEqual({ state: "released", suppressionReason: null });
    // Both totals meet k, but subtraction would expose one contributor on each side.
    expect(decideOverlap("scope-b", ["example-a", "example-b", "example-c", "example-e"])).toEqual({ state: "suppressed", suppressionReason: "overlap_or_differencing" });
    // A three-member remainder is safe at k=3 and can be released.
    expect(decideOverlap("scope-c", ["example-a", "example-b", "example-c", "example-d", "example-e", "example-f", "example-g"])).toEqual({ state: "released", suppressionReason: null });
    expect(decideOverlap("disjoint", ["example-h", "example-i", "example-j"])).toEqual({ state: "released", suppressionReason: null });

    const delimiters = new StickyContributionDisclosurePolicy();
    expect(delimiters.decide({ family: "family|part", queryId: "query", contributorIds: ["a,b", "c", "d"], minimumContributorCount: 3 }))
      .toEqual({ state: "released", suppressionReason: null });
    expect(delimiters.decide({ family: "family", queryId: "part|query", contributorIds: ["a", "b,c", "d"], minimumContributorCount: 3 }))
      .toEqual({ state: "released", suppressionReason: null });
    expect(delimiters.decide({ family: "family|part", queryId: "query", contributorIds: ["a", "b,c", "d"], minimumContributorCount: 3 }))
      .toEqual({ state: "suppressed", suppressionReason: "query_identity_mismatch" });
  });

  it("suppresses a nominally k-sized team contribution when Me/Team differencing leaves sub-k", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const snapshot = await port.getAggregate(await aggregateRequest(port, "team"));
    const protectedMetric = byKey(snapshot.metrics, "prompt.problem_evidence_quality");
    expect(protectedMetric.cohort.member_count).toBe(5);
    expect(protectedMetric.value_state).toBe("suppressed_privacy_policy");
    expect(protectedMetric.suppression_reason).toBe("overlap_or_differencing");
    expect(protectedMetric.numeric_value).toBeNull();
    expect(protectedMetric.missingness.members_with_value).toBeNull();
    expect(protectedMetric.missingness.sessions_without_receipt).toBeNull();
  });

  it("keeps experimental model ranges as separate rows that never replace a measured row", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const snapshot = await port.getAggregate(await aggregateRequest(port, "team"));
    const experimental = snapshot.metrics.filter((metric) => metric.provenance === "experimental_model");
    expect(experimental.length).toBeGreaterThan(0);
    for (const range of experimental) {
      expect(range.uncertainty.method).toBe("model_range_90");
      expect(range.numerator).toBeNull();
      expect(byKey(snapshot.metrics, range.metric_key)).toBeDefined();
    }
    const measuredUnknown = byKey(snapshot.metrics, "logic.decision_rationale_coverage");
    expect(measuredUnknown.value_state).toBe("unknown");
    expect(byKey(snapshot.metrics, "logic.decision_rationale_coverage", "experimental_model").numeric_value).toBeCloseTo(0.44);
  });

  it("serves the personal scope with a single-member cohort and an explicit measured zero", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const snapshot = await port.getAggregate(await aggregateRequest(port, "me"));
    expect(snapshot.scope).toBe("me");
    const zero = byKey(snapshot.metrics, "outcome.first_pass_verification");
    expect(zero.value_state).toBe("known");
    expect(zero.numeric_value).toBe(0);
    expect(zero.numerator).toBe(0);
    expect(zero.denominator).toBe(3);
    expect(zero.cohort.member_count).toBe(1);
    const unknownReceiptCoverage = byKey(snapshot.metrics, "collaboration.clarification_yield");
    expect(unknownReceiptCoverage.value_state).toBe("not_applicable");
    expect(unknownReceiptCoverage.missingness.sessions_without_receipt).toBeNull();
  });

  it("fails closed for scopes that are denied or unavailable", async () => {
    const port = createSyntheticTeamControlPlanePort({ team: "denied" });
    await expect(port.getAggregate({ ...INVALID_AGGREGATE_REQUEST, scope: "organization" })).rejects.toSatisfy((error: unknown) =>
      isTeamControlPlaneError(error) && error.code === "scope_not_allowed");
    await expect(port.getAggregate(INVALID_AGGREGATE_REQUEST)).rejects.toSatisfy((error: unknown) =>
      isTeamControlPlaneError(error) && error.code === "scope_not_allowed");
    const report = await port.getCapabilities();
    expect(teamCapabilityReportIsValid(report, port)).toBe(true);
    expect(report.scopes.find((scope) => scope.scope === "team")?.state).toBe("denied");
  });

  it("lists only consenting members, ordered by pseudonymous id, without any ranking", async () => {
    const port = createSyntheticTeamControlPlanePort({ now: () => "2040-01-31T09:00:00Z" });
    expect(port.getRevealAuditEvents()).toEqual([]);
    const request = await visibilityRequest(port);
    const page = await port.getMemberVisibility(request);
    expect(page.request).toEqual(request);
    expect(page.ordering).toBe("stable_member_id");
    expect(page.members.every((member) => member.consent === "granted")).toBe(true);
    expect(page.withheld_member_count).toBe(1);
    expect(page.members.map((member) => member.member_id)).toEqual(SYNTHETIC_TEAM_MEMBER_IDS.slice(0, 4));
    for (const member of page.members) {
      expect(member.member_id).toMatch(PSEUDONYM);
      expect(member.display_handle).toMatch(/^Member \d\d$/);
      expect(member.metrics).toHaveLength(SYNTHETIC_TEAM_METRIC_SEEDS.length);
      for (const cell of member.metrics) {
        if (cell.value_state !== "known") expect(cell.numeric_value).toBeNull();
        else expect(cell.numeric_value).toBeGreaterThanOrEqual(0);
      }
    }
    const rows = page.members as unknown as Record<string, unknown>[];
    expect(rows.some((row) => "score" in row || "rank" in row || "total" in row)).toBe(false);
    expect(port.getRevealAuditEvents()).toEqual([{
      event: "member_visibility_revealed",
      occurred_at: "2040-01-31T09:00:00Z",
      destination: "local_audit_log",
      grant_reason: "granted_with_member_consent",
      principal_id: request.principal_id,
      grant_id: request.grant_id,
      scope: "team",
      cohort_id: request.cohort_id,
      team_id: request.team_id,
      organization_id: request.organization_id,
      returned_member_count: 4,
      withheld_member_count: 1,
    }]);
  });

  it("refuses a member request whose active scope/cohort/grant binding is not exact", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const request = await visibilityRequest(port);
    await expect(port.getMemberVisibility({ ...request, cohort_id: "9b".repeat(32) }))
      .rejects.toSatisfy((error: unknown) =>
        isTeamControlPlaneError(error) && error.code === "member_visibility_not_granted");
    await expect(port.getMemberVisibility({ ...request, grant_id: "8a".repeat(32) }))
      .rejects.toSatisfy((error: unknown) =>
        isTeamControlPlaneError(error) && error.code === "member_visibility_not_granted");
    await expect(port.getMemberVisibility({ ...request, principal_id: "7b".repeat(32) }))
      .rejects.toSatisfy((error: unknown) =>
        isTeamControlPlaneError(error) && error.code === "member_visibility_not_granted");
    expect(port.getRevealAuditEvents()).toEqual([]);
  });

  it("refuses member visibility without a grant", async () => {
    await expect(createSyntheticTeamControlPlanePort({ memberVisibility: "denied" }).getMemberVisibility(INVALID_VISIBILITY_REQUEST))
      .rejects.toSatisfy((error: unknown) => isTeamControlPlaneError(error) && error.code === "member_visibility_not_granted");
    await expect(createSyntheticTeamControlPlanePort({ memberVisibility: "unavailable" }).getMemberVisibility(INVALID_VISIBILITY_REQUEST))
      .rejects.toSatisfy((error: unknown) => isTeamControlPlaneError(error) && error.code === "member_visibility_unavailable");
  });

  it("returns defensive copies so callers cannot mutate the fixture", async () => {
    const port = createSyntheticTeamControlPlanePort();
    const request = await aggregateRequest(port, "team");
    const first = await port.getAggregate(request);
    (first.metrics as TeamMetricAggregate[]).length = 0;
    const second = await port.getAggregate(request);
    expect(second.metrics.length).toBeGreaterThan(0);
  });
});

describe("unavailable team control-plane port", () => {
  it("reports every team capability as absent and serves no scope", async () => {
    const port = createUnavailableTeamControlPlanePort(() => "2040-02-01T00:00:00Z");
    const report = await port.getCapabilities();
    expect(teamCapabilityReportIsValid(report, port)).toBe(true);
    expect(report.origin).toBe("local_loopback");
    expect(report.scopes.map((scope) => [scope.scope, scope.state, scope.reason])).toEqual([
      ["me", "allowed", "personal_scope_served_locally"],
      ["team", "unavailable", "local_runtime_has_no_team_service"],
      ["organization", "unavailable", "local_runtime_has_no_team_service"],
    ]);
    expect(report.member_visibility.state).toBe("unavailable");
    expect(report.readiness.find((card) => card.id === "team_sync")?.state).toBe("unavailable");
    expect(report.readiness.find((card) => card.id === "billing")?.state).toBe("unavailable");
    await expect(port.getAggregate({ ...INVALID_AGGREGATE_REQUEST, scope: "me", team_id: null, organization_id: null })).rejects.toSatisfy((error: unknown) =>
      isTeamControlPlaneError(error) && error.code === "scope_not_served_by_this_runtime");
    await expect(port.getMemberVisibility(INVALID_VISIBILITY_REQUEST)).rejects.toSatisfy((error: unknown) =>
      isTeamControlPlaneError(error) && error.code === "member_visibility_unavailable");
  });

  it("binds each runtime mode to its honest port", () => {
    expect(createTeamControlPlanePortForRuntime("synthetic_demo").origin).toBe("synthetic_fixture");
    expect(createTeamControlPlanePortForRuntime("local_real").origin).toBe("local_loopback");
  });

  it("keeps the synthetic server authoritative when its grant expires", async () => {
    let now = "2040-01-31T09:00:00Z";
    const port = createSyntheticTeamControlPlanePort({ now: () => now });
    const request = await visibilityRequest(port);
    now = "2040-03-02T09:00:00Z";
    await expect(port.getMemberVisibility(request)).rejects.toSatisfy((error: unknown) =>
      isTeamControlPlaneError(error) && error.code === "member_visibility_not_granted");
    expect(port.getRevealAuditEvents()).toEqual([]);
  });

  it("exposes only privately registered runtime ports to the overlay", () => {
    const synthetic = createTeamControlPlanePortForRuntime("synthetic_demo");
    const local = createTeamControlPlanePortForRuntime("local_real");
    expect(teamControlPlanePortForOverlay("synthetic_demo", synthetic)).toBe(synthetic);
    expect(teamControlPlanePortForOverlay("synthetic_demo", createSyntheticTeamControlPlanePort())).toBeNull();
    expect(teamControlPlanePortForOverlay("local_real", local)).toBe(local);
    expect(teamControlPlanePortForOverlay("local_real", synthetic)).toBeNull();
    expect(teamControlPlanePortForOverlay("synthetic_demo", null)).toBeNull();
  });

  it("registers the local runtime transport as readiness-only", async () => {
    const local = createTeamControlPlanePortForRuntime("local_real", {
      getControlPlaneReadiness: async () => ({
        contract_version: "control-plane-v2",
        delivery_guarantee: "at_least_once_with_monotonic_ack",
        gaps: ["governance_review_pending"],
        production_ready: false,
        profile: "development",
        remote_listening_enabled: false,
      }),
    });

    const report = await local.getCapabilities();

    expect(report.control_plane_readiness?.gaps).toEqual(["governance_review_pending"]);
    expect(teamControlPlanePortForOverlay("local_real", local)).toBe(local);
    await expect(local.getAggregate(INVALID_AGGREGATE_REQUEST)).rejects.toSatisfy(
      (error: unknown) => isTeamControlPlaneError(error)
        && error.code === "scope_not_served_by_this_runtime",
    );
  });

  it("fails closed when a synthetic fixture port is injected into local-real composition", () => {
    const composed = composeTeamControlPlanePort("local_real", createSyntheticTeamControlPlanePort());
    expect(composed.origin).toBe("local_loopback");
    expect(composed).not.toBe(createSyntheticTeamControlPlanePort());
  });

  it("rejects a fully relabelled synthetic adapter without private runtime registration", async () => {
    const fixture = createSyntheticTeamControlPlanePort();
    const relabelled: TeamControlPlanePort = {
      portVersion: fixture.portVersion,
      origin: "local_loopback",
      principalId: fixture.principalId,
      async getCapabilities(signal) {
        return { ...await fixture.getCapabilities(signal), origin: "local_loopback" };
      },
      async getAggregate(request, signal) {
        return { ...await fixture.getAggregate(request, signal), origin: "local_loopback" };
      },
      async getMemberVisibility(request, signal) {
        return { ...await fixture.getMemberVisibility(request, signal), origin: "local_loopback" };
      },
    };
    const composed = composeTeamControlPlanePort("local_real", relabelled);
    expect(composed).not.toBe(relabelled);
    expect((await composed.getCapabilities()).scopes.find((scope) => scope.scope === "team")?.state).toBe("unavailable");

    const registered = createTeamControlPlanePortForRuntime("local_real");
    expect(composeTeamControlPlanePort("local_real", registered)).toBe(registered);
    expect(Object.isFrozen(registered)).toBe(true);
  });
});
