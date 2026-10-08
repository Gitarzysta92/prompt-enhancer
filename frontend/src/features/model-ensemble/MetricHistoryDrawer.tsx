import { useId } from "react";
import type { ModelEnsembleTrajectoryPoint } from "../../shared/api/contracts";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import {
  modelEnsembleMetricStateValue,
  modelEnsembleReceiptsByKey,
  type ModelEnsembleMetricDirection,
} from "./metricAxisModel";
import { shortIdentity } from "./modelStages";
import { metricHistoryPlot, modelEnsembleTrajectoryRadarData } from "./trajectorySelection";
import "./MetricHistoryAndStages.css";

/**
 * Sealed-snapshot history for the selected metric. History is content-free:
 * it renders aggregate receipt states and immutable run identities, never
 * message content. Numeric and state-only receipts remain visibly separate.
 */
export interface MetricWorkspaceHistory {
  points: readonly ModelEnsembleTrajectoryPoint[];
  headRunId: string | null;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  error?: boolean;
  /** Manual read-only refetch once bounded automatic retries are exhausted. */
  onRetry?: () => void;
}

function percent(value: number): string {
  return `${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

function historyReceiptLabel(
  point: ModelEnsembleTrajectoryPoint,
  metricKey: string,
  direction: ModelEnsembleMetricDirection,
): { kind: "numeric" | "state"; text: string } {
  const metric = modelEnsembleReceiptsByKey(modelEnsembleTrajectoryRadarData(point)).get(metricKey) ?? null;
  const raw = metric?.value_state === "known" ? metric.numeric_value : null;
  if (raw == null) {
    const state = metric?.value_state === "known" ? "No numeric value" : modelEnsembleMetricStateValue(metric);
    return { kind: "state", text: `State only · ${state}` };
  }
  return direction === "lower_is_better"
    ? { kind: "numeric", text: `Numeric · raw ${percent(raw)} · chart ${percent(1 - raw)}` }
    : { kind: "numeric", text: `Numeric · ${percent(raw)}` };
}

function snapshotName(point: ModelEnsembleTrajectoryPoint, current: boolean): string {
  return `${current ? "Current" : "Earlier"} · generation ${point.generation}`;
}

export function MetricHistoryDrawer({ history, metricKey, direction }: {
  history?: MetricWorkspaceHistory;
  metricKey: string;
  direction: ModelEnsembleMetricDirection;
}) {
  const descriptionId = useId();
  const { chronological, coordinates, segments } = metricHistoryPlot(history?.points ?? [], metricKey, direction);
  const points = history?.points ?? [];
  const headIsLoaded = history?.headRunId !== null
    && points.some((point) => point.run_id === history?.headRunId);
  const requestedSelectionIsLoaded = history?.selectedRunId !== null
    && points.some((point) => point.run_id === history?.selectedRunId);
  const effectiveSelectedRunId = requestedSelectionIsLoaded
    ? history!.selectedRunId
    : headIsLoaded
      ? history!.headRunId
      : null;
  const numericCount = coordinates.filter((coordinate) => coordinate !== null).length;
  const snapshotCount = points.length;
  const summary = history === undefined
    ? "Not exposed for this receipt"
    : history.error && snapshotCount === 0 ? "History unavailable" : `${snapshotCount} sealed snapshots`;

  return (
    <details className="metric-workspace__drawer metric-history">
      <summary><span>History</span><small>{summary}</small></summary>
      <div className="metric-history__body">
        {history === undefined ? (
          <p className="metric-history__empty">Snapshot history becomes available when the local watch exposes a content-free trajectory. The current sealed snapshot remains unchanged.</p>
        ) : (
          <>
            {history.error && (
              <p className="metric-history__notice" role="status">
                {snapshotCount === 0
                  ? "History refresh is delayed and no previously loaded trajectory is available."
                  : `History refresh is delayed; showing ${snapshotCount} previously loaded sealed snapshot${snapshotCount === 1 ? "" : "s"}.`}
                {history.onRetry !== undefined && (
                  <>
                    {" "}
                    <button
                      className="metric-history__retry"
                      onClick={history.onRetry}
                      type="button"
                    >
                      Retry history
                    </button>
                  </>
                )}
              </p>
            )}
            {!requestedSelectionIsLoaded && history.selectedRunId !== null && headIsLoaded && (
              <p className="metric-history__notice" role="status">The requested snapshot is no longer in the loaded trajectory. The current snapshot is selected.</p>
            )}
            {snapshotCount === 0 ? (
              <p className="metric-history__empty">{history.error ? "The stored snapshot count remains unknown until a verified history read." : "No sealed snapshots are available in the loaded trajectory."} Missing history is not a zero metric value.</p>
            ) : (
              <>
                <p className="metric-history__chart-note" id={descriptionId}>
                  {numericCount} of {snapshotCount} loaded snapshots have a numeric receipt. {" "}
                  {direction === "lower_is_better"
                    ? "Numeric raw rates are inverted once for chart orientation; each snapshot card keeps the raw rate. "
                    : "Numeric receipts use their raw higher-is-better value for chart orientation. "}
                  State-only and missing receipts stay outside the chart. Lines connect adjacent snapshots only when both are comparable to the current snapshot.
                </p>
                {numericCount === 0 ? (
                  <p className="metric-history__chart-empty" role="note">No numeric receipts exist for this metric in the loaded snapshots. State-only receipts remain listed below.</p>
                ) : (
                  <svg aria-describedby={descriptionId} aria-label="Selected metric history" data-numeric-count={numericCount} role="img" viewBox="0 0 200 50">
                    <line className="metric-history__baseline" x1="8" x2="192" y1="42" y2="42" />
                    {segments.map(([from, to], index) => <line className="metric-history__segment" key={index} x1={from[0]} x2={to[0]} y1={from[1]} y2={to[1]} />)}
                    {coordinates.map((coordinate, index) => coordinate === null ? null : (
                      <circle
                        className={chronological[index].run_id === effectiveSelectedRunId ? "is-selected" : undefined}
                        cx={coordinate[0]}
                        cy={coordinate[1]}
                        key={chronological[index].run_id}
                        r="3"
                      />
                    ))}
                  </svg>
                )}
                <ol
                  aria-label="Sealed snapshot history"
                  className="metric-history__snapshots"
                  onKeyDown={(event) => moveRovingFocus(event, (index) => {
                    const point = points[index];
                    if (point !== undefined) history.onSelectRun(point.run_id);
                  })}
                >
                  {points.map((point, index) => {
                    const current = point.run_id === history.headRunId;
                    const selected = point.run_id === effectiveSelectedRunId;
                    const receipt = historyReceiptLabel(point, metricKey, direction);
                    const identity = shortIdentity(point.run_id);
                    const pointDescriptionId = `${descriptionId}-snapshot-${index}`;
                    return (
                      <li key={point.run_id}>
                        <button
                          aria-describedby={`${pointDescriptionId}-heading ${pointDescriptionId}-identity ${pointDescriptionId}-receipt ${pointDescriptionId}-comparison`}
                          aria-label={current ? "Open live snapshot" : `Open earlier snapshot ${index + 1}`}
                          aria-pressed={selected}
                          data-receipt-kind={receipt.kind}
                          onClick={() => history.onSelectRun(point.run_id)}
                          title={`Run ${point.run_id}`}
                          type="button"
                        >
                          <span className="metric-history__snapshot-heading" id={`${pointDescriptionId}-heading`}>
                            <strong>{snapshotName(point, current)}</strong>
                            {selected && <em>Selected</em>}
                          </span>
                          <code id={`${pointDescriptionId}-identity`}>run {identity}</code>
                          <small className="metric-history__receipt" id={`${pointDescriptionId}-receipt`}>{receipt.text}</small>
                          <small className="metric-history__comparability" id={`${pointDescriptionId}-comparison`}>
                            {current ? "Current comparison baseline" : point.comparable_to_head ? "Comparable to current" : "Scope break · not comparable"}
                          </small>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </>
            )}
          </>
        )}
      </div>
    </details>
  );
}
