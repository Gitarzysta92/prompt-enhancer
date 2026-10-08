import { describe, expect, it } from "vitest";
import type {
  SessionAnalysisResult,
  SessionAnalysisRunResponse,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_QUALITY_RUN,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import {
  createAggregateQualityMetricProfile,
  createProjectAggregateQualityMetricProfile,
  createQualityMetricProfile,
  QUALITY_ANALYSIS_DEFINITIONS,
} from "./qualityProfile";

function response(): SessionAnalysisRunResponse {
  return structuredClone(SYNTHETIC_SESSION_QUALITY_RUN);
}

function result(
  detail: SessionAnalysisRunResponse,
  key: string,
): SessionAnalysisResult {
  const found = detail.results.find((item) => item.key === key);
  if (!found) throw new TypeError("Synthetic quality result is missing.");
  return found;
}

function coachingResponse(): SessionAnalysisRunResponse {
  const completedAt = "2042-06-07T12:00:01Z";
  return {
    run: {
      run_id: "1".repeat(64),
      session_id: SYNTHETIC_QUALITY_SESSION_ID,
      request_fingerprint: "2".repeat(64),
      input_fingerprint: "3".repeat(64),
      analysis_profile_key: "coaching_profile",
      analysis_profile_version: 1,
      metric_pack_key: "experimental.redacted-text.coaching",
      metric_pack_version: 3,
      data_tier: "redacted_content",
      consent_purpose: "text_analysis",
      consent_policy_version: "example-consent-1",
      provider: "synthetic",
      provider_version: "example-provider-1",
      adapter_version: "example-adapter-1",
      source_schema_version: "example-source-1",
      content_schema_version: "example-content-1",
      metric_engine_version: "coaching-rules-en-pl-2",
      redactor_version: "example-redactor-1",
      model_plan_fingerprint: "4".repeat(64),
      metric_scope_state: "exact",
      selected_metric_keys: QUALITY_ANALYSIS_DEFINITIONS.map(
        (definition) => definition.key,
      ).sort(),
      schema_version: 9,
      local_only: true,
      started_at: "2042-06-07T12:00:00Z",
      status: "completed",
      finished_at: completedAt,
      failure_code: null,
    },
    results: QUALITY_ANALYSIS_DEFINITIONS.map((definition, index) => {
      const objectiveAbstention = [
        "logic.hypothesis_test_linkage",
        "outcome.agent_claim_grounding",
        "outcome.first_pass_verification",
        "outcome.verified_requirement_coverage",
      ].includes(definition.key);
      return {
        key: definition.key,
        version: definition.version,
        dimension: definition.dimension,
        display_name: definition.label,
        description: "Fictional coaching result.",
        metric_schema_version: 2,
        value_state: objectiveAbstention ? "abstained" : "known",
        numeric_value: objectiveAbstention ? null : 1,
        unit: definition.unit,
        source: "deterministic",
        direction: definition.direction,
        applicability: "applicable",
        aggregation_method: "ratio_of_sums",
        fraction: objectiveAbstention ? null : { numerator: 1, denominator: 1 },
        observed_count: 4,
        eligible_count: 4,
        coverage: 1,
        confidence: null,
        evidence_data_tier: "redacted_content",
        evidence: [],
        signals: objectiveAbstention
          ? [{ code: `candidate.metric_${index}`, status: "unknown", count: null }]
          : [{ code: `candidate.metric_${index}`, status: "detected", count: 1 }],
        explanation_code: objectiveAbstention
          ? "objective_verification_stream_required"
          : "synthetic_candidate",
        error_code: null,
        algorithm_id: "rules.en-pl.coaching-observables",
        algorithm_version: "2",
        model_id: null,
        model_revision: null,
        model_license: null,
        tokenizer_id: null,
        prompt_version: null,
        rubric_version: "coaching-observables-rubric-2",
        computed_at: completedAt,
      } satisfies SessionAnalysisResult;
    }),
  };
}

describe("immutable quality profile adapter", () => {
  it("maps the exact twenty-metric coaching pack into two focused views", () => {
    const detail = coachingResponse();
    const prompt = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const logic = createQualityMetricProfile(
      "reasoning",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(prompt.latest.integrity).toBe("coherent");
    expect(logic.latest.integrity).toBe("coherent");
    expect(prompt.latest.metrics).toHaveLength(11);
    expect(logic.latest.metrics).toHaveLength(9);
    expect(prompt.analysisProfile).toEqual({
      state: "coaching",
      label: "Coaching profile v1",
    });
    expect(
      logic.latest.metrics.find(
        (metric) => metric.definition.key === "outcome.first_pass_verification",
      ),
    ).toMatchObject({ state: "abstained", ratio: null });
  });

  it("labels an older immutable coaching pack as stale instead of corrupted", () => {
    const detail = coachingResponse();
    detail.run.metric_pack_version = 1;

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("stale-pack");
    expect(profile.latest.metricPackVersion).toBe(1);
    expect(profile.latest.metrics.every((metric) => metric.ratio === null)).toBe(true);
    expect(profile.latest.metrics.every((metric) => metric.state === "unavailable")).toBe(true);
  });

  it("maps the exact ten-result DTO while discarding display, evidence, model and run identifiers", () => {
    const detail = response();
    const canary = "PRIVATE-DERIVED-FIELD-CANARY";
    detail.results.forEach((item) => {
      item.display_name = canary;
      item.description = canary;
      item.evidence = [{ message_id: "c".repeat(64), origin: "direct" }];
    });
    result(detail, "logic.requirement_action_traceability").model_id = canary;
    result(detail, "logic.requirement_action_traceability").model_revision = canary;
    result(detail, "logic.requirement_action_traceability").model_license = canary;
    result(detail, "logic.requirement_action_traceability").tokenizer_id = canary;

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    );

    expect(profile?.latest.integrity).toBe("coherent");
    expect(profile?.latest.metrics.map((item) => item.definition.key)).toEqual([
      "prompt.goal_definition",
      "prompt.constraint_resolution",
      "prompt.completion_evaluability",
      "prompt.deliverable_contract",
      "prompt.open_decision_load",
    ]);
    expect(JSON.stringify(profile)).not.toContain(canary);
    expect(JSON.stringify(profile)).not.toContain(detail.run.run_id);
    expect(JSON.stringify(profile)).not.toContain("c".repeat(64));
  });

  it("keeps the metric fraction separate from observation coverage", () => {
    const profile = createQualityMetricProfile(
      "prompt-quality",
      response(),
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const goal = profile.latest.metrics[0];

    expect(goal).toMatchObject({
      ratio: 1,
      fractionNumerator: 3,
      fractionDenominator: 3,
      observed: 8,
      eligible: 10,
      coverage: 0.8,
      state: "partial",
    });
  });

  it("does not call a complete deterministic receipt partial only because confidence is uncalibrated", () => {
    const detail = response();
    const goal = result(detail, "prompt.goal_definition");
    goal.observed_count = 10;
    goal.eligible_count = 10;
    goal.coverage = 1;
    goal.confidence = null;

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics[0].state).toBe("observed");
    expect(profile.latest.metrics[0].confidence).toBeNull();
  });

  it("accepts coherent per-result hybrid model provenance", () => {
    const profile = createQualityMetricProfile(
      "reasoning",
      response(),
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.map((item) => item.state)).toEqual([
      "partial",
      "unavailable",
      "unavailable",
      "partial",
      "abstained",
    ]);
  });

  it("keeps the Standard engineering v1 synthetic run semantically coherent", () => {
    const detail = response();

    expect(detail.run).toMatchObject({
      analysis_profile_key: "standard_engineering",
      analysis_profile_version: 1,
      schema_version: 9,
    });
    expect(detail.results.every((item) => item.applicability === "applicable")).toBe(
      true,
    );
    for (const key of [
      "prompt.constraint_resolution",
      "prompt.deliverable_contract",
    ]) {
      expect(result(detail, key)).toMatchObject({
        value_state: "abstained",
        numeric_value: null,
        fraction: null,
        explanation_code: "denominator_unknown",
      });
      expect(result(detail, key).signals).toEqual([
        expect.objectContaining({ status: "unknown", count: null }),
      ]);
    }
    expect(result(detail, "prompt.goal_definition").signals).toEqual([
      { code: "goal.action", status: "detected", count: 1 },
      { code: "goal.target", status: "detected", count: 1 },
      { code: "goal.outcome", status: "detected", count: 1 },
    ]);
    expect(result(detail, "logic.plan_state_accounting")).toMatchObject({
      applicability: "applicable",
      value_state: "unknown",
    });
  });

  it("accepts risk_ratio only for the two lower-is-better axes", () => {
    const wrongCapabilityUnit = response();
    result(wrongCapabilityUnit, "prompt.goal_definition").unit = "risk_ratio";
    expect(
      createQualityMetricProfile(
        "prompt-quality",
        wrongCapabilityUnit,
        SYNTHETIC_QUALITY_SESSION_ID,
      )?.latest.integrity,
    ).toBe("invalid-contract");

    const wrongRiskDirection = response();
    result(wrongRiskDirection, "logic.scoped_consistency_candidate_rate").direction =
      "higher_is_better";
    expect(
      createQualityMetricProfile(
        "reasoning",
        wrongRiskDirection,
        SYNTHETIC_QUALITY_SESSION_ID,
      )?.latest.integrity,
    ).toBe("invalid-contract");
  });

  it("fails closed on contradictory fractions, value states, coverage and model tuples", () => {
    const contradictions = [
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "prompt.goal_definition").numeric_value = 0.5;
      },
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "prompt.goal_definition").value_state = "abstained";
      },
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "prompt.goal_definition").coverage = 1;
      },
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "logic.requirement_action_traceability").model_license = null;
      },
    ];

    contradictions.forEach((mutate) => {
      const detail = response();
      mutate(detail);
      const profile = createQualityMetricProfile(
        "prompt-quality",
        detail,
        SYNTHETIC_QUALITY_SESSION_ID,
      )!;
      expect(profile.latest.integrity).toBe("invalid-contract");
      expect(profile.latest.metrics.every((item) => item.ratio === null)).toBe(true);
    });
  });

  it("fails closed on duplicate, malformed, or arithmetically contradictory score receipts", () => {
    const mutations = [
      (detail: SessionAnalysisRunResponse) => {
        const goal = result(detail, "prompt.goal_definition");
        goal.signals[1] = structuredClone(goal.signals[0]);
      },
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "prompt.goal_definition").signals[0].count = 0;
      },
      (detail: SessionAnalysisRunResponse) => {
        result(detail, "prompt.goal_definition").signals[0] = {
          code: "goal.action",
          status: "missing",
          count: 0,
        };
      },
    ];

    mutations.forEach((mutate) => {
      const detail = response();
      mutate(detail);
      expect(
        createQualityMetricProfile(
          "prompt-quality",
          detail,
          SYNTHETIC_QUALITY_SESSION_ID,
        )?.latest.integrity,
      ).toBe("invalid-contract");
    });
  });

  it("rejects missing, duplicate, extra and cross-session results", () => {
    const missing = response();
    missing.results.pop();
    expect(
      createQualityMetricProfile(
        "reasoning",
        missing,
        SYNTHETIC_QUALITY_SESSION_ID,
      )?.latest.integrity,
    ).toBe("invalid-contract");

    const duplicate = response();
    duplicate.results[9] = structuredClone(duplicate.results[0]);
    expect(
      createQualityMetricProfile(
        "prompt-quality",
        duplicate,
        SYNTHETIC_QUALITY_SESSION_ID,
      )?.latest.integrity,
    ).toBe("invalid-contract");

    expect(
      createQualityMetricProfile(
        "prompt-quality",
        response(),
        "f".repeat(64),
      )?.latest.integrity,
    ).toBe("invalid-contract");
  });

  it("keeps exact-scope omissions distinct from missing, failed, and zero", () => {
    const detail = coachingResponse();
    const selectedKey = "prompt.task_definition_coverage";
    detail.results = detail.results.filter((item) => item.key === selectedKey);
    detail.run.selected_metric_keys = [selectedKey];

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === selectedKey,
    )).toMatchObject({ state: "observed", ratio: 1, notSelectedRuns: 0 });
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.context_sufficiency",
    )).toMatchObject({
      state: "not-selected",
      ratio: null,
      errorCode: "metric-not-selected",
      notSelectedRuns: 1,
    });
  });

  it("keeps a legacy run with unknown scope coherent without inventing omissions", () => {
    const detail = coachingResponse();
    detail.run.metric_scope_state = "legacy_unknown";
    detail.run.selected_metric_keys = [];
    detail.results = [];

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.every((metric) =>
      metric.state === "unavailable" &&
      metric.errorCode === "metric-scope-unknown" &&
      metric.notSelectedRuns === 0
    )).toBe(true);
  });

  it("lets transport-era legacy versions reach the mapper but blocks a mixed-version metric snapshot", () => {
    const detail = response();
    detail.run.metric_scope_state = "legacy_unknown";
    detail.run.selected_metric_keys = [];
    detail.results = [
      detail.results[0],
      { ...detail.results[0], version: 2 },
    ];

    const profile = createQualityMetricProfile(
      "prompt-quality",
      detail,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    expect(profile.latest.integrity).toBe("invalid-contract");
    expect(profile.latest.metrics.every((metric) => metric.ratio === null)).toBe(true);
  });

  it("fails closed instead of throwing when JSON violates the generated runtime shape", () => {
    const malformed = response() as unknown as {
      run: SessionAnalysisRunResponse["run"];
      results: Array<Record<string, unknown>>;
    };
    malformed.results[0].evidence = null;

    expect(() =>
      createQualityMetricProfile(
        "prompt-quality",
        malformed as unknown as SessionAnalysisRunResponse,
        SYNTHETIC_QUALITY_SESSION_ID,
      ),
    ).not.toThrow();
    expect(
      createQualityMetricProfile(
        "prompt-quality",
        malformed as unknown as SessionAnalysisRunResponse,
        SYNTHETIC_QUALITY_SESSION_ID,
      )?.latest.integrity,
    ).toBe("invalid-contract");
  });

  it("rejects omitted or nullable required provenance without throwing", () => {
    const malformedResponses = [
      (() => {
        const detail = response() as unknown as Record<string, unknown>;
        (detail.run as Record<string, unknown>).adapter_version = null;
        return detail;
      })(),
      (() => {
        const detail = response() as unknown as Record<string, unknown>;
        delete ((detail.results as Array<Record<string, unknown>>)[0].algorithm_id);
        return detail;
      })(),
      (() => {
        const detail = response() as unknown as Record<string, unknown>;
        delete ((detail.results as Array<Record<string, unknown>>)[0].fraction);
        return detail;
      })(),
      (() => {
        const detail = response() as unknown as Record<string, unknown>;
        (detail.results as Array<Record<string, unknown>>)[0].computed_at = null;
        return detail;
      })(),
    ];

    malformedResponses.forEach((detail) => {
      expect(() =>
        createQualityMetricProfile(
          "prompt-quality",
          detail as unknown as SessionAnalysisRunResponse,
          SYNTHETIC_QUALITY_SESSION_ID,
        ),
      ).not.toThrow();
      expect(
        createQualityMetricProfile(
          "prompt-quality",
          detail as unknown as SessionAnalysisRunResponse,
          SYNTHETIC_QUALITY_SESSION_ID,
        )?.latest.integrity,
      ).toBe("invalid-contract");
    });
  });

  it("represents a 404/no-run state as unavailable rather than zero", () => {
    const profile = createQualityMetricProfile(
      "prompt-quality",
      null,
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;

    expect(profile.latest.integrity).toBe("unavailable");
    expect(profile.latest.metrics.every((item) => item.ratio === null)).toBe(true);
    expect(profile.initial.integrity).toBe("unavailable");
  });

  it("maps a server ratio-of-sums aggregate without retaining selected identifiers", async () => {
    const aggregate = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    const profile = createAggregateQualityMetricProfile(
      "prompt-quality",
      aggregate,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.scope).toEqual({
      selectedSessions: 1,
      completedRuns: 1,
      missingRuns: 0,
    });
    expect(profile.latest.metrics[0]).toMatchObject({
      ratio: 1,
      fractionNumerator: 3,
      fractionDenominator: 3,
      observed: 12,
      eligible: 12,
      state: "observed",
    });
    const serialized = JSON.stringify(profile);
    expect(serialized).not.toContain(SYNTHETIC_QUALITY_SESSION_ID);
    expect(serialized).not.toContain(SYNTHETIC_QUALITY_PROJECT_ID);
    expect(profile.latest.metrics[0]).not.toHaveProperty("evidence");
  });

  it("aggregates overlapping exact scopes without counting omissions as missing", async () => {
    const aggregate = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    aggregate.selected_session_count = 2;
    aggregate.completed_run_count = 2;
    aggregate.missing_run_count = 0;
    const alwaysSelected = "prompt.task_definition_coverage";
    for (const metric of aggregate.metrics) {
      metric.selected_session_count = 2;
      metric.completed_run_count = 2;
      metric.missing_run_count = 0;
      if (metric.metric_key !== alwaysSelected) {
        metric.not_selected_run_count = 1;
        continue;
      }
      metric.present_result_count = 2;
      metric.not_selected_run_count = 0;
      metric.state_counts = Object.fromEntries(
        Object.entries(metric.state_counts).map(([state, count]) => [state, count * 2]),
      ) as typeof metric.state_counts;
      metric.compatibility_cohorts[0].state_counts = {
        ...metric.state_counts,
      };
      metric.compatibility_cohorts[0].result_count = 2;
      if (metric.fraction_numerator != null) metric.fraction_numerator *= 2;
      if (metric.fraction_denominator != null) metric.fraction_denominator *= 2;
      metric.analyzable_observed_count! *= 2;
      metric.analyzable_eligible_count! *= 2;
      if (metric.compatibility_cohorts[0].fraction_numerator !== null) {
        metric.compatibility_cohorts[0].fraction_numerator! *= 2;
      }
      if (metric.compatibility_cohorts[0].fraction_denominator !== null) {
        metric.compatibility_cohorts[0].fraction_denominator! *= 2;
      }
      metric.compatibility_cohorts[0].analyzable_observed_count *= 2;
      metric.compatibility_cohorts[0].analyzable_eligible_count *= 2;
    }

    const profile = createAggregateQualityMetricProfile("prompt-quality", aggregate)!;
    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === alwaysSelected,
    )).toMatchObject({
      state: "observed",
      fractionNumerator: 6,
      fractionDenominator: 6,
      notSelectedRuns: 0,
    });
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.problem_evidence_quality",
    )).toMatchObject({
      state: "partial",
      ratio: 1,
      notSelectedRuns: 1,
    });
  });

  it("projects a pure exact-scope omission as not selected", async () => {
    const aggregate = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    const omitted = aggregate.metrics.find(
      (metric) => metric.metric_key === "prompt.task_definition_coverage",
    )!;
    omitted.compatibility_state = "no_results";
    omitted.aggregate_state = "unknown";
    omitted.not_selected_run_count = omitted.completed_run_count;
    omitted.present_result_count = 0;
    omitted.missing_result_count = 0;
    omitted.state_counts = {
      known: 0, unknown: 0, not_applicable: 0, abstained: 0, execution_error: 0,
    };
    omitted.compatibility_cohorts = [];
    omitted.fraction_numerator = null;
    omitted.fraction_denominator = null;
    omitted.numeric_value = null;
    omitted.analyzable_observed_count = null;
    omitted.analyzable_eligible_count = null;
    omitted.analyzable_coverage = null;

    const profile = createAggregateQualityMetricProfile("prompt-quality", aggregate)!;
    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.task_definition_coverage",
    )).toMatchObject({
      state: "not-selected",
      ratio: null,
      errorCode: "metric-not-selected",
      notSelectedRuns: 1,
    });
  });

  it("does not call a metric purely not selected when another selected session is missing", async () => {
    const aggregate = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    aggregate.selected_session_count = 2;
    aggregate.completed_run_count = 1;
    aggregate.missing_run_count = 1;
    aggregate.metrics.forEach((metric) => {
      metric.selected_session_count = 2;
      metric.completed_run_count = 1;
      metric.missing_run_count = 1;
    });
    const omitted = aggregate.metrics.find(
      (metric) => metric.metric_key === "prompt.task_definition_coverage",
    )!;
    omitted.compatibility_state = "no_results";
    omitted.aggregate_state = "unknown";
    omitted.not_selected_run_count = 1;
    omitted.present_result_count = 0;
    omitted.missing_result_count = 0;
    omitted.state_counts = {
      known: 0, unknown: 0, not_applicable: 0, abstained: 0, execution_error: 0,
    };
    omitted.compatibility_cohorts = [];
    omitted.fraction_numerator = null;
    omitted.fraction_denominator = null;
    omitted.numeric_value = null;
    omitted.analyzable_observed_count = null;
    omitted.analyzable_eligible_count = null;
    omitted.analyzable_coverage = null;

    const profile = createAggregateQualityMetricProfile("prompt-quality", aggregate)!;
    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.task_definition_coverage",
    )).toMatchObject({
      state: "unavailable",
      ratio: null,
      notSelectedRuns: 1,
    });
    expect(profile.latest.scope).toMatchObject({ missingRuns: 1 });
  });

  it("blocks aggregation across legacy unknown scopes without relabeling them as failed", async () => {
    const aggregate = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    aggregate.integrity_state = "incompatible";
    aggregate.metrics.forEach((metric) => {
      metric.unknown_scope_run_count = 1;
      metric.compatibility_state = "incompatible";
      metric.aggregate_state = "incompatible";
      metric.blocked_reason_codes = ["metric_scope_unknown", "metric_contract_mismatch"];
      metric.compatibility_cohorts[0].key.metric_scope_state = "legacy_unknown";
      metric.fraction_numerator = null;
      metric.fraction_denominator = null;
      metric.numeric_value = null;
      metric.analyzable_observed_count = null;
      metric.analyzable_eligible_count = null;
      metric.analyzable_coverage = null;
    });

    const profile = createAggregateQualityMetricProfile("prompt-quality", aggregate)!;
    expect(profile.latest.integrity).toBe("mixed-provenance");
    expect(profile.latest.metrics.every((metric) =>
      metric.state === "unavailable" &&
      metric.errorCode === "metric-scope-unknown" &&
      metric.unknownScopeRuns === 1 &&
      metric.ratio === null
    )).toBe(true);
  });

  it("keeps project-level unknown metric scope explicit and content-free", async () => {
    const response = await createSyntheticTransport().aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    const aggregate = response.session_quality;
    aggregate.integrity_state = "incompatible";
    aggregate.metrics.forEach((metric) => {
      metric.unknown_scope_run_count = 1;
      metric.compatibility_state = "incompatible";
      metric.aggregate_state = "incompatible";
      metric.blocked_reason_codes = ["metric_scope_unknown"];
      metric.fraction_numerator = null;
      metric.fraction_denominator = null;
      metric.numeric_value = null;
      metric.analyzable_observed_count = null;
      metric.analyzable_eligible_count = null;
      metric.analyzable_coverage = null;
    });

    const profile = createProjectAggregateQualityMetricProfile(
      "prompt-quality",
      aggregate,
    )!;
    expect(profile.latest.integrity).toBe("mixed-provenance");
    expect(profile.latest.metrics.every((metric) =>
      metric.errorCode === "metric-scope-unknown" &&
      metric.unknownScopeRuns === 1 &&
      metric.ratio === null
    )).toBe(true);
  });

  it("maps the identifier-free project aggregate without retaining compatibility receipts", async () => {
    const response = await createSyntheticTransport().aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    const profile = createProjectAggregateQualityMetricProfile(
      "prompt-quality",
      response.session_quality,
    )!;

    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.scope).toEqual({
      selectedSessions: 1,
      completedRuns: 1,
      missingRuns: 0,
    });
    expect(profile.latest.metrics).toHaveLength(11);
    const serialized = JSON.stringify(profile);
    expect(serialized).not.toContain("compatibility_fingerprint");
    expect(serialized).not.toContain("compatibility_cohorts");
    expect(serialized).not.toContain("provider_version");
  });

  it("keeps a measured project zero distinct from a project metric with no results", async () => {
    const response = await createSyntheticTransport().aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    const aggregate = structuredClone(response.session_quality);
    const measuredZero = aggregate.metrics.find(
      (metric) => metric.metric_key === "prompt.task_definition_coverage",
    )!;
    measuredZero.fraction_numerator = 0;
    measuredZero.fraction_denominator = 4;
    measuredZero.numeric_value = 0;
    measuredZero.compatibility_cohorts[0].fraction_numerator = 0;
    measuredZero.compatibility_cohorts[0].fraction_denominator = 4;
    measuredZero.compatibility_cohorts[0].numeric_value = 0;

    const unavailable = aggregate.metrics.find(
      (metric) => metric.metric_key === "prompt.context_sufficiency",
    )!;
    unavailable.compatibility_state = "no_results";
    unavailable.aggregate_state = "unknown";
    unavailable.present_result_count = 0;
    unavailable.missing_result_count = unavailable.completed_run_count;
    unavailable.state_counts = {
      known: 0,
      unknown: 0,
      not_applicable: 0,
      abstained: 0,
      execution_error: 0,
    };
    unavailable.compatibility_cohorts = [];
    unavailable.fraction_numerator = null;
    unavailable.fraction_denominator = null;
    unavailable.numeric_value = null;
    unavailable.analyzable_observed_count = null;
    unavailable.analyzable_eligible_count = null;
    unavailable.analyzable_coverage = null;

    const profile = createProjectAggregateQualityMetricProfile(
      "prompt-quality",
      aggregate,
    )!;
    expect(profile.latest.integrity).toBe("coherent");
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.task_definition_coverage",
    )).toMatchObject({ ratio: 0, state: "observed" });
    expect(profile.latest.metrics.find(
      (metric) => metric.definition.key === "prompt.context_sufficiency",
    )).toMatchObject({ ratio: null, state: "unavailable" });
  });

  it("fails closed on malformed public project cohorts and additive nested fields", async () => {
    const response = await createSyntheticTransport().aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    const malformed = [
      (() => {
        const aggregate = structuredClone(response.session_quality) as unknown as Record<string, unknown>;
        const metric = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        metric.private_label = "PRIVATE-PROJECT-AGGREGATE-CANARY";
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(response.session_quality) as unknown as Record<string, unknown>;
        const metric = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        delete metric.unknown_scope_run_count;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(response.session_quality) as unknown as Record<string, unknown>;
        const metric = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (metric.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        cohort.compatibility_fingerprint = "not-a-fingerprint";
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(response.session_quality) as unknown as Record<string, unknown>;
        const metric = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        metric.numeric_value = 0.125;
        return aggregate;
      })(),
    ];

    malformed.forEach((aggregate) => {
      expect(() => createProjectAggregateQualityMetricProfile(
        "prompt-quality",
        aggregate as never,
      )).not.toThrow();
      const profile = createProjectAggregateQualityMetricProfile(
        "prompt-quality",
        aggregate as never,
      )!;
      expect(profile.latest.integrity).toBe("invalid-contract");
      expect(JSON.stringify(profile)).not.toContain("PRIVATE-PROJECT-AGGREGATE-CANARY");
    });
  });

  it("preserves compatible project metrics beside a distinct incompatible metric", async () => {
    const response = await createSyntheticTransport().aggregateProjectQuality({
      project_ids: [SYNTHETIC_QUALITY_PROJECT_ID],
      selection_mode: "all_analyzed_work",
    });
    const aggregate = response.session_quality;
    aggregate.integrity_state = "incompatible";
    const blocked = aggregate.metrics[0];
    blocked.compatibility_state = "incompatible";
    blocked.aggregate_state = "incompatible";
    blocked.blocked_reason_codes = ["mixed_provenance"];
    blocked.fraction_numerator = null;
    blocked.fraction_denominator = null;
    blocked.numeric_value = null;
    blocked.analyzable_observed_count = null;
    blocked.analyzable_eligible_count = null;
    blocked.analyzable_coverage = null;

    const profile = createProjectAggregateQualityMetricProfile(
      "prompt-quality",
      aggregate,
    )!;
    expect(profile.latest.integrity).toBe("mixed-provenance");
    expect(profile.latest.metrics[0]).toMatchObject({
      state: "incompatible",
      ratio: null,
      errorCode: "incompatible-provenance",
    });
    expect(profile.latest.metrics[1]).toMatchObject({
      state: "observed",
      ratio: 0.75,
    });
  });

  it("fails closed for mixed or contradictory aggregate provenance", async () => {
    const source = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    const mixed = structuredClone(source);
    mixed.integrity_state = "incompatible";
    mixed.metrics[0].compatibility_state = "incompatible";
    mixed.metrics[0].aggregate_state = "incompatible";
    mixed.metrics[0].blocked_reason_codes = ["mixed_provenance"];
    mixed.metrics[0].numeric_value = null;
    mixed.metrics[0].fraction_numerator = null;
    mixed.metrics[0].fraction_denominator = null;
    mixed.metrics[0].analyzable_observed_count = null;
    mixed.metrics[0].analyzable_eligible_count = null;
    mixed.metrics[0].analyzable_coverage = null;
    const mixedProfile = createAggregateQualityMetricProfile(
      "prompt-quality",
      mixed,
    )!;
    expect(mixedProfile.latest.integrity).toBe("mixed-provenance");
    expect(mixedProfile.latest.metrics[0]).toMatchObject({
      state: "incompatible",
      ratio: null,
      errorCode: "incompatible-provenance",
    });
    expect(mixedProfile.latest.metrics[1]).toMatchObject({
      state: "observed",
      ratio: 1,
    });

    const contradictory = structuredClone(source);
    contradictory.metrics[0].numeric_value = 0.25;
    const invalid = createAggregateQualityMetricProfile(
      "prompt-quality",
      contradictory,
    )!;
    expect(invalid.latest.integrity).toBe("invalid-contract");
    expect(invalid.latest.metrics.every((metric) => metric.ratio === null)).toBe(
      true,
    );
  });

  it("fails closed without throwing on malformed aggregate JSON", async () => {
    const source = await createSyntheticTransport().aggregateSessionQuality({
      session_ids: [SYNTHETIC_QUALITY_SESSION_ID],
    });
    const malformedAggregates = [
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        delete aggregate.metrics;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        delete first.state_counts;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        delete first.not_selected_run_count;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        delete first.unknown_scope_run_count;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        first.unknown_scope_run_count = 2;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        delete (cohort.key as Record<string, unknown>).algorithm_id;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        delete (cohort.key as Record<string, unknown>).analysis_profile_key;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        delete (cohort.key as Record<string, unknown>).metric_scope_state;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        (cohort.key as Record<string, unknown>).analysis_profile_version = 0;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        cohort.analyzable_coverage = null;
        return aggregate;
      })(),
      (() => {
        const aggregate = structuredClone(source) as unknown as Record<string, unknown>;
        const first = (aggregate.metrics as Array<Record<string, unknown>>)[0];
        const cohort = (first.compatibility_cohorts as Array<Record<string, unknown>>)[0];
        cohort.numeric_value = "1";
        return aggregate;
      })(),
    ];

    malformedAggregates.forEach((aggregate) => {
      expect(() =>
        createAggregateQualityMetricProfile(
          "prompt-quality",
          aggregate as unknown as typeof source,
        ),
      ).not.toThrow();
      const profile = createAggregateQualityMetricProfile(
        "prompt-quality",
        aggregate as unknown as typeof source,
      )!;
      expect(profile.latest.integrity).toBe("invalid-contract");
      expect(profile.latest.metrics.every((metric) => metric.ratio === null)).toBe(
        true,
      );
    });
  });
});
