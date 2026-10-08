import type {
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPoint,
} from "../../shared/api/contracts";
import {
  modelEnsembleRadarQualityValue,
  modelEnsembleReceiptsByKey,
  type ModelEnsembleMetricDirection,
  type ModelEnsembleRadarData,
} from "./metricAxisModel";

/**
 * Pure head/history reconciliation for the published trajectory. Both the
 * session panel and the live overlay select which sealed run the workspace
 * shows and which earlier comparable publication may be overlaid; the rules
 * live here once so the two surfaces can never drift apart.
 */

/** A content-free trajectory point rendered as radar data (aggregate only, no chunk trace). */
export function modelEnsembleTrajectoryRadarData(
  point: ModelEnsembleTrajectoryPoint,
): ModelEnsembleRadarData {
  return {
    metrics: point.metrics,
    typed_metrics: point.typed_metrics ?? [],
    metric_states_v2: point.metric_states_v2 ?? [],
    predictive_metrics: point.predictive_metrics ?? [],
    chunk_metrics: [],
  };
}

/**
 * Radar-quality value of one metric at one history point. It resolves the
 * receipt exactly as the radar does for the same point (`modelEnsembleRadarAxes`
 * over `modelEnsembleTrajectoryRadarData`): the typed projection is the only
 * source when the point exposes one, so a typed unknown, abstained, error, N/A,
 * or non-numeric receipt stays `null` and is never replaced by a known legacy
 * committee value; a legacy-only point (no typed receipts at all) reads its
 * committee receipt. Lower-is-better values are oriented as `1 - raw`; an
 * unknown or absent receipt is never a zero.
 */
export function modelEnsembleHistoryRadarValue(
  point: ModelEnsembleTrajectoryPoint,
  metricKey: string,
  direction: ModelEnsembleMetricDirection,
): number | null {
  const metric = modelEnsembleReceiptsByKey(modelEnsembleTrajectoryRadarData(point)).get(metricKey) ?? null;
  return modelEnsembleRadarQualityValue(metric, direction);
}

export type MetricHistoryCoordinate = readonly [number, number];

export interface MetricHistoryPlot {
  /** Oldest first, matching the left-to-right sparkline. */
  chronological: readonly ModelEnsembleTrajectoryPoint[];
  /** Radar-quality value per chronological point; a null stays unplotted, never zero. */
  values: ReadonlyArray<number | null>;
  /** SVG coordinates in the 200x50 sparkline viewBox; null for unplotted points. */
  coordinates: ReadonlyArray<MetricHistoryCoordinate | null>;
  /** Only adjacent plotted points that are both comparable to the head connect. */
  segments: ReadonlyArray<readonly [MetricHistoryCoordinate, MetricHistoryCoordinate]>;
}

/** Sparkline geometry for one metric across sealed history points (newest-first input). */
export function metricHistoryPlot(
  points: readonly ModelEnsembleTrajectoryPoint[],
  metricKey: string,
  direction: ModelEnsembleMetricDirection,
): MetricHistoryPlot {
  const chronological = [...points].reverse();
  const values = chronological.map((point) => modelEnsembleHistoryRadarValue(point, metricKey, direction));
  const coordinates = values.map((value, index) => value === null
    ? null
    : [8 + index * (184 / Math.max(1, values.length - 1)), 42 - value * 34] as const);
  const segments = coordinates.flatMap((coordinate, index) => {
    const next = coordinates[index + 1];
    const currentPoint = chronological[index];
    const nextPoint = chronological[index + 1];
    return coordinate !== null && next !== null && currentPoint?.comparable_to_head && nextPoint?.comparable_to_head
      ? [[coordinate, next] as const]
      : [];
  });
  return { chronological, values, coordinates, segments };
}

export interface TrajectorySelectionInput {
  /** Visible trajectory points, newest first (empty when no trajectory is shown). */
  points: readonly ModelEnsembleTrajectoryPoint[];
  /** The run the user selected in the history drawer, or null when following the head. */
  selectedRunId: string | null;
  /** The exact sealed head run currently loaded for this surface, if any. */
  headRun: ModelEnsembleRun | null;
  /** The immutable snapshot loaded for an earlier selected point, if any. */
  historicalRun: ModelEnsembleRun | null;
}

export interface TrajectorySelection {
  selectedPointIndex: number;
  selectedPoint: ModelEnsembleTrajectoryPoint | null;
  /** The earlier run id whose immutable snapshot should be loaded, or null when the head is shown. */
  historicalRunId: string | null;
  /** The radar data to render: the exact head run, the exact historical run, or the aggregate-only point. */
  selectedRadarRun: ModelEnsembleRadarData | null;
  /** The immediately preceding publication, only when both sides are comparable and share a window. */
  comparisonRadarRun: ModelEnsembleRadarData | null;
}

export function resolveTrajectorySelection({
  points,
  selectedRunId,
  headRun,
  historicalRun,
}: TrajectorySelectionInput): TrajectorySelection {
  const selectedPointIndex = points.findIndex((point) => point.run_id === selectedRunId);
  const selectedPoint = selectedPointIndex < 0 ? null : points[selectedPointIndex];
  const historicalRunId = selectedPoint !== null && selectedPoint.run_id !== headRun?.run_id
    ? selectedPoint.run_id
    : null;
  const selectedRadarRun: ModelEnsembleRadarData | null = selectedPoint === null
    ? headRun
    : selectedPoint.run_id === headRun?.run_id
      ? headRun
      : historicalRun?.run_id === selectedPoint.run_id
        ? historicalRun
        : modelEnsembleTrajectoryRadarData(selectedPoint);
  const comparisonPoint = selectedPointIndex >= 0
    ? points[selectedPointIndex + 1] ?? null
    : null;
  const comparisonRadarRun = selectedPoint !== null
    && comparisonPoint !== null
    && selectedPoint.comparable_to_head
    && comparisonPoint.comparable_to_head
    && selectedPoint.max_messages === comparisonPoint.max_messages
    ? modelEnsembleTrajectoryRadarData(comparisonPoint)
    : null;
  return { selectedPointIndex, selectedPoint, historicalRunId, selectedRadarRun, comparisonRadarRun };
}
