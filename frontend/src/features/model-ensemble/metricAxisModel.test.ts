import { describe, expect, it } from "vitest";
import type { ModelEnsembleRun } from "../../shared/api/contracts";
import {
  METRIC_V2_CONTRACT_IDENTITIES,
  parseMetricV2State,
} from "../../shared/api/metricPublicationV2Contract";
import * as axisModel from "./metricAxisModel";
import {
  isModelEnsembleTypedMetric,
  modelEnsembleAxisCoverage,
  modelEnsembleAxisEvidence,
  modelEnsembleAxisPlottedLabel,
  modelEnsembleAxisRawRateLabel,
  modelEnsembleCompletedSmallExperts,
  modelEnsembleKnowledgeEntries,
  modelEnsembleMetricPresentation,
  modelEnsembleMetricStateLabel,
  modelEnsembleMetricStateValue,
  modelEnsemblePrimaryMetrics,
  modelEnsembleRadarAxes,
  modelEnsembleRadarQualityValue,
  modelEnsembleReceiptsByKey,
} from "./metricAxisModel";
import { isDeepModelStage } from "./modelStages";
import * as radarModule from "./ModelEnsembleRadar";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import { syntheticPublishedMetricV2 } from "../../test/metricPublicationV2Fixture";

type EnsembleMetric = ModelEnsembleRun["metrics"][number];
type TypedMetric = ModelEnsembleRun["typed_metrics"][number];
type ProjectionVersion = NonNullable<ModelEnsembleRun["metric_publication_v2"]>["projection_version"];

function committeeMetric(overrides: Partial<EnsembleMetric> = {}): EnsembleMetric {
  return {
    metric_key: "prompt.task_definition_coverage",
    value_state: "known",
    numerator: 1,
    denominator: 2,
    numeric_value: 0.5,
    known_chunk_count: 2,
    abstained_chunk_count: 0,
    unsupported_chunk_count: 0,
    failed_chunk_count: 0,
    total_chunk_count: 4,
    explanation_code: "example_ratio_of_chunks",
    calibration_state: "not_assessed",
    product_metric_eligible: false,
    ...overrides,
  };
}

function typedMetric(overrides: Partial<TypedMetric> = {}): TypedMetric {
  return {
    metric_key: "prompt.task_definition_coverage",
    metric_version: 3,
    value_state: "known",
    numerator: 3,
    denominator: 4,
    numeric_value: 0.75,
    observed_message_count: 8,
    eligible_message_count: 10,
    coverage: 0.8,
    explanation_code: "typed_requirement_ratio",
    error_code: null,
    projection_source: "deterministic_typed_contract",
    metric_schema_version: 2,
    engine_version: "coaching-rules-en-pl-2",
    algorithm_id: "coaching-text-features",
    algorithm_version: "coaching-features-en-pl-2",
    rubric_version: "coaching-rubric-v3",
    calibration_state: "not_assessed",
    product_metric_eligible: false,
    ...overrides,
  };
}

function runWith(typed: readonly TypedMetric[], metrics: readonly EnsembleMetric[] = []): ModelEnsembleRun {
  return { typed_metrics: typed, metrics, chunk_metrics: [] } as unknown as ModelEnsembleRun;
}

function runWithV2(
  metricKey: string,
  valueState: "known" | "pending" | "unknown" = "unknown",
  capabilityAvailable = true,
  projectionVersion: ProjectionVersion = "metric-contract-v2-projection-1",
): ModelEnsembleRun {
  const known = valueState === "known";
  const pending = valueState === "pending";
  const identity = METRIC_V2_CONTRACT_IDENTITIES[metricKey as keyof typeof METRIC_V2_CONTRACT_IDENTITIES];
  if (identity === undefined) throw new Error("test V2 identity missing");
  const state = parseMetricV2State({
    metric_key: metricKey,
    registry_version: "all-20-factor-contracts-v2",
    contract_version: "probabilistic-metric-contract-v2",
    contract_fingerprint: identity.fingerprint,
    evidence_authority: identity.authority,
    value_state: valueState,
    explanation_code: pending ? "episode_horizon_open" : known ? "exact_fraction" : "opportunity_family_unobservable",
    numerator: known ? 1 : null,
    denominator: known ? 2 : null,
    numeric_value: known ? 0.5 : null,
    censoring_lower_bound: known ? 0.5 : pending ? 0 : null,
    censoring_upper_bound: known ? 0.5 : pending ? 1 : null,
    statistics: {
      metric_key: metricKey,
      denominator_basis: identity.basis,
      opportunity_unit_kind: identity.unit,
      capability_available: capabilityAvailable,
      source_complete: known || pending,
      eligible_count: known ? 2 : pending ? 1 : 0,
      met_count: known ? 1 : 0,
      not_met_count: known ? 1 : 0,
      pending_count: pending ? 1 : 0,
      unknown_count: 0,
      superseded_excluded_count: 0,
      distinct_owner_count: identity.basis === "semantic_unit_opportunities" ? (known ? 2 : pending ? 1 : 0) : 0,
    },
    projection_version: projectionVersion,
    product_metric_eligible: false,
  }, metricKey);
  return {
    typed_metrics: [typedMetric({ metric_key: metricKey, numeric_value: 1 })],
    metrics: [committeeMetric({ metric_key: metricKey, numeric_value: 1 })],
    chunk_metrics: [],
    metric_publication_v2: null,
    metric_profile_binding: null,
    metric_states_v2: [state],
  } as unknown as ModelEnsembleRun;
}

describe("metricAxisModel axis tile helpers", () => {
  const rework = "collaboration.rework_candidate_rate";
  const collaborationRun = runWith([
    typedMetric({ metric_key: rework, numerator: 2, denominator: 100, numeric_value: 0.02 }),
    typedMetric({ metric_key: "collaboration.ambiguity_resolution", numerator: 1, denominator: 4, numeric_value: 0.25 }),
    typedMetric({
      metric_key: "collaboration.clarification_yield",
      value_state: "unknown",
      numerator: null,
      denominator: null,
      numeric_value: null,
      explanation_code: "episode_horizon_open",
    }),
    typedMetric({
      metric_key: "collaboration.exploration_conversion",
      value_state: "not_applicable",
      numerator: null,
      denominator: null,
      numeric_value: null,
      explanation_code: "message_kind_unobserved",
    }),
  ]);
  const axes = modelEnsembleRadarAxes(collaborationRun, "collaboration-flow");
  const byKey = (key: string) => axes.find((axis) => axis.key === key)!;

  it("labels lower-is-better values as radar quality while exposing the raw rate once", () => {
    const axis = byKey(rework);
    expect(axis.plotted).toBe(0.98);
    expect(modelEnsembleAxisPlottedLabel(axis)).toBe("98% radar quality");
    expect(modelEnsembleAxisRawRateLabel(axis)).toBe("raw rate 2%");
  });

  it("labels higher-is-better values as plain percentages without a raw-rate caption", () => {
    const axis = byKey("collaboration.ambiguity_resolution");
    expect(modelEnsembleAxisPlottedLabel(axis)).toBe("25%");
    expect(modelEnsembleAxisRawRateLabel(axis)).toBeNull();
  });

  it("keeps pending, N/A, and missing axes unplotted with explicit state values", () => {
    expect(byKey("collaboration.clarification_yield").plotted).toBeNull();
    expect(modelEnsembleAxisPlottedLabel(byKey("collaboration.clarification_yield"))).toBe("Pending");
    expect(modelEnsembleAxisPlottedLabel(byKey("collaboration.exploration_conversion"))).toBe("N/A");
    expect(modelEnsembleAxisPlottedLabel(byKey("collaboration.scope_change_discipline"))).toBe("No record");
    expect(modelEnsembleAxisRawRateLabel(byKey("collaboration.clarification_yield"))).toBeNull();
    expect(modelEnsembleMetricStateValue(null)).toBe("No record");
    expect(modelEnsembleMetricStateLabel(null)).toBe("not observed");
    expect(modelEnsembleMetricStateLabel(byKey("collaboration.clarification_yield").metric)).toBe("pending · horizon open");
    expect(modelEnsembleMetricStateLabel(byKey("collaboration.exploration_conversion").metric)).toBe("not applicable");
  });

  it("distinguishes compact objective evidence absence from an adapter capability gap", () => {
    const key = "logic.requirement_action_traceability";
    const axisFor = (capabilityAvailable: boolean) => modelEnsembleRadarAxes(
      runWithV2(key, "unknown", capabilityAvailable),
      "outcome-evidence",
    ).find((axis) => axis.key === key)!;
    const evidenceMissing = modelEnsembleMetricPresentation(axisFor(true).metric!, "higher_is_better");
    const capabilityMissing = modelEnsembleMetricPresentation(axisFor(false).metric!, "higher_is_better");
    expect(evidenceMissing.detail).toMatch(/^Objective evidence missing:/u);
    expect(evidenceMissing.detail).toMatch(/adapter exposes/u);
    expect(capabilityMissing.detail).toMatch(/^Adapter capability missing:/u);
    expect(capabilityMissing.detail).toMatch(/no user wording or agent action can fix/u);
    expect(capabilityMissing.detail).toMatch(/supported structured-evidence adapter.*confirmation workflow/u);
  });

  it("derives guidance evidence that never carries a numeric value for a non-known state", () => {
    expect(modelEnsembleAxisEvidence(byKey(rework))).toEqual({
      state: "known",
      numericValue: 0.02,
      numerator: 2,
      denominator: 100,
      explanationCode: "typed_requirement_ratio",
      evidenceAuthority: expect.any(String),
      suppressionReason: null,
      comparabilityState: null,
    });
    expect(modelEnsembleAxisEvidence(byKey("collaboration.clarification_yield"))).toEqual({
      state: "unknown",
      numericValue: null,
      numerator: null,
      denominator: null,
      explanationCode: "episode_horizon_open",
      evidenceAuthority: expect.any(String),
      suppressionReason: null,
      comparabilityState: null,
    });
    expect(modelEnsembleAxisEvidence(byKey("collaboration.scope_change_discipline"))).toEqual({
      state: "missing",
      numericValue: null,
      numerator: null,
      denominator: null,
      explanationCode: null,
      evidenceAuthority: expect.any(String),
      suppressionReason: null,
      comparabilityState: null,
    });
  });

  it("passes only typed explanation codes to guidance; committee codes stay diagnostics", () => {
    const committeeOnly = modelEnsembleRadarAxes(
      runWith([], [committeeMetric({ value_state: "abstained", numerator: null, denominator: null, numeric_value: null, known_chunk_count: 0, abstained_chunk_count: 4 })]),
      "task-framing",
    )[0];
    expect(isModelEnsembleTypedMetric(committeeOnly.metric!)).toBe(false);
    expect(modelEnsembleAxisEvidence(committeeOnly)).toEqual({
      state: "abstained",
      numericValue: null,
      numerator: null,
      denominator: null,
      explanationCode: null,
      evidenceAuthority: expect.any(String),
      suppressionReason: null,
      comparabilityState: null,
    });
  });

  it("reports typed source coverage or legacy eligible-observation coverage for the ring", () => {
    expect(modelEnsembleAxisCoverage(byKey(rework))).toBe(0.8);
    const legacy = modelEnsembleRadarAxes(runWith([], [committeeMetric()]), "task-framing")[0];
    expect(modelEnsembleAxisCoverage(legacy)).toBe(0.5);
    expect(modelEnsembleAxisCoverage(byKey("collaboration.scope_change_discipline"))).toBe(0);
    const emptyDenominator = modelEnsembleRadarAxes(
      runWith([], [committeeMetric({ value_state: "unknown", numerator: null, denominator: null, numeric_value: null, known_chunk_count: 0, unsupported_chunk_count: 0, total_chunk_count: 0 })]),
      "task-framing",
    )[0];
    expect(modelEnsembleAxisCoverage(emptyDenominator)).toBe(0);
  });

  it("builds knowledge entries whose status matches the state label of each axis", () => {
    const entries = modelEnsembleKnowledgeEntries(axes);
    expect(entries.map((entry) => entry.key)).toEqual(axes.map((axis) => axis.key));
    expect(entries.map((entry) => entry.status)).toEqual(axes.map((axis) => modelEnsembleMetricStateLabel(axis.metric)));
    expect(entries.find((entry) => entry.key === rework)?.status).toBe("known");
    expect(entries.find((entry) => entry.key === "collaboration.scope_change_discipline")?.status).toBe("not observed");
    const stateAware = entries.find((entry) => entry.key === "collaboration.scope_change_discipline")!;
    expect(stateAware.guidance.state).toBe("missing");
    expect(stateAware.guidance.evidenceAuthority).toMatch(/candidate|receipt|evidence/i);
    expect(stateAware.guidance.suppressionReason).toBeNull();
    expect(stateAware.guidance.comparabilityState).toBeNull();
  });

  it("derives scope, contributor, model, and evidence context facts that never turn absence into zero", () => {
    const entries = modelEnsembleKnowledgeEntries(axes);
    const measured = entries.find((entry) => entry.key === rework)!.context;
    expect(measured.scope).toBe("me");
    expect(measured.label).toBe("Me · this installation");
    expect(measured.contributors).toMatch(/One principal \(you\)/);
    expect(measured.model).toBeNull();
    expect(measured.evidence).toMatch(/^2\/100 resolved opportunities/);
    const missing = entries.find((entry) => entry.key === "collaboration.scope_change_discipline")!.context;
    expect(missing.evidence).toMatch(/not observed, not zero, not plotted/);
    expect(missing.evidence).not.toMatch(/\b0\/0\b|\b0%/);
    const notApplicable = entries.find((entry) => entry.key === "collaboration.exploration_conversion")!.context;
    expect(notApplicable.evidence).toMatch(/State “not applicable”/);
    expect(notApplicable.evidence).toMatch(/never drawn as zero/);
    const teamScoped = axisModel.modelEnsembleKnowledgeEntries(axes, {
      scope: "team",
      label: "Team · fixture cohort",
      description: "Aggregate over a consented cohort.",
    });
    expect(teamScoped[0].context.scope).toBe("team");
    expect(teamScoped[0].context.contributors).toBeNull();
    const withheld = axisModel.modelEnsembleAxisContextFacts({
      ...byKey(rework),
      prediction: { state: "experimental" } as unknown as NonNullable<ReturnType<typeof byKey>["prediction"]>,
      predictiveMedian: null,
      predictiveWithheldReason: axisModel.PREDICTIVE_WITHHELD_TOO_FEW_EXPERTS,
    });
    expect(withheld.model).toBe(`Model estimate withheld · ${axisModel.PREDICTIVE_WITHHELD_TOO_FEW_EXPERTS}`);
    const visible = axisModel.modelEnsembleAxisContextFacts({ ...byKey(rework), predictiveMedian: 0.42 });
    expect(visible.model).toMatch(/median 42%/);
    expect(visible.model).toMatch(/never merged/);
  });
});

describe("metricAxisModel receipt resolver", () => {
  const rework = "collaboration.rework_candidate_rate";
  const typedRework = typedMetric({ metric_key: rework, numerator: 1, denominator: 5, numeric_value: 0.2 });
  const committeeRework = committeeMetric({ metric_key: rework, numerator: 7, denominator: 10, numeric_value: 0.7 });

  it("reads only the typed projection when one exists and the committee shadow otherwise, never mixing per key", () => {
    const typedUnknown = typedMetric({ metric_key: rework, value_state: "unknown", numerator: null, denominator: null, numeric_value: null });
    expect(modelEnsemblePrimaryMetrics(runWith([typedUnknown], [committeeRework]))).toEqual([typedUnknown]);
    expect(modelEnsemblePrimaryMetrics(runWith([], [committeeRework]))).toEqual([committeeRework]);
    expect(modelEnsembleReceiptsByKey(runWith([typedUnknown], [committeeRework])).get(rework)).toBe(typedUnknown);
    expect(modelEnsembleReceiptsByKey(runWith([typedRework], [committeeRework])).get(rework)).toBe(typedRework);
    expect(modelEnsembleReceiptsByKey(runWith([], [committeeRework])).get(rework)).toBe(committeeRework);
    // A typed projection that omits the key leaves it unobserved rather than borrowing the committee receipt.
    expect(modelEnsembleReceiptsByKey(runWith([typedMetric()], [committeeRework])).get(rework)).toBeUndefined();
  });

  it("uses the canonical V2 state ahead of both legacy layers and keeps first-class pending unplotted", () => {
    const metricKey = "collaboration.ambiguity_resolution";
    const v2Pending = runWithV2(metricKey, "pending");
    const primary = modelEnsemblePrimaryMetrics(v2Pending);
    expect(primary).toHaveLength(1);
    expect(primary[0]).toMatchObject({
      metric_key: metricKey,
      value_state: "pending",
      numeric_value: null,
      projection_source: "metric_contract_v2_live",
      source_kind: "metric_v2",
    });
    const axis = modelEnsembleRadarAxes(v2Pending, "collaboration-flow")
      .find((candidate) => candidate.key === metricKey)!;
    expect(axis.plotted).toBeNull();
    expect(modelEnsembleAxisPlottedLabel(axis)).toBe("Pending");
    expect(modelEnsembleAxisEvidence(axis)).toEqual({
      state: "pending",
      numericValue: null,
      numerator: null,
      denominator: null,
      explanationCode: "episode_horizon_open",
      evidenceAuthority: "conversation",
      suppressionReason: null,
      comparabilityState: null,
    });
    expect(modelEnsembleKnowledgeEntries([axis])[0].guidance.evidenceAuthority).toBe("conversation");
  });

  it("keeps exact r8 unknown censoring bounds and partial verification authority in compact history", () => {
    const published = syntheticPublishedMetricV2(
      "outcome.verified_requirement_coverage",
      {
        value_state: "unknown", eligible: 4, unknown: 2,
        capability_available: true, source_complete: true,
        censoring_lower_bound: 0.25, censoring_upper_bound: 0.75,
        explanation_code: "app_issued_requirement_verification_pending",
      },
    );
    published.state.projection_version = "metric-contract-v2-projection-8";
    published.state.statistics.met_count = 1;
    published.state.statistics.not_met_count = 1;
    published.state.statistics.distinct_owner_count = 4;
    const state = parseMetricV2State(
      structuredClone(published.state),
      published.state.metric_key,
    );
    const run = {
      typed_metrics: [], metrics: [], chunk_metrics: [],
      metric_publication_v2: null, metric_profile_binding: null,
      metric_states_v2: [state],
    } as unknown as ModelEnsembleRun;
    const axis = modelEnsembleRadarAxes(run, "outcome-evidence").find(
      (candidate) => candidate.key === "outcome.verified_requirement_coverage",
    )!;

    expect(axisModel.modelEnsembleAxisPendingBoundsLabel(axis)).toBe("bounds 25%–75%");
    expect(modelEnsembleMetricPresentation(axis.metric!, axis.direction).detail)
      .toMatch(/exact right-censored interval is 25%–75%/i);
    const guidance = axisModel.modelEnsembleAxisGuidanceSentences(axis);
    expect(guidance.meaning).toMatch(/remainder right-censors/i);
    expect(guidance.meaning).toMatch(/lower bound of 25% and an upper bound of 75%/i);
    expect(guidance.meaning).toMatch(/native human acceptances/i);
    expect(guidance.meaning).not.toMatch(/typed receipt exists/i);
  });

  it("propagates the exact projection into compact guidance instead of relabeling r4 history as r5", () => {
    const key = "prompt.acceptance_testability";
    const axisFor = (projection: ProjectionVersion) => modelEnsembleRadarAxes(
      runWithV2(key, "known", true, projection),
      "task-framing",
    ).find((axis) => axis.key === key)!;
    const r4 = modelEnsembleKnowledgeEntries([axisFor("metric-contract-v2-projection-4")])[0];
    const r5 = modelEnsembleKnowledgeEntries([axisFor("metric-contract-v2-projection-5")])[0];
    const r6 = modelEnsembleKnowledgeEntries([axisFor("metric-contract-v2-projection-6")])[0];

    expect(r4.projectionVersion).toBe("metric-contract-v2-projection-4");
    expect(r4.guidance.meaning).toContain("one per detected requirement clause");
    expect(r4.guidance.meaning).toContain("versioned local contract");
    expect(r4.guidance.meaning).not.toContain("expected-outcome slot");
    expect(r5.projectionVersion).toBe("metric-contract-v2-projection-5");
    expect(r5.guidance.meaning).toContain("one per expected-outcome slot in the reviewed task profile");
    expect(r5.guidance.meaning).toContain("sealed r5 reviewed-profile contract");
    expect(r5.guidance.meaning).not.toContain("detected requirement clause");
    expect(r6.projectionVersion).toBe("metric-contract-v2-projection-6");
    expect(r6.guidance.meaning).toContain("one per expected-outcome slot in the reviewed task profile");
    expect(r6.guidance.meaning).toContain("sealed r6 reviewed-profile contract");
    expect(r6.guidance.meaning).not.toContain("detected requirement clause");
  });

  it("keeps compact r2/r3 and r3/r4 lifecycle boundaries exact", () => {
    const openLoop = (projection: ProjectionVersion) => {
      const axis = modelEnsembleRadarAxes(
        runWithV2("logic.open_loop_closure", "known", true, projection),
        "reasoning-trace",
      ).find((candidate) => candidate.key === "logic.open_loop_closure")!;
      return modelEnsembleKnowledgeEntries([axis])[0];
    };
    const collaboration = (projection: ProjectionVersion) => {
      const axis = modelEnsembleRadarAxes(
        runWithV2("collaboration.ambiguity_resolution", "known", true, projection),
        "collaboration-flow",
      ).find((candidate) => candidate.key === "collaboration.ambiguity_resolution")!;
      return modelEnsembleKnowledgeEntries([axis])[0];
    };

    expect(openLoop("metric-contract-v2-projection-2").guidance.meaning)
      .toContain("one per detected question");
    expect(openLoop("metric-contract-v2-projection-3").guidance.meaning)
      .toContain("one per documented agent PLAN episode");
    expect(openLoop("metric-contract-v2-projection-3").guidance.meaning)
      .toContain("sealed r3 explicit-plan lifecycle contract");
    expect(collaboration("metric-contract-v2-projection-3").guidance.meaning)
      .toContain("one per clause with an ambiguity marker");
    expect(collaboration("metric-contract-v2-projection-4").guidance.meaning)
      .toContain("one per confirmed enumerated ambiguity opportunity");
    expect(collaboration("metric-contract-v2-projection-4").guidance.meaning)
      .toContain("sealed r4 confirmed-lifecycle contract");
  });

  it("keeps authorized-but-unresolved objective history distinct from a missing capability", () => {
    const metricKey = "outcome.verified_requirement_coverage";
    const state = {
      metric_key: metricKey,
      value_state: "unknown",
      numerator: null,
      denominator: null,
      numeric_value: null,
      explanation_code: "typed_objective_evidence_unresolved",
      evidence_authority: "objective_receipt",
      statistics: {
        capability_available: true,
        eligible_count: 2,
        met_count: 1,
        not_met_count: 0,
        pending_count: 0,
        unknown_count: 1,
      },
    };
    const run = {
      typed_metrics: [],
      metrics: [committeeMetric({ metric_key: metricKey })],
      chunk_metrics: [],
      metric_states_v2: [state],
    } as unknown as ModelEnsembleRun;
    expect(modelEnsemblePrimaryMetrics(run)[0]).toMatchObject({
      metric_key: metricKey,
      implementation_state: "objective_evidence_unresolved",
      numeric_value: null,
    });
  });

  it("orients only known numeric receipts and keeps every other state null, never zero", () => {
    expect(modelEnsembleRadarQualityValue(typedRework, "lower_is_better")).toBeCloseTo(0.8);
    expect(modelEnsembleRadarQualityValue(typedRework, "higher_is_better")).toBeCloseTo(0.2);
    expect(modelEnsembleRadarQualityValue(committeeRework, "lower_is_better")).toBeCloseTo(0.3);
    for (const state of ["unknown", "not_applicable", "abstained", "execution_error"] as const) {
      const metric = typedMetric({ metric_key: rework, value_state: state, numerator: null, denominator: null, numeric_value: null });
      expect(modelEnsembleRadarQualityValue(metric, "lower_is_better"), state).toBeNull();
    }
    expect(modelEnsembleRadarQualityValue(typedMetric({ numeric_value: null }), "higher_is_better")).toBeNull();
    expect(modelEnsembleRadarQualityValue(null, "lower_is_better")).toBeNull();
    expect(modelEnsembleRadarQualityValue(undefined, "higher_is_better")).toBeNull();
    // The axes use the same resolver: a typed unknown beside a known committee receipt stays unplotted.
    const axis = modelEnsembleRadarAxes(
      runWith([typedMetric({ metric_key: rework, value_state: "unknown", numerator: null, denominator: null, numeric_value: null })], [committeeRework]),
      "collaboration-flow",
    ).find((candidate) => candidate.key === rework)!;
    expect(axis.plotted).toBeNull();
    expect(axis.metric?.value_state).toBe("unknown");
  });
});

describe("metricAxisModel small-expert gate", () => {
  it("uses the single deep-model predicate shared with the stage drawer", () => {
    const stage = (modelKey: string, repositoryId: string, status: "completed" | "failed" = "completed") => ({
      model_key: modelKey,
      repository_id: repositoryId,
      revision: "f".repeat(40),
      status,
      error_code: null,
      device: "cpu" as const,
      quantization: "none" as const,
      inference_latency_ms: 10,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 128,
      unloaded_after_stage: true as const,
    });
    const run = {
      typed_metrics: [],
      metrics: [],
      chunk_metrics: [],
      predictive_model_stages: [
        stage("mdeberta_xnli", "example-org/mdeberta-xnli"),
        stage("multilingual_minilmv2_l6_nli", "example-org/minilm"),
        stage("qwen3_4b_rubric", "example-org/qwen3-4b-rubric"),
        stage("example_deep_judge", "example-org/deep-judge"),
        stage("modernbert_challenger", "example-org/modernbert", "failed"),
      ],
    } as unknown as ModelEnsembleRun;

    expect(modelEnsembleCompletedSmallExperts(run)).toBe(2);
    expect(run.predictive_model_stages.filter((candidate) => isDeepModelStage(candidate.model_key, candidate.repository_id)).map((candidate) => candidate.model_key))
      .toEqual(["qwen3_4b_rubric", "example_deep_judge"]);
    expect(modelEnsembleCompletedSmallExperts({ typed_metrics: [], metrics: [], chunk_metrics: [] })).toBeNull();
  });
});

describe("ModelEnsembleRadar public surface", () => {
  it("re-exports the pure axis model and the keyboard helper unchanged", () => {
    const names = [
      "MODEL_ENSEMBLE_LENSES",
      "MODEL_ENSEMBLE_STATE_LANE_MAGNITUDE",
      "MODEL_ENSEMBLE_WITHHELD_LANE_MAGNITUDE",
      "PREDICTIVE_WITHHELD_CONTRIBUTOR_PROOF_MISSING",
      "PREDICTIVE_WITHHELD_TOO_FEW_EXPERTS",
      "isModelEnsembleTypedMetric",
      "modelEnsembleAxisCoverage",
      "modelEnsembleAxisEvidence",
      "modelEnsembleAxisPlottedLabel",
      "modelEnsembleAxisRawRateLabel",
      "modelEnsembleCompletedSmallExperts",
      "modelEnsembleDensityBinsForDirection",
      "modelEnsembleIsRawExplicitZero",
      "modelEnsembleKnowledgeEntries",
      "modelEnsembleMetricPresentation",
      "modelEnsembleMetricStateLabel",
      "modelEnsembleMetricStateValue",
      "modelEnsembleMetricStatus",
      "modelEnsembleMetricStatusLabel",
      "modelEnsemblePredictiveBandPath",
      "modelEnsemblePredictiveSegments",
      "modelEnsemblePredictiveVisibility",
      "modelEnsemblePrimaryMetrics",
      "modelEnsembleRadarAxes",
      "modelEnsembleRadarMarkerMagnitude",
      "modelEnsembleRadarQualityValue",
      "modelEnsembleRadarSegments",
      "modelEnsembleReceiptsByKey",
    ] as const;
    const model = axisModel as unknown as Record<string, unknown>;
    const radar = radarModule as unknown as Record<string, unknown>;
    for (const name of names) {
      expect(model[name], name).toBeDefined();
      expect(radar[name], name).toBe(model[name]);
    }
    expect(radarModule.moveRovingFocus).toBe(moveRovingFocus);
    expect(typeof radarModule.ModelEnsembleRadar).toBe("function");
  });
});
