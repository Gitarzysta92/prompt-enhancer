import { describe, expect, it } from "vitest";
import type { ModelEnsembleRun } from "../../shared/api/contracts";
import {
  MODEL_ENSEMBLE_LENSES,
  modelEnsembleDensityBinsForDirection,
  modelEnsembleMetricPresentation,
  modelEnsembleMetricStatus,
  modelEnsembleMetricStatusLabel,
  modelEnsembleIsRawExplicitZero,
  modelEnsemblePredictiveVisibility,
  modelEnsembleRadarAxes,
  modelEnsembleRadarMarkerMagnitude,
  modelEnsembleRadarSegments,
  moveRovingFocus,
} from "./ModelEnsembleRadar";

type EnsembleMetric = ModelEnsembleRun["metrics"][number];
type TypedMetric = ModelEnsembleRun["typed_metrics"][number];
type PredictiveMetric = ModelEnsembleRun["predictive_metrics"][number];

function prediction(overrides: Partial<PredictiveMetric> = {}): PredictiveMetric {
  return {
    metric_key: "prompt.task_definition_coverage",
    target: "metric_value",
    state: "experimental",
    mean: 0.5,
    median: 0.5,
    q05: 0.2,
    q25: 0.4,
    q75: 0.6,
    q95: 0.8,
    applicability_probability: 0.9,
    pending_probability: 0.05,
    model_disagreement: 0.2,
    effective_observation_count: 2,
    model_set_version: "example-model-set-v1",
    calibration_version: "not-calibrated-v1",
    contract_version: "example-contract-v1",
    contract_fingerprint: "a".repeat(64),
    product_metric_eligible: false,
    ...overrides,
  };
}

function metric(overrides: Partial<EnsembleMetric> = {}): EnsembleMetric {
  return {
    metric_key: "prompt.task_definition_coverage",
    value_state: "known",
    numerator: 0,
    denominator: 2,
    numeric_value: 0,
    known_chunk_count: 2,
    abstained_chunk_count: 0,
    unsupported_chunk_count: 0,
    failed_chunk_count: 0,
    total_chunk_count: 2,
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

describe("modelEnsembleMetricPresentation", () => {
  it("distinguishes an explicit known zero from missing inference", () => {
    const value = modelEnsembleMetricPresentation(metric(), "higher_is_better");

    expect(value.value).toBe("0% signal");
    expect(value.detail).toMatch(/typed opportunity eligibility/i);
    expect(value.detail).toMatch(/radar 0%/i);
  });

  it("explains that lower-is-better raw zero maps to the radar edge", () => {
    const value = modelEnsembleMetricPresentation(metric(), "lower_is_better");

    expect(value.value).toBe("100% radar quality");
    expect(value.detail).toMatch(/raw lower-is-better rate 0%/i);
    expect(value.detail).toMatch(/radar quality is 100%/i);
  });

  it("orients lower-is-better estimates and density as radar quality while preserving the raw rate", () => {
    const rework = "collaboration.rework_candidate_rate";
    const run = {
      typed_metrics: [typedMetric({
        metric_key: rework,
        numerator: 2,
        denominator: 100,
        numeric_value: 0.02,
      })],
      metrics: [],
      chunk_metrics: [],
      predictive_metrics: [prediction({
        metric_key: rework,
        median: 0.02,
        q05: 0.01,
        q25: 0.015,
        q75: 0.03,
        q95: 0.04,
      })],
      predictive_model_stages: [0, 1].map((index) => ({
        model_key: `example_small_${index}`,
        repository_id: `example-org/small-${index}`,
        status: "completed",
      })),
    } as unknown as ModelEnsembleRun;

    const axis = modelEnsembleRadarAxes(run, "collaboration-flow")
      .find((candidate) => candidate.key === rework)!;
    expect(axis.plotted).toBe(0.98);
    expect(modelEnsembleIsRawExplicitZero(axis)).toBe(false);
    expect(axis.predictiveMedian).toBe(0.98);
    expect(axis.predictiveQ05).toBe(0.96);
    expect(axis.predictiveQ95).toBe(0.99);
    expect(modelEnsembleMetricPresentation(axis.metric!, axis.direction)).toEqual({
      value: "98% radar quality",
      detail: expect.stringMatching(/raw lower-is-better rate 2%/i),
    });
    expect(modelEnsembleDensityBinsForDirection([0.1, 0.2, 0.7], "lower_is_better"))
      .toEqual([0.7, 0.2, 0.1]);
    expect(modelEnsembleDensityBinsForDirection([0.1, 0.2, 0.7], "higher_is_better"))
      .toEqual([0.1, 0.2, 0.7]);
  });

  it("never presents abstention as numeric zero", () => {
    const value = modelEnsembleMetricPresentation(
      metric({
        value_state: "abstained",
        numerator: null,
        denominator: null,
        numeric_value: null,
        known_chunk_count: 0,
        abstained_chunk_count: 2,
      }),
      "higher_is_better",
    );

    expect(value.value).toBe("Needs evidence");
    expect(value.detail).toMatch(/did not support a numeric decision/i);
  });

  it("presents an open episode horizon as first-class pending state without plotting zero", () => {
    const pending = typedMetric({
      value_state: "unknown",
      numerator: null,
      denominator: null,
      numeric_value: null,
      explanation_code: "episode_horizon_open",
    });
    const run = {
      typed_metrics: [pending],
      metrics: [],
      chunk_metrics: [],
    } as unknown as ModelEnsembleRun;

    expect(modelEnsembleMetricStatus(pending)).toBe("pending");
    expect(modelEnsembleMetricStatusLabel("pending")).toBe("pending · horizon open");
    expect(modelEnsembleMetricPresentation(pending, "higher_is_better")).toEqual({
      value: "Pending",
      detail: expect.stringMatching(/episode closes.*not a zero/i),
    });
    expect(modelEnsembleRadarAxes(run, "task-framing")[0].plotted).toBeNull();
  });

  it("supports arrow, Home, and End keyboard movement across metric controls", () => {
    const navigation = document.createElement("nav");
    navigation.innerHTML = "<button>One</button><button>Two</button><button disabled>Skip</button><button>Three</button>";
    document.body.append(navigation);
    const buttons = [...navigation.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
    const selected: number[] = [];
    buttons[0].focus();

    moveRovingFocus({
      key: "ArrowRight",
      currentTarget: navigation,
      preventDefault: () => undefined,
    }, (index) => selected.push(index));
    expect(buttons[1]).toHaveFocus();
    moveRovingFocus({ key: "End", currentTarget: navigation, preventDefault: () => undefined });
    expect(buttons[2]).toHaveFocus();
    moveRovingFocus({ key: "Home", currentTarget: navigation, preventDefault: () => undefined });
    expect(buttons[0]).toHaveFocus();
    expect(selected).toEqual([1]);
  });

  it("keeps four versioned lenses with stable axis counts", () => {
    expect(MODEL_ENSEMBLE_LENSES.map((lens) => [lens.id, lens.expectedMetricCount])).toEqual([
      ["task-framing", 6],
      ["collaboration-flow", 5],
      ["reasoning-trace", 4],
      ["outcome-evidence", 5],
    ]);
  });

  it("uses typed numerator and denominator even when the model committee abstains", () => {
    const committee = metric({
      value_state: "abstained",
      numerator: null,
      denominator: null,
      numeric_value: null,
      known_chunk_count: 0,
      abstained_chunk_count: 2,
    });
    const run = {
      metrics: [committee],
      typed_metrics: [typedMetric()],
      chunk_metrics: [],
    } as unknown as ModelEnsembleRun;

    const axes = modelEnsembleRadarAxes(run, "task-framing");
    expect(axes[0].plotted).toBe(0.75);
    const presentation = modelEnsembleMetricPresentation(axes[0].metric!, "higher_is_better");
    expect(presentation.value).toBe("75% measured");
    expect(presentation.detail).toMatch(/3\/4 typed opportunities/i);
  });

  it("breaks the outline at unknown axes instead of bridging them as zero", () => {
    const run = {
      typed_metrics: [],
      metrics: [
        metric({ metric_key: "prompt.task_definition_coverage", numeric_value: 0.8, numerator: 4, denominator: 5 }),
        metric({ metric_key: "prompt.problem_evidence_quality", numeric_value: 0.6, numerator: 3, denominator: 5 }),
        metric({
          metric_key: "prompt.context_sufficiency",
          value_state: "unknown",
          numeric_value: null,
          numerator: null,
          denominator: null,
          known_chunk_count: 0,
          unsupported_chunk_count: 2,
        }),
      ],
    } as unknown as ModelEnsembleRun;
    const axes = modelEnsembleRadarAxes(run, "task-framing");

    expect(axes).toHaveLength(6);
    expect(axes[2].plotted).toBeNull();
    expect(modelEnsembleRadarSegments(axes)).toEqual([[0, 1]]);
  });

  it("gives explicit zeros and nonnumeric states distinct marker positions without changing values", () => {
    expect(modelEnsembleRadarMarkerMagnitude(0)).toBe(0);
    expect(modelEnsembleRadarMarkerMagnitude(null)).toBeGreaterThan(1);
    expect(modelEnsembleRadarMarkerMagnitude(0.67)).toBe(0.67);
  });

  it("derives explicit zero from the raw receipt rather than inverted radar geometry", () => {
    const rework = "collaboration.rework_candidate_rate";
    const zeroRateRun = {
      typed_metrics: [typedMetric({ metric_key: rework, numerator: 0, denominator: 5, numeric_value: 0 })],
      metrics: [], chunk_metrics: [],
    } as unknown as ModelEnsembleRun;
    const worstRateRun = {
      typed_metrics: [typedMetric({ metric_key: rework, numerator: 5, denominator: 5, numeric_value: 1 })],
      metrics: [], chunk_metrics: [],
    } as unknown as ModelEnsembleRun;

    const best = modelEnsembleRadarAxes(zeroRateRun, "collaboration-flow").find((axis) => axis.key === rework)!;
    const worst = modelEnsembleRadarAxes(worstRateRun, "collaboration-flow").find((axis) => axis.key === rework)!;
    expect(best.plotted).toBe(1);
    expect(modelEnsembleIsRawExplicitZero(best)).toBe(true);
    expect(worst.plotted).toBe(0);
    expect(modelEnsembleIsRawExplicitZero(worst)).toBe(false);
  });

  it("explains adapter and objective-receipt gaps instead of calling them low scores", () => {
    const unavailable = modelEnsembleMetricPresentation(
      typedMetric({
        metric_key: "logic.decision_rationale_coverage",
        value_state: "abstained",
        numerator: null,
        denominator: null,
        numeric_value: null,
        explanation_code: "message_kind_unavailable",
      }),
      "higher_is_better",
    );
    const objective = modelEnsembleMetricPresentation(
      typedMetric({
        metric_key: "outcome.verified_requirement_coverage",
        value_state: "abstained",
        numerator: null,
        denominator: null,
        numeric_value: null,
        explanation_code: "objective_verification_stream_required",
      }),
      "higher_is_better",
    );

    expect(unavailable.detail).toMatch(/adapter version/i);
    expect(unavailable.detail).toMatch(/not a zero/i);
    expect(unavailable.value).toBe("Needs evidence");
    expect(objective.detail).toMatch(/typed local tool, test, artifact, or verification receipt/i);
  });

  it("withholds broad, out-of-distribution, and single-expert estimates", () => {
    expect(modelEnsemblePredictiveVisibility(prediction(), 2)).toEqual({ visible: true, reason: null });
    expect(modelEnsemblePredictiveVisibility(prediction({ q05: 0, q95: 1 }), 3).reason).toMatch(/uninformative/i);
    expect(modelEnsemblePredictiveVisibility(prediction(), 1).reason).toMatch(/fewer than two/i);
    expect(modelEnsemblePredictiveVisibility(prediction({ state: "out_of_distribution" }), 3).reason).toMatch(/outside/i);
  });

  it("separates missing contributor proof from a proven shortage of small experts", () => {
    const missingProof = modelEnsemblePredictiveVisibility(prediction(), null);
    expect(missingProof.visible).toBe(false);
    expect(missingProof.reason).toMatch(/does not expose contributor proof/i);
    expect(missingProof.reason).not.toMatch(/fewer than two/i);
    expect(modelEnsemblePredictiveVisibility(prediction(), 0).reason).toMatch(/fewer than two/i);
    // Out-of-distribution outranks both, so a history point never claims cohort membership.
    expect(modelEnsemblePredictiveVisibility(prediction({ state: "out_of_distribution" }), null).reason).toMatch(/outside/i);
  });
});
