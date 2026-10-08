import { useMemo } from "react";
import type { TeamAggregateSnapshot } from "../../shared/api/teamControlPlane";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import {
  MetricExplainerCardSlot,
  MetricExplainerDescriptions,
  metricExplainerTriggerProps,
  type MetricExplainerEntry,
} from "../model-ensemble/MetricExplainer";
import {
  useMetricKnowledgeCardController,
  type MetricKnowledgeSurface,
} from "../model-ensemble/MetricKnowledgeCard";
import {
  MODEL_ENSEMBLE_LENSES,
  type ModelEnsembleLensId,
} from "../model-ensemble/metricAxisModel";
import {
  percent,
  teamMetricRowContext,
  teamMetricRowsForLens,
  teamSnapshotSummary,
  type TeamMetricRow,
} from "./teamAggregatePresentation";
import { shortUtcDate } from "./teamAnalyticsCopy";

/**
 * Per-axis interval bar. Each metric is its own construct, so intervals are
 * drawn as separate horizontal bands and never connected into a polygon. A
 * measured band and an experimental band share the axis but stay visually and
 * semantically distinct. Non-numeric states are written in a state lane beside
 * an empty track; they are never drawn at zero.
 */
function IntervalBar({ row, compact }: { row: TeamMetricRow; compact: boolean }) {
  const left = (value: number) => `${Math.round(value * 1000) / 10}%`;
  const width = (low: number, high: number) => `${Math.max(0, Math.round((high - low) * 1000) / 10)}%`;
  return (
    <div aria-hidden="true" className={`team-interval${compact ? " team-interval--compact" : ""}`} data-status={row.status}>
      <span className="team-interval__track">
        {row.interval !== null && (
          <i
            className="team-interval__band"
            style={{ left: left(row.interval.low), width: width(row.interval.low, row.interval.high) }}
          />
        )}
        {row.radarQuality !== null && (
          <i
            className={`team-interval__point${row.explicitZero ? " team-interval__point--zero" : ""}`}
            style={{ left: left(row.radarQuality) }}
          />
        )}
        {row.experimentalRange !== null && (
          <i
            className="team-interval__model-band"
            style={{ left: left(row.experimentalRange.low), width: width(row.experimentalRange.low, row.experimentalRange.high) }}
          />
        )}
        {row.experimentalMedian !== null && (
          <i className="team-interval__model-point" style={{ left: left(row.experimentalMedian) }} />
        )}
      </span>
      {row.radarQuality === null && <span className="team-interval__state">{row.statusLabel}</span>}
    </div>
  );
}

function condensedFacets(row: TeamMetricRow): string {
  const measured = row.measured;
  if (measured === null) return "no aggregate record";
  const withValue = measured.missingness.members_with_value;
  const inCohort = measured.missingness.members_in_cohort;
  const members = withValue === null || inCohort === null ? "member coverage unavailable" : `${withValue}/${inCohort} members`;
  const comparability = measured.comparability.state === "comparable" ? "comparable" : "not comparable";
  const freshness = measured.freshness.newest_receipt_at === null
    ? "no receipt dates"
    : `newest ${shortUtcDate(measured.freshness.newest_receipt_at)}`;
  return `${members} · ${comparability} · ${freshness}`;
}

function experimentalNote(row: TeamMetricRow): string | null {
  if (row.experimentalMedian === null) return null;
  const range = row.experimentalRange === null
    ? ""
    : ` · central 90% ${percent(row.experimentalRange.low)}–${percent(row.experimentalRange.high)}`;
  return `◇ ${percent(row.experimentalMedian)} experimental radar-quality median${range} · model judgment, not measured`;
}

export function TeamAggregateBoard({
  snapshot,
  lensId,
  mode,
  surface = mode === "full" ? "team-board" : "team-compact",
}: {
  snapshot: TeamAggregateSnapshot;
  lensId: ModelEnsembleLensId;
  mode: "full" | "compact";
  surface?: MetricKnowledgeSurface;
}) {
  const rows = useMemo(() => teamMetricRowsForLens(snapshot, lensId), [lensId, snapshot]);
  const summary = useMemo(() => teamSnapshotSummary(snapshot), [snapshot]);
  const lens = MODEL_ENSEMBLE_LENSES.find((candidate) => candidate.id === lensId);
  const explainerContextIdentity = `${snapshot.request.query_id.length}:${snapshot.request.query_id}:${snapshot.generated_at}`;
  const explainer = useMetricKnowledgeCardController(explainerContextIdentity);
  const entries: MetricExplainerEntry[] = rows.map((row) => ({
    key: row.key,
    label: row.label,
    provenance: row.explainerProvenance,
    numericValue: row.explainerValue,
    valueLabel: row.valueLabel,
    state: row.status === "suppressed"
      ? "suppressed"
      : row.status === "withheld"
        ? "withheld"
        : row.status,
    direction: row.direction,
    numerator: row.measured?.numerator ?? null,
    denominator: row.measured?.denominator ?? null,
    explanationCode: row.measured?.value_state ?? "aggregate_record_missing",
    evidenceAuthority: row.measured?.provenance === "measured_typed"
      ? "Exact aggregate of versioned typed receipts; transcript prose and model estimates cannot establish the measured value."
      : row.experimental !== null
        ? "Experimental model range only; it is not measured evidence."
        : "No aggregate evidence authority was published for this row.",
    suppressionReason: row.measured?.suppression_reason ?? null,
    comparabilityState: row.measured?.comparability.state ?? null,
    context: teamMetricRowContext(snapshot, row),
  }));
  const compact = mode === "compact";
  const boardLabel = `${lens?.label ?? "Metric"} · ${snapshot.cohort_label} · aggregate only`;

  return (
    <div
      className={`team-aggregate-board team-aggregate-board--${mode}`}
      data-origin={snapshot.origin}
      data-scope={snapshot.scope}
    >
      <MetricExplainerDescriptions controller={explainer} entries={entries} surface={surface} />
      {compact ? (
        <ul
          aria-label={boardLabel}
          className="team-aggregate-list"
          onKeyDown={(event) => moveRovingFocus(event)}
        >
          {rows.map((row) => {
            const note = experimentalNote(row);
            return (
              <li data-status={row.status} key={row.key}>
                <button
                  {...metricExplainerTriggerProps(explainer, surface, row.key)}
                  data-provenance={row.explainerProvenance}
                  onClick={() => explainer.togglePin({ surface, metricKey: row.key })}
                  type="button"
                >
                  <span>{row.shortLabel}</span>
                  <b>{row.valueLabelCompact}</b>
                </button>
                <IntervalBar compact row={row} />
                <small>{condensedFacets(row)}</small>
                {note === null ? null : <small className="team-aggregate-list__model">{note}</small>}
              </li>
            );
          })}
        </ul>
      ) : (
        <table className="team-aggregate-table">
          <caption>
            <strong>{lens?.label ?? "Metrics"}</strong>
            <span>
              {summary.measured} measured · {summary.stateOnly} state-only · {summary.experimental} experimental range{summary.experimental === 1 ? "" : "s"}
              {summary.suppressed > 0 ? ` · ${summary.suppressed} suppressed` : ""} · exact cohort fractions, no member ranking
            </span>
          </caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Value &amp; uncertainty</th>
              <th scope="col">Cohort</th>
              <th scope="col">Missingness</th>
              <th scope="col">Comparability</th>
              <th scope="col">Freshness</th>
            </tr>
          </thead>
          <tbody onKeyDown={(event) => moveRovingFocus(event)}>
            {rows.map((row) => {
              const note = experimentalNote(row);
              return (
                <tr data-status={row.status} key={row.key}>
                  <th scope="row">
                    <button
                      {...metricExplainerTriggerProps(explainer, surface, row.key)}
                      data-provenance={row.explainerProvenance}
                      onClick={() => explainer.togglePin({ surface, metricKey: row.key })}
                      type="button"
                    >
                      <strong>{row.label}</strong>
                      <small>{row.statusLabel} · definition v{row.definitionVersion}</small>
                    </button>
                  </th>
                  <td>
                    <b>{row.valueLabel}</b>
                    <IntervalBar compact={false} row={row} />
                    <small>{row.uncertaintyLabel}</small>
                    {note === null ? null : <small className="team-aggregate-table__model">{note}</small>}
                  </td>
                  <td>{row.cohortLabel}</td>
                  <td>{row.missingnessLabel}</td>
                  <td>{row.comparabilityLabel}</td>
                  <td>{row.freshnessLabel}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <MetricExplainerCardSlot compact={compact} controller={explainer} entries={entries} surface={surface} />
    </div>
  );
}
