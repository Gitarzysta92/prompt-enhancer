import { describe, expect, it } from "vitest";
import type { ModelEnsembleRun, ModelEnsembleTrajectoryPoint } from "../../shared/api/contracts";
import { modelEnsembleRadarAxes } from "./metricAxisModel";
import {
  metricHistoryPlot,
  modelEnsembleHistoryRadarValue,
  modelEnsembleTrajectoryRadarData,
  resolveTrajectorySelection,
} from "./trajectorySelection";

const METRIC = "prompt.task_definition_coverage";
const REWORK = "collaboration.rework_candidate_rate";

type ReceiptState = "known" | "unknown" | "not_applicable" | "abstained" | "execution_error";

/** A minimal synthetic receipt for one key; the numeric value is only meaningful for `known`. */
function receipt(metricKey: string, state: ReceiptState, numericValue: number | null) {
  return { metric_key: metricKey, value_state: state, numeric_value: numericValue };
}

/**
 * One sealed history point carrying exactly one typed receipt for `metricKey`
 * (defaults to the higher-is-better framing metric). A `null` value seals an
 * unknown state; the history must never read it as zero or borrow another key.
 */
function point(
  runId: string,
  generation: number,
  value: number | null,
  overrides: Partial<ModelEnsembleTrajectoryPoint> = {},
  metricKey: string = METRIC,
): ModelEnsembleTrajectoryPoint {
  return {
    generation,
    run_id: runId,
    published_at: `2040-01-0${generation}T10:00:01Z`,
    completed_at: `2040-01-0${generation}T10:00:00Z`,
    max_messages: 100,
    source_coverage_state: "complete_window",
    chunk_count: 1,
    comparable_to_head: true,
    metrics: [],
    typed_metrics: value === null
      ? [{ metric_key: metricKey, value_state: "unknown", numeric_value: null }]
      : [{ metric_key: metricKey, value_state: "known", numeric_value: value }],
    predictive_metrics: [],
    ...overrides,
  } as unknown as ModelEnsembleTrajectoryPoint;
}

function sealedRun(runId: string): ModelEnsembleRun {
  return { run_id: runId, metrics: [], typed_metrics: [], chunk_metrics: [], predictive_metrics: [] } as unknown as ModelEnsembleRun;
}

describe("resolveTrajectorySelection", () => {
  const head = sealedRun("9".repeat(64));
  const points = [
    point(head.run_id, 4, 1),
    point("8".repeat(64), 3, 0.5),
    point("7".repeat(64), 2, 0.25, { comparable_to_head: false }),
    point("6".repeat(64), 1, 0.75),
  ];

  it("shows the exact head run while following live and overlays the comparable previous publication", () => {
    const selection = resolveTrajectorySelection({ points, selectedRunId: head.run_id, headRun: head, historicalRun: null });
    expect(selection.selectedPointIndex).toBe(0);
    expect(selection.selectedPoint?.run_id).toBe(head.run_id);
    expect(selection.historicalRunId).toBeNull();
    expect(selection.selectedRadarRun).toBe(head);
    expect(selection.comparisonRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));
  });

  it("falls back to the aggregate-only point until the exact historical snapshot for that id arrives", () => {
    const earlier = points[1].run_id;
    const pending = resolveTrajectorySelection({ points, selectedRunId: earlier, headRun: head, historicalRun: null });
    expect(pending.historicalRunId).toBe(earlier);
    expect(pending.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));
    expect(pending.selectedRadarRun).not.toBe(head);

    const wrongSnapshot = resolveTrajectorySelection({ points, selectedRunId: earlier, headRun: head, historicalRun: sealedRun("5".repeat(64)) });
    expect(wrongSnapshot.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));

    const exact = sealedRun(earlier);
    const loaded = resolveTrajectorySelection({ points, selectedRunId: earlier, headRun: head, historicalRun: exact });
    expect(loaded.selectedRadarRun).toBe(exact);
  });

  it("withholds the comparison across a scope break or a different message window", () => {
    const beforeBreak = resolveTrajectorySelection({ points, selectedRunId: points[1].run_id, headRun: head, historicalRun: null });
    expect(beforeBreak.comparisonRadarRun).toBeNull();
    const atBreak = resolveTrajectorySelection({ points, selectedRunId: points[2].run_id, headRun: head, historicalRun: null });
    expect(atBreak.comparisonRadarRun).toBeNull();
    const narrower = [points[0], point("8".repeat(64), 3, 0.5, { max_messages: 50 })];
    expect(resolveTrajectorySelection({ points: narrower, selectedRunId: head.run_id, headRun: head, historicalRun: null }).comparisonRadarRun).toBeNull();
    const oldest = resolveTrajectorySelection({ points, selectedRunId: points[3].run_id, headRun: head, historicalRun: null });
    expect(oldest.comparisonRadarRun).toBeNull();
  });

  it("keeps the exact head visible when the selection is absent from the visible history", () => {
    const missing = resolveTrajectorySelection({ points, selectedRunId: "1".repeat(64), headRun: head, historicalRun: null });
    expect(missing.selectedPointIndex).toBe(-1);
    expect(missing.selectedPoint).toBeNull();
    expect(missing.selectedRadarRun).toBe(head);
    expect(missing.comparisonRadarRun).toBeNull();
    const noHistory = resolveTrajectorySelection({ points: [], selectedRunId: null, headRun: head, historicalRun: null });
    expect(noHistory.selectedRadarRun).toBe(head);
    const nothing = resolveTrajectorySelection({ points: [], selectedRunId: null, headRun: null, historicalRun: null });
    expect(nothing.selectedRadarRun).toBeNull();
  });

  it("requests the exact snapshot for a selected point when no head run is loaded yet, showing the aggregate point meanwhile", () => {
    const withoutHead = resolveTrajectorySelection({ points, selectedRunId: head.run_id, headRun: null, historicalRun: null });
    expect(withoutHead.historicalRunId).toBe(head.run_id);
    expect(withoutHead.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[0]));
  });
});

describe("metricHistoryPlot", () => {
  it("orders points oldest-first, keeps unknown values unplotted, and connects only comparable neighbours", () => {
    const newestFirst = [
      point("d".repeat(64), 4, 1),
      point("c".repeat(64), 3, null),
      point("b".repeat(64), 2, 0.5, { comparable_to_head: false }),
      point("a".repeat(64), 1, 0),
    ];
    const plot = metricHistoryPlot(newestFirst, METRIC, "higher_is_better");
    expect(plot.chronological.map((entry) => entry.generation)).toEqual([1, 2, 3, 4]);
    expect(plot.values).toEqual([0, 0.5, null, 1]);
    expect(plot.coordinates).toEqual([
      [8, 42],
      [8 + 184 / 3, 42 - 0.5 * 34],
      null,
      [8 + 3 * (184 / 3), 42 - 34],
    ]);
    // a→b is broken by b's scope break, b→c by the unknown value, c→d by the unknown value.
    expect(plot.segments).toEqual([]);

    const comparable = metricHistoryPlot([point("b".repeat(64), 2, 0.5), point("a".repeat(64), 1, 0.25)], METRIC, "higher_is_better");
    expect(comparable.segments).toEqual([[[8, 42 - 0.25 * 34], [192, 42 - 0.5 * 34]]]);
  });

  it("orients lower-is-better history as radar quality and handles a single point", () => {
    // A sealed known raw rework rate of 0.2 is radar quality 0.8: farther from the centre, never inverted twice.
    const single = metricHistoryPlot([point("a".repeat(64), 1, 0.2, {}, REWORK)], REWORK, "lower_is_better");
    expect(single.values[0]).toBeCloseTo(0.8);
    expect(single.coordinates[0]?.[0]).toBe(8);
    expect(single.coordinates[0]?.[1]).toBeCloseTo(42 - 0.8 * 34);
    expect(single.segments).toEqual([]);
    expect(modelEnsembleHistoryRadarValue(point("a".repeat(64), 1, null), METRIC, "higher_is_better")).toBeNull();
    expect(metricHistoryPlot([], METRIC, "higher_is_better")).toEqual({ chronological: [], values: [], coordinates: [], segments: [] });
  });

  it("reads exactly the requested metric key and keeps unknown or absent receipts null", () => {
    const reworkPoint = point("a".repeat(64), 1, 0.2, {}, REWORK);
    // The same point never lends its rework value to another axis, in either direction.
    expect(modelEnsembleHistoryRadarValue(reworkPoint, REWORK, "lower_is_better")).toBeCloseTo(0.8);
    expect(modelEnsembleHistoryRadarValue(reworkPoint, REWORK, "higher_is_better")).toBeCloseTo(0.2);
    expect(modelEnsembleHistoryRadarValue(reworkPoint, METRIC, "higher_is_better")).toBeNull();
    expect(modelEnsembleHistoryRadarValue(point("b".repeat(64), 2, 0.9), REWORK, "lower_is_better")).toBeNull();
    // A sealed unknown rework state stays null; it is not a zero rate and not radar quality 1.
    expect(modelEnsembleHistoryRadarValue(point("c".repeat(64), 3, null, {}, REWORK), REWORK, "lower_is_better")).toBeNull();
    // A scope break keeps the value plotted for that point; only the connecting segments are withheld.
    const scopeBreak = metricHistoryPlot(
      [point("e".repeat(64), 5, 0.2, { comparable_to_head: false }, REWORK), point("d".repeat(64), 4, 0.5, {}, REWORK)],
      REWORK,
      "lower_is_better",
    );
    expect(scopeBreak.values[0]).toBeCloseTo(0.5);
    expect(scopeBreak.values[1]).toBeCloseTo(0.8);
    expect(scopeBreak.segments).toEqual([]);
  });

  /** A history point with explicit typed and legacy committee receipt lists (either may be empty). */
  const receiptsPoint = (
    typed: ReadonlyArray<ReturnType<typeof receipt>>,
    committee: ReadonlyArray<ReturnType<typeof receipt>>,
  ): ModelEnsembleTrajectoryPoint => ({
    ...point("a".repeat(64), 1, null),
    typed_metrics: typed,
    metrics: committee,
  }) as unknown as ModelEnsembleTrajectoryPoint;

  it("never replaces a typed non-numeric state with a known legacy committee value", () => {
    const committeeKnown = [receipt(REWORK, "known", 0.2)];
    for (const state of ["unknown", "not_applicable", "abstained", "execution_error"] as const) {
      const typedState = receiptsPoint([receipt(REWORK, state, null)], committeeKnown);
      expect(modelEnsembleHistoryRadarValue(typedState, REWORK, "lower_is_better"), state).toBeNull();
      expect(modelEnsembleHistoryRadarValue(typedState, REWORK, "higher_is_better"), state).toBeNull();
    }
    // A typed receipt marked known but without a numeric value is not a measurement either.
    const typedKnownWithoutValue = receiptsPoint([receipt(REWORK, "known", null)], committeeKnown);
    expect(modelEnsembleHistoryRadarValue(typedKnownWithoutValue, REWORK, "lower_is_better")).toBeNull();
    // A typed projection that does not publish the key does not borrow the committee value for it.
    const typedOtherKeyOnly = receiptsPoint([receipt(METRIC, "known", 0.9)], committeeKnown);
    expect(modelEnsembleHistoryRadarValue(typedOtherKeyOnly, REWORK, "lower_is_better")).toBeNull();
    expect(modelEnsembleHistoryRadarValue(typedOtherKeyOnly, METRIC, "higher_is_better")).toBeCloseTo(0.9);
  });

  it("uses compact canonical V2 history states ahead of both legacy layers", () => {
    const committeeKnown = [receipt(REWORK, "known", 0.2)];
    const historyPoint = receiptsPoint([receipt(REWORK, "known", 0.4)], committeeKnown);
    (historyPoint as any).metric_states_v2 = [{
      metric_key: REWORK,
      registry_version: "all-20-factor-contracts-v2",
      contract_version: "probabilistic-metric-contract-v2",
      contract_fingerprint: "3cfa3bbf472661329527e86b3248f5255bfe0307931d30042a87ec36cf1100a0",
      evidence_authority: "conversation",
      value_state: "unknown",
      explanation_code: "opportunity_family_unobservable",
      numerator: null,
      denominator: null,
      numeric_value: null,
      censoring_lower_bound: null,
      censoring_upper_bound: null,
      statistics: {
        metric_key: REWORK,
        denominator_basis: "semantic_unit_opportunities",
        opportunity_unit_kind: "feedback",
        capability_available: false,
        source_complete: false,
        eligible_count: 0,
        met_count: 0,
        not_met_count: 0,
        pending_count: 0,
        unknown_count: 0,
        superseded_excluded_count: 0,
        distinct_owner_count: 0,
      },
      projection_version: "metric-contract-v2-projection-1",
      product_metric_eligible: false,
    }];
    expect(modelEnsembleHistoryRadarValue(historyPoint, REWORK, "lower_is_better")).toBeNull();
    const axis = modelEnsembleRadarAxes(modelEnsembleTrajectoryRadarData(historyPoint), "collaboration-flow")
      .find((candidate) => candidate.key === REWORK)!;
    expect(axis.metric).toMatchObject({ value_state: "unknown", source_kind: "metric_v2" });
    expect(axis.plotted).toBeNull();
  });

  it("lets a typed known receipt win over the committee, falls back only for legacy-only points, and orients lower-is-better", () => {
    const typedWins = receiptsPoint([receipt(REWORK, "known", 0.2)], [receipt(REWORK, "known", 0.7)]);
    expect(modelEnsembleHistoryRadarValue(typedWins, REWORK, "lower_is_better")).toBeCloseTo(0.8);
    expect(modelEnsembleHistoryRadarValue(typedWins, REWORK, "higher_is_better")).toBeCloseTo(0.2);

    const legacyOnly = receiptsPoint([], [receipt(REWORK, "known", 0.2)]);
    expect(modelEnsembleHistoryRadarValue(legacyOnly, REWORK, "lower_is_better")).toBeCloseTo(0.8);
    expect(modelEnsembleHistoryRadarValue(legacyOnly, REWORK, "higher_is_better")).toBeCloseTo(0.2);
    expect(modelEnsembleHistoryRadarValue(legacyOnly, METRIC, "higher_is_better")).toBeNull();

    const legacyUnknown = receiptsPoint([], [receipt(REWORK, "unknown", null)]);
    expect(modelEnsembleHistoryRadarValue(legacyUnknown, REWORK, "lower_is_better")).toBeNull();
    expect(modelEnsembleHistoryRadarValue(receiptsPoint([], []), REWORK, "lower_is_better")).toBeNull();
  });

  it("resolves every history value exactly as the radar resolves the same point", () => {
    const cases: Array<[string, ModelEnsembleTrajectoryPoint]> = [
      ["typed unknown + committee known", receiptsPoint([receipt(REWORK, "unknown", null)], [receipt(REWORK, "known", 0.2)])],
      ["typed abstained + committee known", receiptsPoint([receipt(REWORK, "abstained", null)], [receipt(REWORK, "known", 0.2)])],
      ["typed known + committee known", receiptsPoint([receipt(REWORK, "known", 0.2)], [receipt(REWORK, "known", 0.7)])],
      ["typed other key + committee known", receiptsPoint([receipt(METRIC, "known", 0.9)], [receipt(REWORK, "known", 0.2)])],
      ["legacy-only known", receiptsPoint([], [receipt(REWORK, "known", 0.2)])],
      ["legacy-only unknown", receiptsPoint([], [receipt(REWORK, "unknown", null)])],
      ["no receipts", receiptsPoint([], [])],
    ];
    for (const [label, historyPoint] of cases) {
      const axis = modelEnsembleRadarAxes(modelEnsembleTrajectoryRadarData(historyPoint), "collaboration-flow")
        .find((candidate) => candidate.key === REWORK)!;
      expect(axis.direction, label).toBe("lower_is_better");
      expect(modelEnsembleHistoryRadarValue(historyPoint, REWORK, axis.direction), label).toBe(axis.plotted);
    }
  });
});
