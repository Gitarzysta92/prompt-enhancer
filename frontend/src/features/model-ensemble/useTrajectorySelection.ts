import { useEffect, useState } from "react";
import type {
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPoint,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { MetricDefinitionsOutOfDateError, type MetricDefinitionMismatch } from "../../shared/api/metricPublicationV2Contract";
import { resolveTrajectorySelection, type TrajectorySelection } from "./trajectorySelection";

export interface HistoricalRunState {
  run: ModelEnsembleRun | null;
  /**
   * Set when the exact snapshot for the earlier point exists but the
   * compatibility gate refused it: only the compact state facts of that point
   * may be shown, and no guidance receipt is read from it. Kept separate from a
   * transport failure so the surface never calls a refused receipt "absent".
   */
  refused: MetricDefinitionMismatch | null;
}

interface HistoricalRunSlot extends HistoricalRunState {
  /** Request identity that owns both the run and the refusal in this slot. */
  requestedRunId: string | null;
}

/**
 * Loads the immutable snapshot for an earlier selected history point. The
 * displayed run is cleared while loading, admitted only when its run id equals
 * the requested id, and dropped again on failure; the aggregate-only trajectory
 * point remains the fallback for the caller.
 */
export function useHistoricalRun(
  transport: Pick<PromptEnhancerTransport, "getModelEnsembleSnapshot">,
  historicalRunId: string | null,
): HistoricalRunState {
  const [historical, setHistorical] = useState<HistoricalRunSlot>({
    requestedRunId: null,
    run: null,
    refused: null,
  });
  useEffect(() => {
    if (historicalRunId === null || transport.getModelEnsembleSnapshot === undefined) {
      setHistorical({ requestedRunId: historicalRunId, run: null, refused: null });
      return;
    }
    const controller = new AbortController();
    setHistorical({ requestedRunId: historicalRunId, run: null, refused: null });
    transport.getModelEnsembleSnapshot(historicalRunId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted && value.run_id === historicalRunId) {
          setHistorical({ requestedRunId: historicalRunId, run: value, refused: null });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setHistorical({
          requestedRunId: historicalRunId,
          run: null,
          refused: error instanceof MetricDefinitionsOutOfDateError ? error.mismatch : null,
        });
    });
    return () => controller.abort();
  }, [historicalRunId, transport]);
  // Effects clear the slot only after a changed selection has rendered. Bind
  // the cached value to its request during render as well, so A can never be
  // exposed as B for even one committed frame.
  return historical.requestedRunId === historicalRunId
    ? { run: historical.run, refused: historical.refused }
    : { run: null, refused: null };
}

export interface UseTrajectorySelectionInput {
  transport: Pick<PromptEnhancerTransport, "getModelEnsembleSnapshot">;
  /** Visible trajectory points, newest first (empty when no trajectory is shown). */
  points: readonly ModelEnsembleTrajectoryPoint[];
  selectedRunId: string | null;
  /** The exact sealed head run currently loaded for this surface, if any. */
  headRun: ModelEnsembleRun | null;
}

export interface UseTrajectorySelectionResult extends TrajectorySelection {
  /** The exact snapshot loaded for the selected earlier point, when it is not the head. */
  historicalRun: ModelEnsembleRun | null;
  /** Compatibility-gate refusal of that exact snapshot; the compact point is shown alone. */
  historicalRunRefused: MetricDefinitionMismatch | null;
  /** Exact selected seal for identity-sensitive consumers; null while an earlier snapshot is loading/refused. */
  selectedExactRun: ModelEnsembleRun | null;
}

/**
 * Head/history reconciliation shared by the session panel and the live overlay:
 * resolves which point is selected, loads its exact snapshot when it is not the
 * head, and derives the radar data plus the comparable prior publication.
 */
export function useTrajectorySelection({
  transport,
  points,
  selectedRunId,
  headRun,
}: UseTrajectorySelectionInput): UseTrajectorySelectionResult {
  const selectedPointIndex = points.findIndex((point) => point.run_id === selectedRunId);
  const selectedPoint = selectedPointIndex < 0 ? null : points[selectedPointIndex];
  const historicalRunId = selectedPoint !== null && selectedPoint.run_id !== headRun?.run_id
    ? selectedPoint.run_id
    : null;
  const historical = useHistoricalRun(transport, historicalRunId);
  const exactHistoricalRun = historicalRunId !== null && historical.run?.run_id === historicalRunId
    ? historical.run
    : null;
  const selection = resolveTrajectorySelection({
    points,
    selectedRunId,
    headRun,
    historicalRun: exactHistoricalRun,
  });
  const selectedExactRun = selection.selectedPoint === null
    ? headRun
    : selection.selectedPoint.run_id === headRun?.run_id
      ? headRun
      : exactHistoricalRun;
  return {
    ...selection,
    historicalRun: exactHistoricalRun,
    historicalRunRefused: historicalRunId === null ? null : historical.refused,
    selectedExactRun,
  };
}
