import { describe, expect, it } from "vitest";
import {
  syntheticMetricEvidenceReadinessV2,
  syntheticMetricPublicationV2,
  type MetricKeyV2,
  type MetricScenarioV2,
} from "../../test/metricPublicationV2Fixture";
import type { ModelEnsembleRun } from "../../shared/api/contracts";
import { metricEvidenceReadinessForPublication } from "./metricEvidenceReadiness";

type ProjectionVersion = NonNullable<ModelEnsembleRun["metric_publication_v2"]>["projection_version"];

function publicationFor(
  projectionVersion: ProjectionVersion,
  scenarios: Partial<Record<MetricKeyV2, MetricScenarioV2>> = {},
) {
  const resolvedScenarios: Partial<Record<MetricKeyV2, MetricScenarioV2>> = {
    ...scenarios,
  };
  if (
    ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      projectionVersion,
    )
    && resolvedScenarios["logic.requirement_action_traceability"] === undefined
  ) {
    resolvedScenarios["logic.requirement_action_traceability"] = {
      value_state: "unknown",
      capability_available: false,
      source_complete: true,
      eligible: 0,
      explanation_code: "requirement_action_evidence_unavailable",
    };
  }
  if (
    projectionVersion === "metric-contract-v2-projection-8"
    && resolvedScenarios["outcome.verified_requirement_coverage"] === undefined
  ) {
    resolvedScenarios["outcome.verified_requirement_coverage"] = {
      value_state: "unknown",
      capability_available: false,
      source_complete: true,
      eligible: 0,
      unknown: 0,
      explanation_code: "reviewed_requirement_authority_unavailable",
      distinct_owner_count: 0,
    };
  }
  const publication = structuredClone(syntheticMetricPublicationV2(resolvedScenarios));
  publication.projection_version = projectionVersion;
  for (const metric of publication.metrics) metric.state.projection_version = projectionVersion;
  return publication;
}

function expectReasonBound(
  publication: ReturnType<typeof syntheticMetricPublicationV2>,
  metricKey: MetricKeyV2,
  expectedReason: string,
) {
  const readiness = syntheticMetricEvidenceReadinessV2(publication);
  const target = readiness.metrics.find((row) => row.metric_key === metricKey);
  expect(target?.reason_code).toBe(expectedReason);
  expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);
  const tampered = structuredClone(readiness);
  const mutated = tampered.metrics.find((row) => row.metric_key === metricKey);
  if (mutated === undefined) throw new Error("synthetic readiness row missing");
  mutated.reason_code = (expectedReason === "calculator_abstained"
    ? "execution_error_reported"
    : "calculator_abstained") as typeof mutated.reason_code;
  expect(metricEvidenceReadinessForPublication(tampered, publication)).toBeNull();
}

describe("metric evidence readiness presentation binding", () => {
  it("accepts the all-twenty additive projection only for its exact sealed publication", () => {
    const publication = syntheticMetricPublicationV2({
      "prompt.task_definition_coverage": { value_state: "known", numerator: 2, denominator: 3 },
      "prompt.context_sufficiency": { value_state: "pending", eligible: 4, pending: 2, numerator: 1 },
    });
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);
    expect(readiness.metrics).toHaveLength(20);
    expect(readiness.measured_count + readiness.pending_count + readiness.capability_missing_count).toBe(20);
    expect(readiness.objective_metric_count).toBe(5);
    expect(readiness.objective_measurable_count).toBe(0);
    expect(readiness.objective_measured_count).toBe(0);
    expect(readiness.metrics.find((row) => row.metric_key === "logic.hypothesis_test_linkage")?.required_adapter_capabilities)
      .toEqual(["hypothesis_opportunities", "hypothesis_evidence_links", "tool_events", "decision_events", "verification_events"]);
  });

  it("withholds pending readiness unless source authority and both censoring bounds are exact", () => {
    const exact = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "pending", capability_available: true, source_complete: true,
        eligible: 4, numerator: 1, pending: 2,
        explanation_code: "opportunity_right_censored",
      },
      "logic.requirement_action_traceability": {
        value_state: "unknown", capability_available: false, source_complete: true,
        eligible: 4, unknown: 4, explanation_code: "requirement_action_evidence_unavailable",
      },
    });
    expect(metricEvidenceReadinessForPublication(
      syntheticMetricEvidenceReadinessV2(exact),
      exact,
    )).not.toBeNull();

    for (const mutate of [
      (state: any) => { state.statistics.source_complete = false; },
      (state: any) => { state.statistics.capability_available = false; },
      (state: any) => { state.censoring_lower_bound = null; },
      (state: any) => { state.censoring_upper_bound = null; },
      (state: any) => { state.censoring_lower_bound = 0.5; },
      (state: any) => { state.censoring_upper_bound = 0.5; },
    ]) {
      const attacked = structuredClone(exact);
      const state = attacked.metrics.find(
        (item) => item.state.metric_key === "logic.decomposition_coverage",
      )!.state;
      mutate(state);
      expect(metricEvidenceReadinessForPublication(
        syntheticMetricEvidenceReadinessV2(attacked),
        attacked,
      )).toBeNull();
    }
  });

  it("withholds contributor prose when identity, row order, counts, or contributor partitions drift", () => {
    const publication = syntheticMetricPublicationV2();
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const mutations: Array<(value: any) => void> = [
      (value) => { value.unexpected_projection_detail = false; },
      (value) => { value.metrics[0].unexpected_row_detail = false; },
      (value) => { value.contract_set_fingerprint = "0".repeat(64); },
      (value) => { value.metric_projection_version = "metric-contract-v2-projection-3"; },
      (value) => { [value.metrics[0], value.metrics[1]] = [value.metrics[1], value.metrics[0]]; },
      (value) => { value.metrics[0].contract_fingerprint = "1".repeat(64); },
      (value) => { value.metrics[0].missing_contributors = []; },
      (value) => { value.metrics[12].required_adapter_capabilities = ["verification_events"]; },
      (value) => { value.metrics[12].reason_code = "generic_objective_capability_required"; },
      (value) => { value.capability_missing_count += 1; },
      (value) => { value.objective_measurable_count += 1; },
    ];
    for (const mutate of mutations) {
      const tampered = structuredClone(readiness);
      mutate(tampered);
      expect(metricEvidenceReadinessForPublication(tampered, publication)).toBeNull();
    }
  });

  it("keeps the contributor partition exact when a capable adapter has resolved nothing yet", () => {
    // Abstained with an available capability and an empty denominator: some
    // proof contributors are observed, the rest are not. The projection must
    // still name the missing ones, otherwise the guard withholds every row.
    const publication = syntheticMetricPublicationV2({
      "collaboration.clarification_yield": {
        value_state: "abstained",
        capability_available: true,
        source_complete: true,
        eligible: 0,
      },
    });
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const row = readiness.metrics.find((candidate) => candidate.metric_key === "collaboration.clarification_yield");
    expect(row?.availability_state).toBe("abstained");
    expect(row?.observed_contributors.length).toBeGreaterThan(0);
    expect([...(row?.observed_contributors ?? []), ...(row?.missing_contributors ?? [])].sort())
      .toEqual([...(row?.required_contributors ?? [])].sort());
    expect(row?.missing_contributors.length).toBeGreaterThan(0);
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);
  });

  it("binds the r3 open-loop row to explicit plan and supersession evidence", () => {
    const publication = structuredClone(syntheticMetricPublicationV2({
      "logic.open_loop_closure": {
        value_state: "pending",
        eligible: 2,
        pending: 1,
        numerator: 1,
      },
    }));
    publication.projection_version = "metric-contract-v2-projection-3";
    for (const metric of publication.metrics) {
      metric.state.projection_version = "metric-contract-v2-projection-3";
    }
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const openLoop = readiness.metrics.find((row) => row.metric_key === "logic.open_loop_closure");

    expect(openLoop?.required_contributors).toEqual([
      "documented_plan_message",
      "explicit_plan_supersession_link",
    ]);
    expect(openLoop?.availability_state).toBe("pending_right_censored");
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);

    const stale = structuredClone(readiness);
    const staleOpenLoop = stale.metrics.find((row) => row.metric_key === "logic.open_loop_closure");
    if (staleOpenLoop === undefined) throw new Error("synthetic open-loop row missing");
    staleOpenLoop.required_contributors = ["semantic_unit_heads", "agent_response_text"];
    expect(metricEvidenceReadinessForPublication(stale, publication)).toBeNull();
  });

  it("binds r4 lifecycle receipts, preserves the r3 open-loop overlay, and handles an authoritative empty family", () => {
    const publication = structuredClone(syntheticMetricPublicationV2({
      "collaboration.ambiguity_resolution": {
        value_state: "known", numerator: 1, denominator: 2,
      },
      "collaboration.clarification_yield": { value_state: "not_applicable", eligible: 0 },
      "logic.open_loop_closure": {
        value_state: "pending", eligible: 2, pending: 1, numerator: 1,
      },
    }));
    publication.projection_version = "metric-contract-v2-projection-4";
    for (const metric of publication.metrics) {
      metric.state.projection_version = "metric-contract-v2-projection-4";
    }
    const readiness = syntheticMetricEvidenceReadinessV2(publication);

    expect(readiness.catalog_version).toBe("metric-evidence-readiness-v2-5");
    expect(readiness.metrics.find((row) => row.metric_key === "collaboration.ambiguity_resolution")?.required_contributors)
      .toEqual([
        "confirmed_lifecycle_enumeration",
        "confirmed_lifecycle_opportunity",
        "confirmed_lifecycle_outcome_link",
      ]);
    expect(readiness.metrics.find((row) => row.metric_key === "collaboration.clarification_yield")?.required_contributors)
      .toEqual(["confirmed_lifecycle_enumeration"]);
    expect(readiness.metrics.find((row) => row.metric_key === "logic.open_loop_closure")?.required_contributors)
      .toEqual(["documented_plan_message", "explicit_plan_supersession_link"]);
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);

    const historical = structuredClone(readiness) as any;
    historical.catalog_version = "metric-evidence-readiness-v2-3";
    expect(metricEvidenceReadinessForPublication(historical, publication)).toEqual(historical);
    historical.catalog_version = "metric-evidence-readiness-v2-2";
    expect(metricEvidenceReadinessForPublication(historical, publication)).toBeNull();
  });

  it("binds current readiness v2-5 to r5 without rewriting r1-r4 history", () => {
    const publication = structuredClone(syntheticMetricPublicationV2({
      "prompt.constraint_precision": {
        value_state: "unknown",
        capability_available: true,
        source_complete: true,
        eligible: 0,
      },
      "collaboration.clarification_yield": {
        value_state: "not_applicable",
        capability_available: true,
        source_complete: true,
        eligible: 0,
      },
    }));
    publication.projection_version = "metric-contract-v2-projection-5";
    for (const metric of publication.metrics) {
      metric.state.projection_version = "metric-contract-v2-projection-5";
    }
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const profile = readiness.metrics.find((row) => row.metric_key === "prompt.constraint_precision");
    const lifecycle = readiness.metrics.find((row) => row.metric_key === "collaboration.clarification_yield");

    expect(readiness.catalog_version).toBe("metric-evidence-readiness-v2-5");
    expect(profile?.reason_code).toBe("declared_profile_slots_absent");
    expect(profile?.observed_contributors).toEqual([]);
    expect(profile?.missing_contributors).toEqual(["declared_task_profile", "canonical_request_text"]);
    expect(lifecycle?.required_contributors).toEqual(["confirmed_lifecycle_enumeration"]);
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);

    const staleCatalog = structuredClone(readiness) as any;
    staleCatalog.catalog_version = "metric-evidence-readiness-v2-4";
    expect(metricEvidenceReadinessForPublication(staleCatalog, publication)).toEqual(staleCatalog);
    staleCatalog.catalog_version = "metric-evidence-readiness-v2-3";
    expect(metricEvidenceReadinessForPublication(staleCatalog, publication)).toBeNull();
  });

  it("binds r6 decomposition readiness to reviewed requirement-plan evidence only", () => {
    const publication = publicationFor("metric-contract-v2-projection-6", {
      "logic.decomposition_coverage": {
        value_state: "known",
        numerator: 2,
        denominator: 3,
        explanation_code: "reviewed_requirement_plan_links",
      },
    });
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const decomposition = readiness.metrics.find(
      (row) => row.metric_key === "logic.decomposition_coverage",
    );
    expect(readiness.catalog_version).toBe("metric-evidence-readiness-v2-5");
    expect(decomposition).toMatchObject({
      availability_state: "measured",
      reason_code: "measured_from_owned_opportunities",
      required_contributors: [
        "reviewed_requirement_enumeration",
        "reviewed_requirement_plan_disposition",
      ],
      observed_contributors: [
        "reviewed_requirement_enumeration",
        "reviewed_requirement_plan_disposition",
      ],
    });
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);
    const stale = structuredClone(readiness) as any;
    stale.catalog_version = "metric-evidence-readiness-v2-4";
    expect(metricEvidenceReadinessForPublication(stale, publication)).toBeNull();

    const invalidPublication = publicationFor("metric-contract-v2-projection-6", {
      "logic.decomposition_coverage": {
        value_state: "unknown",
        capability_available: true,
        source_complete: false,
        eligible: 0,
        explanation_code: "requirement_plan_evidence_invalid",
      },
    });
    expectReasonBound(
      invalidPublication,
      "logic.decomposition_coverage",
      "reviewed_requirement_plan_binding_invalid",
    );

    const awaitingReview = publicationFor("metric-contract-v2-projection-6", {
      "logic.decomposition_coverage": {
        value_state: "unknown",
        capability_available: true,
        source_complete: true,
        eligible: 0,
        explanation_code: "requirement_plan_evidence_confirmation_required",
      },
    });
    expectReasonBound(
      awaitingReview,
      "logic.decomposition_coverage",
      "reviewed_requirement_plan_confirmation_required",
    );
    const awaitingReadiness = syntheticMetricEvidenceReadinessV2(awaitingReview).metrics.find(
      (row) => row.metric_key === "logic.decomposition_coverage",
    );
    expect(awaitingReadiness?.observed_contributors).toEqual([]);
    expect(awaitingReadiness?.missing_contributors).toEqual([
      "reviewed_requirement_enumeration",
      "reviewed_requirement_plan_disposition",
    ]);

    const emptyReviewedEnumeration = publicationFor("metric-contract-v2-projection-6", {
      "logic.decomposition_coverage": {
        value_state: "not_applicable",
        capability_available: true,
        source_complete: true,
        eligible: 0,
        explanation_code: "no_opportunity_observed",
      },
    });
    const emptyReadiness = syntheticMetricEvidenceReadinessV2(
      emptyReviewedEnumeration,
    ).metrics.find((row) => row.metric_key === "logic.decomposition_coverage");
    expect(emptyReadiness).toMatchObject({
      availability_state: "no_opportunity",
      reason_code: "no_eligible_opportunity_observed",
      required_contributors: ["reviewed_requirement_enumeration"],
      observed_contributors: ["reviewed_requirement_enumeration"],
      missing_contributors: [],
    });
    expect(metricEvidenceReadinessForPublication(
      syntheticMetricEvidenceReadinessV2(emptyReviewedEnumeration),
      emptyReviewedEnumeration,
    )).not.toBeNull();
  });

  it("binds r7 action traceability only to a complete reviewed requirement-action graph", () => {
    const publication = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "known",
        numerator: 2,
        denominator: 3,
        explanation_code: "reviewed_requirement_plan_links",
      },
      "logic.requirement_action_traceability": {
        value_state: "known",
        numerator: 2,
        denominator: 3,
        explanation_code: "reviewed_requirement_action_links",
      },
    });
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const action = readiness.metrics.find(
      (row) => row.metric_key === "logic.requirement_action_traceability",
    );

    expect(readiness.catalog_version).toBe("metric-evidence-readiness-v2-6");
    expect(action).toMatchObject({
      availability_state: "measured",
      reason_code: "measured_from_owned_opportunities",
      required_contributors: [
        "reviewed_requirement_enumeration",
        "reviewed_requirement_action_link",
        "safe_action_candidate_enumeration",
      ],
      observed_contributors: [
        "reviewed_requirement_enumeration",
        "reviewed_requirement_action_link",
        "safe_action_candidate_enumeration",
      ],
      missing_contributors: [],
    });
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);

    const staleCatalog = structuredClone(readiness) as any;
    staleCatalog.catalog_version = "metric-evidence-readiness-v2-5";
    expect(metricEvidenceReadinessForPublication(staleCatalog, publication)).toBeNull();
  });

  it("keeps every unresolved r7 action authority fail-closed and reason-bound", () => {
    for (const [explanationCode, scenario, reason] of [
      [
        "requirement_action_evidence_unavailable",
        { capability_available: false, source_complete: true, eligible: 2, unknown: 2 },
        "reviewed_requirement_action_service_required",
      ],
      [
        "requirement_action_evidence_confirmation_required",
        { capability_available: true, source_complete: true, eligible: 2, unknown: 2 },
        "reviewed_requirement_action_confirmation_required",
      ],
      [
        "requirement_action_evidence_invalid",
        { capability_available: true, source_complete: false, eligible: 2, unknown: 2 },
        "reviewed_requirement_action_binding_invalid",
      ],
      [
        "requirement_action_evidence_overflow",
        { capability_available: true, source_complete: true, eligible: 2, unknown: 2 },
        "opportunity_set_exceeds_receipt_bound",
      ],
      [
        "requirement_action_candidate_source_incomplete",
        { capability_available: true, source_complete: false, eligible: 2, unknown: 2 },
        "requirement_action_adapter_capabilities_required",
      ],
    ] as const) {
      const publication = publicationFor("metric-contract-v2-projection-7", {
        "logic.decomposition_coverage": {
          value_state: "known" as const, numerator: 1, denominator: 2,
          explanation_code: "reviewed_requirement_plan_links",
        },
        "logic.requirement_action_traceability": {
          value_state: "unknown",
          explanation_code: explanationCode,
          ...scenario,
        },
      });
      expectReasonBound(publication, "logic.requirement_action_traceability", reason);

      const pendingPlanPublication = publicationFor("metric-contract-v2-projection-7", {
        "logic.decomposition_coverage": {
          value_state: "pending", capability_available: true, source_complete: true,
          eligible: 2, numerator: 1, pending: 1,
          explanation_code: "opportunity_right_censored",
        },
        "logic.requirement_action_traceability": {
          value_state: "unknown",
          explanation_code: explanationCode,
          ...scenario,
        },
      });
      expectReasonBound(
        pendingPlanPublication,
        "logic.requirement_action_traceability",
        reason,
      );

      const denominatorDrift = publicationFor("metric-contract-v2-projection-7", {
        "logic.decomposition_coverage": {
          value_state: "known", numerator: 1, denominator: 2,
          explanation_code: "reviewed_requirement_plan_links",
        },
        "logic.requirement_action_traceability": {
          value_state: "unknown",
          explanation_code: explanationCode,
          ...scenario,
          eligible: 1,
          unknown: 1,
        },
      });
      expect(metricEvidenceReadinessForPublication(
        syntheticMetricEvidenceReadinessV2(denominatorDrift),
        denominatorDrift,
      )).toBeNull();
    }

    const reviewedDenominatorDrift = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "known", numerator: 1, denominator: 2,
        explanation_code: "reviewed_requirement_plan_links",
      },
      "logic.requirement_action_traceability": {
        value_state: "known", numerator: 1, denominator: 1,
        explanation_code: "reviewed_requirement_action_links",
      },
    });
    expect(metricEvidenceReadinessForPublication(
      syntheticMetricEvidenceReadinessV2(reviewedDenominatorDrift),
      reviewedDenominatorDrift,
    )).toBeNull();

    const emptyOverflow = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "not_applicable", capability_available: true, source_complete: true,
        eligible: 0, explanation_code: "no_opportunity_observed",
      },
      "logic.requirement_action_traceability": {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_overflow",
      },
    });
    expectReasonBound(
      emptyOverflow,
      "logic.requirement_action_traceability",
      "opportunity_set_exceeds_receipt_bound",
    );

    for (const planScenario of [
      {
        value_state: "unknown" as const, capability_available: false, source_complete: true,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_unavailable",
      },
      {
        value_state: "unknown" as const, capability_available: true, source_complete: true,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_confirmation_required",
      },
      {
        value_state: "unknown" as const, capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
      },
    ]) {
      const overflowBeforePlanAuthority = publicationFor("metric-contract-v2-projection-7", {
        "logic.decomposition_coverage": planScenario,
        "logic.requirement_action_traceability": {
          value_state: "unknown", capability_available: true, source_complete: true,
          eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_overflow",
        },
      });
      expectReasonBound(
        overflowBeforePlanAuthority,
        "logic.requirement_action_traceability",
        "opportunity_set_exceeds_receipt_bound",
      );
    }

    const emptyUnavailable = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "not_applicable", capability_available: true, source_complete: true,
        eligible: 0, explanation_code: "no_opportunity_observed",
      },
      "logic.requirement_action_traceability": {
        value_state: "unknown", capability_available: false, source_complete: true,
        eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_unavailable",
      },
    });
    expectReasonBound(
      emptyUnavailable,
      "logic.requirement_action_traceability",
      "reviewed_requirement_action_service_required",
    );

    const reviewedPending = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "pending", capability_available: true, source_complete: true,
        eligible: 2, numerator: 1, pending: 1,
        explanation_code: "opportunity_right_censored",
      },
      "logic.requirement_action_traceability": {
        value_state: "pending", capability_available: true, source_complete: true,
        eligible: 2, numerator: 1, pending: 1,
        explanation_code: "opportunity_right_censored",
      },
    });
    expectReasonBound(
      reviewedPending,
      "logic.requirement_action_traceability",
      "opportunity_right_censored",
    );

    const reviewedEmpty = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "not_applicable", capability_available: true, source_complete: true,
        eligible: 0, explanation_code: "no_opportunity_observed",
      },
      "logic.requirement_action_traceability": {
        value_state: "not_applicable", capability_available: true, source_complete: true,
        eligible: 0, explanation_code: "no_opportunity_observed",
      },
    });
    expectReasonBound(
      reviewedEmpty,
      "logic.requirement_action_traceability",
      "no_eligible_opportunity_observed",
    );
    const reviewedEmptyWithInvalidPlan = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
      },
      "logic.requirement_action_traceability": {
        value_state: "not_applicable", capability_available: true, source_complete: true,
        eligible: 0, explanation_code: "no_opportunity_observed",
      },
    });
    expect(metricEvidenceReadinessForPublication(
      syntheticMetricEvidenceReadinessV2(reviewedEmptyWithInvalidPlan),
      reviewedEmptyWithInvalidPlan,
    )).toBeNull();

    const invalidPlan = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
      },
      "logic.requirement_action_traceability": {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_invalid",
      },
    });
    expectReasonBound(
      invalidPlan,
      "logic.requirement_action_traceability",
      "reviewed_requirement_action_binding_invalid",
    );
    const invalidPlanWithInventedDenominator = publicationFor("metric-contract-v2-projection-7", {
      "logic.decomposition_coverage": {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
      },
      "logic.requirement_action_traceability": {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 1, unknown: 1, explanation_code: "requirement_action_evidence_invalid",
      },
    });
    expect(metricEvidenceReadinessForPublication(
      syntheticMetricEvidenceReadinessV2(invalidPlanWithInventedDenominator),
      invalidPlanWithInventedDenominator,
    )).toBeNull();

    for (const invalidScenario of [
      { eligible: 2, unknown: 1, pending: 1 },
      { eligible: 0, unknown: 0, pending: 0, met: 0, notMet: 0 },
    ]) {
      const invalid = publicationFor("metric-contract-v2-projection-7", {
        "logic.decomposition_coverage": invalidScenario.eligible === 0 ? {
          value_state: "not_applicable", capability_available: true, source_complete: true,
          eligible: 0, explanation_code: "no_opportunity_observed",
        } : {
          value_state: "known", numerator: 1, denominator: 2,
          explanation_code: "reviewed_requirement_plan_links",
        },
        "logic.requirement_action_traceability": {
          value_state: "unknown", capability_available: true, source_complete: true,
          explanation_code: "requirement_action_evidence_overflow",
          ...invalidScenario,
        },
      });
      const readiness = syntheticMetricEvidenceReadinessV2(invalid);
      if (invalidScenario.eligible === 0) {
        const state = invalid.metrics.find(
          (item) => item.state.metric_key === "logic.requirement_action_traceability",
        )!.state;
        state.statistics.unknown_count = 1;
      }
      expect(metricEvidenceReadinessForPublication(readiness, invalid)).toBeNull();
    }
  });

  it("binds readiness v2-7 to the closed r8 verified-requirement truth table", () => {
    const cases = [
      {
        label: "unavailable authority",
        scenario: {
          value_state: "unknown",
          capability_available: false,
          source_complete: true,
          eligible: 0,
          unknown: 0,
          explanation_code: "reviewed_requirement_authority_unavailable",
          distinct_owner_count: 0,
        },
        expected: {
          availability_state: "capability_missing",
          reason_code: "requirement_verification_adapter_capabilities_required",
          eligible_count: 0,
          met_count: 0,
          not_met_count: 0,
          unknown_count: 0,
          resolved_count: 0,
          censoring_lower_bound: null,
          censoring_upper_bound: null,
          observed_contributors: [],
          missing_contributors: [
            "declared_objective_opportunity_set",
            "typed_verification_receipt",
          ],
        },
      },
      {
        label: "awaiting evidence",
        scenario: {
          value_state: "unknown",
          capability_available: true,
          source_complete: true,
          eligible: 2,
          unknown: 2,
          explanation_code: "requirement_verification_evidence_unavailable",
          censoring_lower_bound: 0,
          censoring_upper_bound: 1,
          distinct_owner_count: 2,
        },
        expected: {
          availability_state: "evidence_unresolved",
          reason_code: "opportunity_classification_unresolved",
          eligible_count: 2,
          met_count: 0,
          not_met_count: 0,
          unknown_count: 2,
          resolved_count: 0,
          censoring_lower_bound: 0,
          censoring_upper_bound: 1,
          observed_contributors: ["declared_objective_opportunity_set"],
          missing_contributors: ["typed_verification_receipt"],
        },
      },
      {
        label: "partially resolved persisted evidence",
        scenario: {
          value_state: "unknown",
          capability_available: true,
          source_complete: true,
          eligible: 3,
          met: 1,
          not_met: 1,
          unknown: 1,
          explanation_code: "app_issued_requirement_verification_pending",
          censoring_lower_bound: 1 / 3,
          censoring_upper_bound: 2 / 3,
          distinct_owner_count: 3,
        },
        expected: {
          availability_state: "evidence_unresolved",
          reason_code: "opportunity_classification_unresolved",
          eligible_count: 3,
          met_count: 1,
          not_met_count: 1,
          unknown_count: 1,
          resolved_count: 2,
          censoring_lower_bound: 1 / 3,
          censoring_upper_bound: 2 / 3,
          observed_contributors: ["declared_objective_opportunity_set"],
          missing_contributors: ["typed_verification_receipt"],
        },
      },
      {
        label: "fully resolved persisted evidence",
        scenario: {
          value_state: "known",
          numerator: 2,
          denominator: 3,
          capability_available: true,
          source_complete: true,
          explanation_code: "app_issued_verified_requirement_coverage",
          distinct_owner_count: 3,
        },
        expected: {
          availability_state: "measured",
          reason_code: "measured_from_owned_opportunities",
          eligible_count: 3,
          met_count: 2,
          not_met_count: 1,
          unknown_count: 0,
          resolved_count: 3,
          censoring_lower_bound: 2 / 3,
          censoring_upper_bound: 2 / 3,
          observed_contributors: ["declared_objective_opportunity_set"],
          missing_contributors: ["typed_verification_receipt"],
        },
      },
    ] as const satisfies readonly {
      label: string;
      scenario: MetricScenarioV2;
      expected: Record<string, unknown>;
    }[];

    for (const { label, scenario, expected } of cases) {
      const publication = publicationFor("metric-contract-v2-projection-8", {
        "outcome.verified_requirement_coverage": scenario,
      });
      const readiness = syntheticMetricEvidenceReadinessV2(publication);
      const verified = readiness.metrics.find(
        (row) => row.metric_key === "outcome.verified_requirement_coverage",
      );

      expect(readiness.catalog_version, label).toBe("metric-evidence-readiness-v2-7");
      expect(verified, label).toMatchObject({
        required_contributors: [
          "declared_objective_opportunity_set",
          "typed_verification_receipt",
        ],
        ...expected,
      });
      expect(verified?.observed_contributors, label).not.toContain(
        "typed_verification_receipt",
      );
      expect(metricEvidenceReadinessForPublication(readiness, publication), label)
        .toEqual(readiness);

      const staleCatalog = structuredClone(readiness) as any;
      staleCatalog.catalog_version = "metric-evidence-readiness-v2-6";
      expect(metricEvidenceReadinessForPublication(staleCatalog, publication), label)
        .toBeNull();
    }
  });

  it.each([
    "metric-contract-v2-projection-1",
    "metric-contract-v2-projection-2",
    "metric-contract-v2-projection-3",
    "metric-contract-v2-projection-4",
  ] as const)("keeps historical %s publications readable under the current catalog", (projectionVersion) => {
    const publication = structuredClone(syntheticMetricPublicationV2());
    publication.projection_version = projectionVersion;
    for (const metric of publication.metrics) metric.state.projection_version = projectionVersion;
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    expect(metricEvidenceReadinessForPublication(readiness, publication)).toEqual(readiness);
  });

  it("binds every capability-missing reason to its exact metric and projection overlay", () => {
    const baseReasons = {
      "prompt.task_definition_coverage": "focus_owned_request_revision_required",
      "prompt.problem_evidence_quality": "focus_owned_request_revision_required",
      "prompt.context_sufficiency": "focus_owned_request_revision_required",
      "prompt.constraint_precision": "owned_canonical_request_text_required",
      "prompt.acceptance_testability": "owned_canonical_request_text_required",
      "prompt.deliverable_contract": "owned_canonical_request_text_required",
      "collaboration.ambiguity_resolution": "ambiguity_episode_extraction_required",
      "collaboration.clarification_yield": "clarification_episode_extraction_required",
      "collaboration.exploration_conversion": "hypothesis_episode_extraction_required",
      "collaboration.scope_change_discipline": "scope_change_episode_extraction_required",
      "collaboration.rework_candidate_rate": "feedback_unit_extraction_required",
      "logic.decomposition_coverage": "requirement_unit_extraction_required",
      "logic.hypothesis_test_linkage": "hypothesis_chain_adapter_capabilities_required",
      "logic.decision_rationale_coverage": "decision_unit_extraction_required",
      "logic.requirement_action_traceability": "requirement_action_adapter_capabilities_required",
      "logic.open_loop_closure": "open_loop_episode_extraction_required",
      "outcome.agent_claim_grounding": "material_claim_verification_adapter_capabilities_required",
      "outcome.verification_strategy_adequacy": "request_revision_unit_extraction_required",
      "outcome.first_pass_verification": "verification_task_outcome_adapter_capabilities_required",
      "outcome.verified_requirement_coverage": "requirement_verification_adapter_capabilities_required",
    } as const;
    const r1 = publicationFor("metric-contract-v2-projection-1");
    for (const [metricKey, reason] of Object.entries(baseReasons)) {
      expectReasonBound(r1, metricKey as MetricKeyV2, reason);
    }

    const r3 = publicationFor("metric-contract-v2-projection-3");
    expectReasonBound(r3, "logic.open_loop_closure", "explicit_plan_episode_required");
    for (const projection of [
      "metric-contract-v2-projection-4",
      "metric-contract-v2-projection-5",
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ] as const) {
      const publication = publicationFor(projection);
      expectReasonBound(publication, "logic.open_loop_closure", "explicit_plan_episode_required");
      for (const metricKey of [
        "collaboration.ambiguity_resolution",
        "collaboration.clarification_yield",
        "collaboration.exploration_conversion",
        "collaboration.scope_change_discipline",
        "collaboration.rework_candidate_rate",
      ] as const) {
        expectReasonBound(publication, metricKey, "confirmed_lifecycle_service_required");
      }
      if (projection === "metric-contract-v2-projection-6") {
        expectReasonBound(
          publication,
          "logic.decomposition_coverage",
          "reviewed_requirement_plan_service_required",
        );
      }
      if (["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
        projection,
      )) {
        expectReasonBound(
          publication,
          "logic.requirement_action_traceability",
          "reviewed_requirement_action_service_required",
        );
        expectReasonBound(
          publication,
          "logic.decomposition_coverage",
          "reviewed_requirement_plan_service_required",
        );
      }
    }
  });

  it("rejects a reason-only mutation for every structural readiness branch", () => {
    const cases: Array<{
      publication: ReturnType<typeof syntheticMetricPublicationV2>;
      metricKey: MetricKeyV2;
      reason: string;
    }> = [
      {
        publication: publicationFor("metric-contract-v2-projection-6", {
          "logic.decomposition_coverage": {
            value_state: "unknown", capability_available: true, source_complete: false, eligible: 0,
          },
        }),
        metricKey: "logic.decomposition_coverage",
        reason: "reviewed_requirement_plan_binding_invalid",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-1", {
          "prompt.constraint_precision": { value_state: "known", numerator: 1, denominator: 2 },
        }),
        metricKey: "prompt.constraint_precision",
        reason: "measured_from_owned_opportunities",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-1", {
          "prompt.task_definition_coverage": { value_state: "known", numerator: 2, denominator: 3 },
        }),
        metricKey: "prompt.task_definition_coverage",
        reason: "measured_under_superseded_projection_identity",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-2", {
          "prompt.task_definition_coverage": { value_state: "known", numerator: 2, denominator: 3 },
        }),
        metricKey: "prompt.task_definition_coverage",
        reason: "measured_from_owned_opportunities",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "logic.open_loop_closure": { value_state: "pending", eligible: 2, pending: 1, numerator: 1 },
        }),
        metricKey: "logic.open_loop_closure",
        reason: "opportunity_right_censored",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-4", {
          "collaboration.clarification_yield": { value_state: "not_applicable", eligible: 0 },
        }),
        metricKey: "collaboration.clarification_yield",
        reason: "no_eligible_opportunity_observed",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "logic.hypothesis_test_linkage": {
            value_state: "unknown", capability_available: true, source_complete: true, eligible: 0,
          },
        }),
        metricKey: "logic.hypothesis_test_linkage",
        reason: "opportunity_set_exceeds_receipt_bound",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "logic.decomposition_coverage": {
            value_state: "unknown", capability_available: true, source_complete: false, eligible: 0,
          },
        }),
        metricKey: "logic.decomposition_coverage",
        reason: "source_reconciliation_incomplete",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-4", {
          "collaboration.ambiguity_resolution": {
            value_state: "unknown", capability_available: true, source_complete: false, eligible: 0,
          },
        }),
        metricKey: "collaboration.ambiguity_resolution",
        reason: "confirmed_lifecycle_enumeration_required",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-5", {
          "prompt.acceptance_testability": {
            value_state: "unknown", capability_available: true, source_complete: true, eligible: 0,
          },
        }),
        metricKey: "prompt.acceptance_testability",
        reason: "declared_profile_slots_absent",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "collaboration.ambiguity_resolution": {
            value_state: "unknown", capability_available: true, source_complete: true, eligible: 0,
          },
        }),
        metricKey: "collaboration.ambiguity_resolution",
        reason: "opportunity_set_undetermined",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "collaboration.ambiguity_resolution": {
            value_state: "unknown", capability_available: true, source_complete: true, eligible: 2, unknown: 1,
          },
        }),
        metricKey: "collaboration.ambiguity_resolution",
        reason: "opportunity_classification_unresolved",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "logic.decision_rationale_coverage": { value_state: "abstained" },
        }),
        metricKey: "logic.decision_rationale_coverage",
        reason: "calculator_abstained",
      },
      {
        publication: publicationFor("metric-contract-v2-projection-3", {
          "logic.decision_rationale_coverage": { value_state: "execution_error" },
        }),
        metricKey: "logic.decision_rationale_coverage",
        reason: "execution_error_reported",
      },
    ];
    for (const item of cases) {
      expectReasonBound(item.publication, item.metricKey, item.reason);
    }
  });

  it("treats absence as no additive detail, never as an empty measured projection", () => {
    const publication = syntheticMetricPublicationV2();
    expect(metricEvidenceReadinessForPublication(null, publication)).toBeNull();
    expect(metricEvidenceReadinessForPublication({}, publication)).toBeNull();
    expect(metricEvidenceReadinessForPublication(syntheticMetricEvidenceReadinessV2(publication), null)).toBeNull();
  });
});
