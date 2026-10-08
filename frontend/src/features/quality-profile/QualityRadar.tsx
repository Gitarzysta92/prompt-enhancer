import { useEffect, useId, useMemo, useState } from "react";
import type { MetricReadiness } from "../../shared/api/contracts";
import { formatPercent } from "../../shared/lib/format";
import type {
  QualityMetricObservation,
  QualityMetricState,
} from "./qualityProfile";
import {
  qualityLensesFor,
  type QualityLensDefinition,
  type QualityLensId,
  type ResolvedQualityLens,
} from "./qualityLenses";
import { metricDecisionGuidance } from "./metricGuidance";
import {
  explainMetricReadiness,
  indexMetricReadiness,
} from "./metricReadiness";
import "./QualityRadar.css";

const CENTER = 280;
const RADIUS = 192;
const LABEL_RADIUS = 242;
const MIN_RADAR_AXES = 3;
const MAX_RADAR_AXES = 8;
const COVERAGE_RING_RADIUS = 10;
const COVERAGE_RING_CIRCUMFERENCE = 2 * Math.PI * COVERAGE_RING_RADIUS;

const STATE_LABELS: Record<QualityMetricState, string> = {
  observed: "Measured",
  partial: "Partial input",
  "not-selected": "Not selected",
  incompatible: "Incompatible",
  unavailable: "Unknown",
  abstained: "Not measurable",
  "not-applicable": "Not applicable",
  "execution-error": "Execution error",
};

function clampRatio(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function hasValidFraction(metric: QualityMetricObservation): boolean {
  return (
    metric.fractionNumerator !== null &&
    metric.fractionDenominator !== null &&
    Number.isSafeInteger(metric.fractionNumerator) &&
    Number.isSafeInteger(metric.fractionDenominator) &&
    metric.fractionNumerator >= 0 &&
    metric.fractionDenominator > 0 &&
    metric.fractionNumerator <= metric.fractionDenominator
  );
}

function hasValidCoverage(metric: QualityMetricObservation): boolean {
  return (
    Number.isSafeInteger(metric.observed) &&
    Number.isSafeInteger(metric.eligible) &&
    metric.observed >= 0 &&
    metric.eligible > 0 &&
    metric.observed <= metric.eligible &&
    Number.isFinite(metric.coverage) &&
    metric.coverage >= 0 &&
    metric.coverage <= 1
  );
}

function point(index: number, count: number, radius: number) {
  const angle = -Math.PI / 2 + (index * Math.PI * 2) / count;
  return {
    x: CENTER + Math.cos(angle) * radius,
    y: CENTER + Math.sin(angle) * radius,
  };
}

function profilePoints(metrics: readonly QualityMetricObservation[]): string {
  return metrics
    .map((metric, index) => {
      const coordinate = point(
        index,
        metrics.length,
        RADIUS * clampRatio(metric.ratio!),
      );
      return `${coordinate.x},${coordinate.y}`;
    })
    .join(" ");
}

export function radarRingPoints(count: number, ratio: number): string {
  return Array.from({ length: count }, (_, index) => {
    const coordinate = point(index, count, RADIUS * ratio);
    return `${coordinate.x},${coordinate.y}`;
  }).join(" ");
}

function fullFraction(metric: QualityMetricObservation): string {
  if (!hasValidFraction(metric)) {
    return "No fraction was produced for this state.";
  }
  return `${metric.fractionNumerator} of ${metric.fractionDenominator}`;
}

function coverageLabel(metric: QualityMetricObservation): string {
  if (metric.eligible === 0) return "No eligible input";
  if (!hasValidCoverage(metric)) return "Coverage unavailable";
  return `${metric.observed}/${metric.eligible} usable · ${formatPercent(metric.coverage)}`;
}

function compactFraction(metric: QualityMetricObservation): string {
  if (!hasValidFraction(metric)) {
    return "unavailable";
  }
  return `${metric.fractionNumerator}/${metric.fractionDenominator}`;
}

function coverageRingDasharray(metric: QualityMetricObservation): string {
  const covered =
    COVERAGE_RING_CIRCUMFERENCE *
    (hasValidCoverage(metric) ? clampRatio(metric.coverage) : 0);
  return `${covered} ${COVERAGE_RING_CIRCUMFERENCE}`;
}

function directionLabel(metric: QualityMetricObservation): string {
  return metric.definition.direction === "lower_is_better"
    ? "Lower is better; the persisted value is not inverted."
    : "Higher is better.";
}

function analysisMode(metric: QualityMetricObservation): string {
  if (metric.modelId !== null) return "Local model-assisted analysis";
  if (metric.algorithmId !== null) return "Deterministic local analysis; no model";
  return "Analysis method provenance unavailable";
}

function calibrationLabel(metric: QualityMetricObservation): string {
  if (metric.confidence === null) {
    return "Not calibrated; confidence unavailable.";
  }
  return `Calibration not reported; recorded confidence ${formatPercent(metric.confidence)}.`;
}

function hasMeasuredNumericValue(metric: QualityMetricObservation): boolean {
  return (
    (metric.state === "observed" || metric.state === "partial") &&
    metric.ratio !== null &&
    Number.isFinite(metric.ratio) &&
    metric.ratio >= 0 &&
    metric.ratio <= 1
  );
}

function normalizedValueLabel(metric: QualityMetricObservation): string {
  if (hasMeasuredNumericValue(metric)) {
    return `${formatPercent(clampRatio(metric.ratio!))} candidate ratio`;
  }
  return {
    "not-selected": "No value — Not selected",
    incompatible: "No value — Incompatible provenance",
    unavailable: "No value — Unknown",
    abstained: "No value — analyzer abstained",
    "not-applicable": "No value — Not applicable",
    "execution-error": "No value — analysis failed",
    observed: "No valid normalized value",
    partial: "No valid normalized value",
  }[metric.state];
}

function exactValueStateLabel(metric: QualityMetricObservation): string {
  if (hasMeasuredNumericValue(metric)) return formatPercent(metric.ratio!);
  return {
    "not-selected": "Not selected",
    incompatible: "Incompatible",
    unavailable: "Unknown",
    abstained: "Abstained",
    "not-applicable": "Not applicable",
    "execution-error": "Failed",
    observed: "Invalid value",
    partial: "Invalid value",
  }[metric.state];
}

function methodRevisionLabel(metric: QualityMetricObservation): string {
  return metric.algorithmVersion === null
    ? "Method revision unavailable"
    : `Method revision ${metric.algorithmVersion}`;
}

function candidateCaveat(metric: QualityMetricObservation): string | null {
  if (!hasMeasuredNumericValue(metric)) return null;
  if (metric.ratio === 0) {
    return "Measured zero; the rule ran and found no counted candidates.";
  }
  if (metric.ratio === 1) {
    return "Full rule match; not proof of task quality.";
  }
  if (
    metric.fractionDenominator !== null &&
    metric.fractionDenominator <= 4
  ) {
    return "Limited evidence base.";
  }
  return null;
}

function labelAnchor(x: number): "start" | "middle" | "end" {
  if (x < CENTER - 20) return "end";
  if (x > CENTER + 20) return "start";
  return "middle";
}

function labelPoint(index: number, count: number) {
  const coordinate = point(index, count, LABEL_RADIUS);
  return {
    x: Math.max(72, Math.min(488, coordinate.x)),
    y: Math.max(52, Math.min(506, coordinate.y)),
  };
}

function isRadarMetric(metric: QualityMetricObservation): boolean {
  return (
    hasMeasuredNumericValue(metric) &&
    metric.definition.polarity !== "review-load" &&
    metric.definition.direction === "higher_is_better"
  );
}

export function radarMetricsFor(
  metrics: readonly QualityMetricObservation[],
): readonly QualityMetricObservation[] {
  return metrics.filter(isRadarMetric).slice(0, MAX_RADAR_AXES);
}

function RadarPlot({
  activeKey,
  descriptionId,
  metrics,
  onPin,
  onPreviewEnd,
  onPreviewStart,
}: {
  activeKey: string | null;
  descriptionId: string;
  metrics: readonly QualityMetricObservation[];
  onPin: (key: string) => void;
  onPreviewEnd: (key: string) => void;
  onPreviewStart: (key: string) => void;
}) {
  const points = profilePoints(metrics);
  return (
    <figure className="quality-radar">
      <svg
        aria-describedby={descriptionId}
        aria-label={`${metrics.length}-axis ${formatPercent(1)} fixed-scale quality lens radar`}
        className="quality-radar__plot"
        role="img"
        viewBox="0 0 560 560"
      >
        <desc id={descriptionId}>
          Every plotted axis uses a fixed zero-to-one-hundred-percent scale.
          Unknown and lower-is-better metrics are omitted. A measured zero is
          plotted at the center. The ring around each point shows usable input
          coverage. The shape is not a combined score.
        </desc>

        {[0.25, 0.5, 0.75, 1].map((ring) => (
          <g key={ring}>
            <polygon
              className="quality-radar__ring"
              data-radar-ring={formatPercent(ring)}
              points={radarRingPoints(metrics.length, ring)}
            />
            <text
              aria-hidden="true"
              className="quality-radar__scale"
              x={CENTER + 7}
              y={CENTER - RADIUS * ring + 11}
            >
              {formatPercent(ring)}
            </text>
          </g>
        ))}
        <text
          aria-hidden="true"
          className="quality-radar__scale quality-radar__scale--zero"
          x={CENTER + 7}
          y={CENTER + 12}
        >
          {formatPercent(0)}
        </text>

        {metrics.map((metric, index) => {
          const end = point(index, metrics.length, RADIUS);
          const label = labelPoint(index, metrics.length);
          const value = point(
            index,
            metrics.length,
            RADIUS * clampRatio(metric.ratio!),
          );
          return (
            <g
              aria-hidden="true"
              className="quality-radar__axis-control"
              key={metric.definition.key}
              onClick={() => onPin(metric.definition.key)}
              onMouseEnter={() => onPreviewStart(metric.definition.key)}
              onMouseLeave={() => onPreviewEnd(metric.definition.key)}
            >
              <line
                className="quality-radar__axis"
                x1={CENTER}
                x2={end.x}
                y1={CENTER}
                y2={end.y}
              />
              <line
                aria-hidden="true"
                className="quality-radar__axis-hit"
                x1={CENTER}
                x2={end.x}
                y1={CENTER}
                y2={end.y}
              />
              <text
                aria-hidden="true"
                className="quality-radar__label"
                textAnchor={labelAnchor(label.x)}
                x={label.x}
                y={label.y - 4}
              >
                <tspan x={label.x}>{metric.definition.shortLabel}</tspan>
                <tspan className="quality-radar__label-value" dy="15" x={label.x}>
                  {formatPercent(clampRatio(metric.ratio!))}
                </tspan>
                <tspan className="quality-radar__label-fraction" dy="14" x={label.x}>
                  {compactFraction(metric)}
                </tspan>
              </text>
            </g>
          );
        })}

        {metrics.length >= 3 ? (
          <polygon
            aria-hidden="true"
            className="quality-radar__profile"
            data-filled-profile="true"
            points={points}
          />
        ) : metrics.length === 2 ? (
          <polyline
            aria-hidden="true"
            className="quality-radar__profile quality-radar__profile--open"
            data-open-profile="true"
            points={points}
          />
        ) : null}

        {metrics.map((metric, index) => {
          const value = point(
            index,
            metrics.length,
            RADIUS * clampRatio(metric.ratio!),
          );
          return (
            <g aria-hidden="true" key={`${metric.definition.key}-visible-point`}>
              <circle
                className={
                  !hasValidCoverage(metric) ||
                  metric.coverage < 1 ||
                  metric.state === "partial"
                    ? "quality-radar__coverage-ring quality-radar__coverage-ring--partial"
                    : "quality-radar__coverage-ring"
                }
                cx={value.x}
                cy={value.y}
                data-input-coverage={
                  hasValidCoverage(metric)
                    ? formatPercent(metric.coverage)
                    : "unavailable"
                }
                r={COVERAGE_RING_RADIUS}
                strokeDasharray={coverageRingDasharray(metric)}
                transform={`rotate(-90 ${value.x} ${value.y})`}
              />
              <circle
                className={
                  metric.definition.key === activeKey
                    ? "quality-radar__point quality-radar__point--active"
                    : "quality-radar__point"
                }
                cx={value.x}
                cy={value.y}
                r={metric.definition.key === activeKey ? 7 : 5}
              />
            </g>
          );
        })}
      </svg>
      <figcaption>
        Position shows the candidate ratio; the fraction sits below each label,
        and the ring around each point shows usable input coverage. Every axis is
        fixed at 0-100%. Unknown values are omitted, measured zero remains at the
        center, and no combined score is calculated.
      </figcaption>
    </figure>
  );
}

function MetricInspector({
  lens,
  metric,
  onClear,
  pinned,
  readiness,
}: {
  lens: QualityLensDefinition;
  metric: QualityMetricObservation;
  onClear: () => void;
  pinned: boolean;
  readiness?: MetricReadiness;
}) {
  const guidance = metricDecisionGuidance(metric.definition.key);
  const readinessExplanation = explainMetricReadiness(metric, readiness);
  return (
    <aside
      aria-live={pinned ? "polite" : "off"}
      className={
        pinned
          ? "quality-radar__inspector quality-radar__inspector--pinned"
          : "quality-radar__inspector"
      }
    >
      <header>
        <div>
          <p className="eyebrow">{pinned ? "Pinned metric" : "Axis inspector"}</p>
          <h4>{metric.definition.label}</h4>
        </div>
        {pinned && (
          <button className="quality-radar__clear" onClick={onClear} type="button">
            Clear pin
          </button>
        )}
      </header>
      <p className="quality-radar__inspector-question">
        {metric.definition.question}
      </p>
      <div className="quality-radar__inspector-result">
        <strong>{normalizedValueLabel(metric)}</strong>
        <span className={`quality-board__state quality-board__state--${metric.state}`}>
          {STATE_LABELS[metric.state]}
        </span>
      </div>
      {candidateCaveat(metric) && (
        <p className="quality-radar__inspector-caveat">
          {candidateCaveat(metric)}
        </p>
      )}
      {readinessExplanation !== null && (
        <section
          aria-label="Metric readiness explanation"
          className={`quality-readiness quality-readiness--${readinessExplanation.state}`}
          data-readiness-state={readinessExplanation.state}
        >
          <strong>{readinessExplanation.label}</strong>
          <p>{readinessExplanation.reasonCopy}</p>
          <p>
            <b>Evidence</b>
            {readinessExplanation.evidenceCopy}
          </p>
          <p>
            <b>Next</b>
            {readinessExplanation.actionCopy.join(" ")}
          </p>
        </section>
      )}
      <dl className="quality-radar__inspector-summary">
        <div>
          <dt>Raw fraction</dt>
          <dd>{fullFraction(metric)}</dd>
        </div>
        <div>
          <dt>Input coverage</dt>
          <dd>{coverageLabel(metric)}</dd>
        </div>
        {metric.notSelectedRuns > 0 && (
          <div>
            <dt>Scope omissions</dt>
            <dd>{metric.notSelectedRuns} completed run{metric.notSelectedRuns === 1 ? "" : "s"}; excluded, not failed</dd>
          </div>
        )}
        {metric.unknownScopeRuns > 0 && (
          <div>
            <dt>Legacy scope unknown</dt>
            <dd>{metric.unknownScopeRuns} completed run{metric.unknownScopeRuns === 1 ? "" : "s"}; absence is not classified as failed</dd>
          </div>
        )}
      </dl>
      <section
        aria-label="Decision guidance"
        className="quality-radar__decision-guidance"
      >
        <span>{guidance.role}</span>
        <p>
          <strong>Why it matters</strong>
          {guidance.whyItMatters}
        </p>
        <p>
          <strong>Review next</strong>
          {guidance.reviewNext}
        </p>
        <div className="quality-radar__decision-actions">
          <p>
            <strong>Try next</strong>
            {guidance.tryNext}
          </p>
          <p>
            <strong>Confirm with</strong>
            {guidance.confirmWith}
          </p>
        </div>
      </section>
      <details className="quality-radar__inspector-details">
        <summary>Method &amp; limits</summary>
        <dl>
          <div>
            <dt>Direction</dt>
            <dd>{directionLabel(metric)}</dd>
          </div>
          <div className="quality-radar__inspector-wide">
            <dt>Method</dt>
            <dd>{metric.definition.method}</dd>
          </div>
          <div>
            <dt>Analysis mode</dt>
            <dd>{analysisMode(metric)}</dd>
          </div>
          <div>
            <dt>Method provenance</dt>
            <dd>
              Definition v{metric.definition.version}; {methodRevisionLabel(metric)}
            </dd>
          </div>
          <div>
            <dt>Calibration</dt>
            <dd>{calibrationLabel(metric)}</dd>
          </div>
          <div className="quality-radar__inspector-wide">
            <dt>Interpretation limit</dt>
            <dd>{metric.definition.limitation}</dd>
          </div>
        </dl>
        <p className="quality-radar__inspector-boundary">{lens.boundary}</p>
      </details>
    </aside>
  );
}

function ExactValueFallback({
  metrics,
  totalMetricCount,
}: {
  metrics: readonly QualityMetricObservation[];
  totalMetricCount: number;
}) {
  return (
    <figure
      aria-label="Exact-value bar fallback"
      className="quality-radar__fallback"
    >
      <figcaption>
        <strong>Radar withheld · exact-value bars</strong>
        <span>
          {metrics.length} of {totalMetricCount} metrics are compatible numeric
          higher-is-better axes. A radar needs at least three. These aligned bars
          keep the fixed 0-100% scale; review-load and non-measured states remain
          in the exact-value board.
        </span>
      </figcaption>
      {metrics.length > 0 ? (
        <div
          aria-label="Compatible exact-value bars"
          className="quality-radar__fallback-bars"
          role="list"
        >
          {metrics.map((metric) => {
            const ratio = clampRatio(metric.ratio!);
            return (
              <div
                aria-label={`${metric.definition.label}: ${formatPercent(ratio)}, raw ${compactFraction(metric)}`}
                className="quality-radar__fallback-row"
                key={metric.definition.key}
                role="listitem"
              >
                <span className="quality-radar__fallback-label">
                  {metric.definition.shortLabel}
                </span>
                <span aria-hidden="true" className="quality-radar__fallback-track">
                  <span
                    data-exact-value={formatPercent(ratio)}
                    style={{ width: `${ratio * 100}%` }}
                  />
                </span>
                <strong>{formatPercent(ratio)}</strong>
                <small>{compactFraction(metric)}</small>
              </div>
            );
          })}
        </div>
      ) : (
        <p>
          No compatible numeric higher-is-better value is available for this
          lens. Use the exact-value board for the recorded states and evidence.
        </p>
      )}
    </figure>
  );
}

function MetricBoard({
  activeKey,
  lens,
  onClear,
  onPin,
  onPreviewEnd,
  onPreviewStart,
  pinnedKey,
  readiness,
}: {
  activeKey: string | null;
  lens: ResolvedQualityLens;
  onClear: () => void;
  onPin: (key: string) => void;
  onPreviewEnd: (key: string) => void;
  onPreviewStart: (key: string) => void;
  pinnedKey: string | null;
  readiness: ReadonlyMap<string, MetricReadiness>;
}) {
  const measured = lens.metrics.filter(hasMeasuredNumericValue).length;
  const compatibilityRegion =
    lens.definition.dimension === "prompt"
      ? "Prompt-quality candidates"
      : `${lens.definition.label} metric candidates`;
  return (
    <section aria-label={compatibilityRegion} className="quality-board">
      <header className="quality-board__header">
        <div>
          <p className="eyebrow">Authoritative values</p>
          <h3>Metrics</h3>
        </div>
        <p className="quality-board__summary">
          {measured}/{lens.metrics.length} measured · v{lens.definition.version}
        </p>
      </header>
      <div
        aria-label={`${lens.definition.label} metrics`}
        className="quality-board__grid"
        role="region"
      >
        {lens.metrics.map((metric) => {
          const hasValue = hasMeasuredNumericValue(metric);
          const percentage = hasValue ? clampRatio(metric.ratio!) * 100 : null;
          const risk = metric.definition.direction === "lower_is_better";
          const active = metric.definition.key === activeKey;
          const pinned = metric.definition.key === pinnedKey;
          const caveat = candidateCaveat(metric);
          const metricReadiness = readiness.get(
            `${metric.definition.key}@${metric.definition.version}`,
          );
          const readinessExplanation = explainMetricReadiness(metric, metricReadiness);
          return (
            <button
              aria-pressed={pinned}
              className={[
                "quality-board__metric",
                risk ? "quality-board__metric--risk" : "",
                hasValue ? "" : "quality-board__metric--missing",
                active ? "quality-board__metric--active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={metric.definition.key}
              onBlur={() => onPreviewEnd(metric.definition.key)}
              onClick={() => onPin(metric.definition.key)}
              onFocus={() => onPreviewStart(metric.definition.key)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  onClear();
                }
              }}
              onMouseEnter={() => onPreviewStart(metric.definition.key)}
              onMouseLeave={() => onPreviewEnd(metric.definition.key)}
              type="button"
            >
              <span className="quality-board__metric-heading">
                <span className="quality-board__title">
                  <strong>{metric.definition.label}</strong>
                  {risk && <small>Lower is better; raw value</small>}
                </span>
                <span className="quality-board__metric-meta">
                  <span
                    className={`quality-board__state quality-board__state--${metric.state}`}
                  >
                    {STATE_LABELS[metric.state]}
                  </span>
                  <b>{exactValueStateLabel(metric)}</b>
                </span>
              </span>
              {hasValue ? (
                <span
                  aria-hidden="true"
                  className="quality-board__track"
                >
                  <span style={{ width: `${percentage}%` }} />
                </span>
              ) : (
                <span
                  aria-hidden="true"
                  className="quality-board__track quality-board__track--missing"
                />
              )}
              <span className="quality-board__basis">
                <span>Raw {compactFraction(metric)}</span>
                <small>Input {coverageLabel(metric)}</small>
                {metric.notSelectedRuns > 0 && (
                  <small>{metric.notSelectedRuns} run{metric.notSelectedRuns === 1 ? "" : "s"} omitted by selected scope; not missing or failed</small>
                )}
                {metric.unknownScopeRuns > 0 && (
                  <small>{metric.unknownScopeRuns} legacy run{metric.unknownScopeRuns === 1 ? "" : "s"} without a metric-scope receipt; not classified as failed</small>
                )}
                {caveat && <small>{caveat}</small>}
              </span>
              {readinessExplanation !== null && (
                <span
                  className={`quality-board__readiness quality-board__readiness--${readinessExplanation.state}`}
                  data-readiness-state={readinessExplanation.state}
                >
                  <strong>{readinessExplanation.label}</strong>
                  <small>{readinessExplanation.compactReasonCopy}</small>
                  <small>
                    <b>Needed / next:</b> {readinessExplanation.compactEvidenceCopy}{" "}
                    {readinessExplanation.compactActionCopy}
                  </small>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}

interface QualityRadarProps {
  metrics: readonly QualityMetricObservation[];
  readiness?: readonly MetricReadiness[] | null;
  /** Stable, content-free owner identity supplied by an exact host context. */
  contextIdentity?: string;
}

function numericOwnerIdentity(value: number | null): readonly [string, number?] {
  if (value === null) return ["null"];
  if (Number.isNaN(value)) return ["nan"];
  if (value === Number.POSITIVE_INFINITY) return ["positive-infinity"];
  if (value === Number.NEGATIVE_INFINITY) return ["negative-infinity"];
  if (Object.is(value, -0)) return ["negative-zero"];
  return ["finite", value];
}

function qualityRadarIdentity(
  metrics: readonly QualityMetricObservation[],
  readiness: readonly MetricReadiness[] | null | undefined,
): string {
  return JSON.stringify({
    metrics: metrics.map((metric) => ({
      key: metric.definition.key,
      version: metric.definition.version,
      direction: metric.definition.direction,
      state: metric.state,
      ratio: numericOwnerIdentity(metric.ratio),
      numerator: numericOwnerIdentity(metric.fractionNumerator),
      denominator: numericOwnerIdentity(metric.fractionDenominator),
      observed: numericOwnerIdentity(metric.observed),
      eligible: numericOwnerIdentity(metric.eligible),
      coverage: numericOwnerIdentity(metric.coverage),
      notSelectedRuns: numericOwnerIdentity(metric.notSelectedRuns),
      unknownScopeRuns: numericOwnerIdentity(metric.unknownScopeRuns),
      schema: metric.metricSchemaVersion,
      explanation: metric.explanationCode,
      algorithm: metric.algorithmId,
      algorithmVersion: metric.algorithmVersion,
      model: metric.modelId,
      error: metric.errorCode,
      definitionVersion: metric.definitionVersion,
      computedAt: metric.computedAt,
      signals: metric.signals.map((signal) => [
        signal.code,
        signal.status,
        numericOwnerIdentity(signal.count),
      ]),
    })),
    readiness: (readiness ?? []).map((metric) => ({
      key: metric.metric_key,
      version: metric.metric_version,
      state: metric.state,
      reason: metric.reason_code,
      run: metric.latest_run_id,
      missing: metric.missing_capabilities,
      actions: metric.next_actions,
    })),
  });
}

export function QualityRadar(props: QualityRadarProps) {
  const contextIdentity =
    props.contextIdentity ?? qualityRadarIdentity(props.metrics, props.readiness);
  return <QualityRadarOwned key={contextIdentity} {...props} />;
}

function QualityRadarOwned({
  metrics,
  readiness,
}: QualityRadarProps) {
  const descriptionId = useId();
  const titleId = useId();
  const lenses = useMemo(() => qualityLensesFor(metrics), [metrics]);
  const readinessIndex = useMemo(() => indexMetricReadiness(readiness), [readiness]);
  const [selectedLensId, setSelectedLensId] = useState<QualityLensId | null>(
    () => lenses[0]?.definition.id ?? null,
  );
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);

  const selectedLens =
    lenses.find((lens) => lens.definition.id === selectedLensId) ?? lenses[0] ?? null;

  useEffect(() => {
    if (
      lenses.length > 0 &&
      !lenses.some((lens) => lens.definition.id === selectedLensId)
    ) {
      setSelectedLensId(lenses[0].definition.id);
      setPreviewKey(null);
      setPinnedKey(null);
    }
  }, [lenses, selectedLensId]);

  useEffect(() => {
    if (
      selectedLens !== null &&
      pinnedKey !== null &&
      !selectedLens.metrics.some((metric) => metric.definition.key === pinnedKey)
    ) {
      setPinnedKey(null);
    }
  }, [pinnedKey, selectedLens]);

  if (selectedLens === null) {
    return (
      <section className="quality-radar__empty" role="note">
        <strong>No quality lens is available</strong>
        <span>The supplied profile contains no recognized metric dimension.</span>
      </section>
    );
  }

  const activeKey = pinnedKey ?? previewKey ?? selectedLens.metrics[0]?.definition.key ?? null;
  const activeMetric =
    selectedLens.metrics.find((metric) => metric.definition.key === activeKey) ??
    selectedLens.metrics[0];
  const availableRadarMetrics = selectedLens.metrics.filter(isRadarMetric);
  const radarMetrics = radarMetricsFor(selectedLens.metrics);
  const cappedRadarCount = Math.max(
    0,
    availableRadarMetrics.length - radarMetrics.length,
  );
  const measuredCount = selectedLens.metrics.filter(hasMeasuredNumericValue).length;
  const unknownCount = selectedLens.metrics.filter(
    (metric) => metric.state === "unavailable",
  ).length;
  const notSelectedCount = selectedLens.metrics.filter(
    (metric) => metric.state === "not-selected",
  ).length;
  const incompatibleCount = selectedLens.metrics.filter(
    (metric) => metric.state === "incompatible",
  ).length;
  const abstainedCount = selectedLens.metrics.filter(
    (metric) => metric.state === "abstained",
  ).length;
  const notApplicableCount = selectedLens.metrics.filter(
    (metric) => metric.state === "not-applicable",
  ).length;
  const failedCount = selectedLens.metrics.filter(
    (metric) => metric.state === "execution-error",
  ).length;
  const invalidMeasuredCount = selectedLens.metrics.filter(
    (metric) =>
      (metric.state === "observed" || metric.state === "partial") &&
      !hasMeasuredNumericValue(metric),
  ).length;
  const reviewCount = selectedLens.metrics.filter(
    (metric) =>
      metric.definition.polarity === "review-load" ||
      metric.definition.direction === "lower_is_better",
  ).length;
  const zeroCount = radarMetrics.filter((metric) => metric.ratio === 0).length;
  const radarReady = radarMetrics.length >= MIN_RADAR_AXES;
  const profileTitle =
    selectedLens.definition.dimension === "prompt" ||
    selectedLens.definition.dimension === "collaboration"
      ? "Prompt-signal profile"
      : "Work-signal profile";

  function clearSelection() {
    setPreviewKey(null);
    setPinnedKey(null);
  }

  function selectLens(id: QualityLensId) {
    setSelectedLensId(id);
    setPreviewKey(null);
    setPinnedKey(null);
  }

  return (
    <div
      className="quality-radar-shell"
      onKeyDown={(event) => {
        if (event.key === "Escape") clearSelection();
      }}
    >
      <section aria-labelledby={titleId} className="quality-radar__explorer">
        <header className="quality-radar__header">
          <div>
            <p className="eyebrow">{profileTitle}</p>
            <h3 id={titleId}>{selectedLens.definition.label}</h3>
            <p>{selectedLens.definition.question}</p>
          </div>
        </header>

        {lenses.length > 1 && (
          <div aria-label="Quality lenses" className="quality-radar__lenses" role="group">
            {lenses.map((lens) => (
              <button
                aria-label={`${lens.definition.shortLabel}, ${lens.metrics.length} of ${lens.definition.expectedMetricCount} metrics, lens version ${lens.definition.version}`}
                aria-pressed={lens.definition.id === selectedLens.definition.id}
                key={lens.definition.id}
                onClick={() => selectLens(lens.definition.id)}
                type="button"
              >
                <span>{lens.definition.shortLabel}</span>
                <small>
                  {lens.metrics.length}/{lens.definition.expectedMetricCount} metrics
                </small>
              </button>
            ))}
          </div>
        )}

        <div aria-label="Radar availability">
          <div aria-label="Selected lens availability" className="quality-radar__availability">
            <span><strong>{measuredCount}</strong> measured</span>
            <span><strong>{radarMetrics.length}</strong> plottable axes</span>
            {unknownCount > 0 && <span><strong>{unknownCount}</strong> unknown</span>}
            {notSelectedCount > 0 && <span><strong>{notSelectedCount}</strong> not selected</span>}
            {incompatibleCount > 0 && <span><strong>{incompatibleCount}</strong> incompatible</span>}
            {abstainedCount > 0 && <span><strong>{abstainedCount}</strong> abstained</span>}
            {notApplicableCount > 0 && (
              <span><strong>{notApplicableCount}</strong> not applicable</span>
            )}
            {failedCount > 0 && <span><strong>{failedCount}</strong> failed</span>}
            {invalidMeasuredCount > 0 && (
              <span><strong>{invalidMeasuredCount}</strong> invalid measured value</span>
            )}
            {reviewCount > 0 && <span><strong>{reviewCount}</strong> review-load in exact board</span>}
            {cappedRadarCount > 0 && (
              <span><strong>{cappedRadarCount}</strong> outside the 8-axis cap</span>
            )}
            {zeroCount > 0 && <span><strong>{zeroCount}</strong> measured zero</span>}
            <span>Fixed 0-100%</span>
          </div>
        </div>

        <MetricBoard
          activeKey={activeKey}
          lens={selectedLens}
          onClear={clearSelection}
          onPin={(key) => {
            setPinnedKey(key);
            setPreviewKey(null);
          }}
          onPreviewEnd={(key) =>
            setPreviewKey((current) => (current === key ? null : current))
          }
          onPreviewStart={setPreviewKey}
          pinnedKey={pinnedKey}
          readiness={readinessIndex}
        />

        <div className="quality-radar__workspace quality-radar__workspace--secondary">
          {radarReady ? (
            <RadarPlot
              activeKey={activeKey}
              descriptionId={descriptionId}
              metrics={radarMetrics}
              onPin={(key) => {
                setPinnedKey(key);
                setPreviewKey(null);
              }}
              onPreviewEnd={(key) =>
                setPreviewKey((current) => (current === key ? null : current))
              }
              onPreviewStart={setPreviewKey}
            />
          ) : (
            <ExactValueFallback
              metrics={radarMetrics}
              totalMetricCount={selectedLens.metrics.length}
            />
          )}
          <div className="quality-radar__rail">
            <MetricInspector
              lens={selectedLens.definition}
              metric={activeMetric}
              onClear={clearSelection}
              pinned={pinnedKey === activeMetric.definition.key}
              readiness={readinessIndex.get(
                `${activeMetric.definition.key}@${activeMetric.definition.version}`,
              )}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
