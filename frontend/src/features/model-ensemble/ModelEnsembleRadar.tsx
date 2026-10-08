import { useEffect, useId, useMemo, useState } from "react";
import type { PromptEnhancerTransport } from "../../shared/api/contracts";
import { moveRovingFocus } from "../../shared/ui/rovingFocus";
import type { MetricScopeContext } from "./metricContextFacts";
import {
  MetricKnowledgeCardSlot,
  MetricKnowledgeDescriptions,
  metricKnowledgeCardTriggerProps,
  useMetricKnowledgeCardController,
  type MetricKnowledgeCardController,
} from "./MetricKnowledgeCard";
import {
  MODEL_ENSEMBLE_LENSES,
  MODEL_ENSEMBLE_WITHHELD_LANE_MAGNITUDE,
  isModelEnsembleTypedMetric,
  isModelEnsembleV2Metric,
  modelEnsembleAxisCoverage,
  modelEnsembleAxisGuidanceSentences,
  modelEnsembleAxisPendingBoundsLabel,
  modelEnsembleAxisPlottedLabel,
  modelEnsembleAxisRawRateLabel,
  modelEnsembleDensityBinsForDirection,
  modelEnsembleIsRawExplicitZero,
  modelEnsembleKnowledgeEntries,
  modelEnsembleMetricPresentation,
  modelEnsembleMetricStateLabel,
  modelEnsembleMetricStatus,
  modelEnsembleRadarAxes,
  modelEnsembleRadarMarkerMagnitude,
  modelEnsembleRadarSegments,
  type ModelEnsembleLensId,
  type ModelEnsembleRadarData,
} from "./metricAxisModel";
import {
  readableAdapterCapability,
  readableEvidenceAvailability,
  readableEvidenceContributor,
} from "./metricEvidenceReadiness";
import { usePredictiveMetricDetail } from "./usePredictiveMetricDetail";

/**
 * The pure axis/state model and the keyboard helper used to live in this file.
 * They are re-exported so existing imports keep working; new code should import
 * `./metricAxisModel` and `../../shared/ui/rovingFocus` directly.
 */
export * from "./metricAxisModel";
export { moveRovingFocus } from "../../shared/ui/rovingFocus";

const isTypedMetric = isModelEnsembleTypedMetric;
const stateLabel = modelEnsembleMetricStateLabel;

export function ModelEnsembleRadar({
  run,
  lensId,
  compact = false,
  comparisonRun = null,
  snapshotLabel = "Current snapshot",
  comparisonLabel = "Previous comparable snapshot",
  detailRunId,
  detailTransport,
  selectedMetricKey,
  onSelectedMetricKeyChange,
  helpController,
  contextIdentity,
  scopeContext,
}: {
  run: ModelEnsembleRadarData;
  lensId: ModelEnsembleLensId;
  compact?: boolean;
  comparisonRun?: ModelEnsembleRadarData | null;
  snapshotLabel?: string;
  comparisonLabel?: string;
  detailRunId?: string;
  detailTransport?: Pick<PromptEnhancerTransport, "getModelPredictiveMetricDetail">;
  selectedMetricKey?: string;
  onSelectedMetricKeyChange?: (metricKey: string) => void;
  helpController?: MetricKnowledgeCardController;
  /** Stable, content-free identity of the exact snapshot owning these cards. */
  contextIdentity: string | number;
  /** Analytics scope shown in every knowledge card; defaults to the personal (Me) scope. */
  scopeContext?: MetricScopeContext;
}) {
  const axes = useMemo(() => modelEnsembleRadarAxes(run, lensId), [lensId, run]);
  const comparisonAxes = useMemo(
    () => comparisonRun === null ? null : modelEnsembleRadarAxes(comparisonRun, lensId),
    [comparisonRun, lensId],
  );
  const lens = MODEL_ENSEMBLE_LENSES.find((candidate) => candidate.id === lensId)!;
  const [internalSelectedKey, setInternalSelectedKey] = useState(axes.find((axis) => axis.metric !== null)?.key ?? axes[0]?.key ?? "");
  const selectedKey = selectedMetricKey ?? internalSelectedKey;
  const setSelectedKey = (metricKey: string) => {
    setInternalSelectedKey(metricKey);
    onSelectedMetricKeyChange?.(metricKey);
  };
  useEffect(() => {
    if (!axes.some((axis) => axis.key === selectedKey)) {
      setSelectedKey(axes.find((axis) => axis.metric !== null)?.key ?? axes[0]?.key ?? "");
    }
  }, [axes, selectedKey]);
  const selected = axes.find((axis) => axis.key === selectedKey) ?? axes[0];
  const { detail: predictiveDetail, state: predictiveDetailState } = usePredictiveMetricDetail({
    transport: detailTransport,
    runId: detailRunId,
    axis: selected,
  });
  const size = compact ? 340 : 380;
  const center = size / 2;
  const radius = compact ? 96 : 108;
  const ownHelpController = useMetricKnowledgeCardController(contextIdentity);
  const helpCards = helpController ?? ownHelpController;
  const helpEntries = modelEnsembleKnowledgeEntries(axes, scopeContext);
  const point = (index: number, magnitude: number) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / axes.length;
    return [
      center + Math.cos(angle) * radius * magnitude,
      center + Math.sin(angle) * radius * magnitude,
    ] as const;
  };
  const knownCount = axes.filter((axis) => axis.plotted !== null).length;
  const pendingCount = axes.filter((axis) => modelEnsembleMetricStatus(axis.metric) === "pending").length;
  const explicitZeroCount = axes.filter(modelEnsembleIsRawExplicitZero).length;
  const segments = modelEnsembleRadarSegments(axes);
  const comparisonSegments = comparisonAxes === null ? [] : modelEnsembleRadarSegments(comparisonAxes);
  const selectedPresentation = selected?.metric === null || selected === undefined
    ? { value: "—", detail: "This metric is not present in the current receipt." }
    : modelEnsembleMetricPresentation(selected.metric, selected.direction);
  const chunkTrace = selected === undefined
    ? []
    : run.chunk_metrics
      .filter((metric) => metric.metric_key === selected.key)
      .sort((left, right) => left.chunk_ordinal - right.chunk_ordinal);
  const usesV2Publication = (run.metric_publication_v2 !== undefined && run.metric_publication_v2 !== null)
    || (run.metric_states_v2?.length ?? 0) > 0;
  const usesTypedProjection = usesV2Publication || (run.typed_metrics?.length ?? 0) > 0;
  const selectedCommitteeMetric = selected === undefined
    ? null
    : run.metrics.find((metric) => metric.metric_key === selected.key) ?? null;
  const predictiveCount = axes.filter((axis) => axis.predictiveMedian !== null).length;
  const displayDensityBins = predictiveDetail === null || selected === undefined
    ? []
    : modelEnsembleDensityBinsForDirection(predictiveDetail.density_bins, selected.direction);
  const radarHeadingId = useId();
  const focusedMetricHeadingId = useId();
  const radarCaptionId = useId();

  return (
    <figure
      aria-describedby={compact ? undefined : radarCaptionId}
      aria-labelledby={radarHeadingId}
      className={`model-ensemble__radar${compact ? " model-ensemble__radar--compact" : ""}`}
    >
      <header aria-label={`${lens.label} radar summary`} className="model-ensemble__radar-header" role="group">
        <div>
          <h4 id={radarHeadingId}>{lens.label}</h4>
          <span>
            {snapshotLabel} · {knownCount} numeric · {axes.length - knownCount} state-only
            {pendingCount > 0 ? ` · ${pendingCount} pending` : ""}
            {predictiveCount > 0 ? ` · ${predictiveCount} experimental ranges` : ""}
            {explicitZeroCount > 0 ? ` · ${explicitZeroCount} explicit zero${explicitZeroCount === 1 ? "" : "s"}` : ""}
          </span>
        </div>
        <span className="model-ensemble__radar-coverage">
          {usesV2Publication ? "Canonical V2 measured states" : usesTypedProjection ? "Typed local measurement" : "Legacy committee shadow"} · coverage, not confidence
        </span>
      </header>
      <svg
        aria-label={`${lens.label} ${usesTypedProjection ? "typed local metric" : "legacy shadow model"} radar with fixed axes`}
        role="img"
        viewBox={`0 0 ${size} ${size}`}
      >
        {[0.25, 0.5, 0.75, 1].map((level) => (
          <polygon
            className="model-ensemble__radar-ring"
            key={level}
            points={axes.map((_, index) => point(index, level).join(",")).join(" ")}
          />
        ))}
        {axes.map((axis, index) => {
          if (axis.predictiveQ05 === null || axis.predictiveQ95 === null) return null;
          const low = point(index, axis.predictiveQ05);
          const high = point(index, axis.predictiveQ95);
          const innerLow = point(index, axis.predictiveQ25!);
          const innerHigh = point(index, axis.predictiveQ75!);
          return (
            <g key={`predictive-band-${axis.key}`}>
              <line className="model-ensemble__radar-axis-range model-ensemble__radar-axis-range--90" x1={low[0]} x2={high[0]} y1={low[1]} y2={high[1]} />
              <line className="model-ensemble__radar-axis-range model-ensemble__radar-axis-range--50" x1={innerLow[0]} x2={innerHigh[0]} y1={innerLow[1]} y2={innerHigh[1]} />
            </g>
          );
        })}
        {axes.map((axis, index) => {
          if (axis.predictiveMedian === null) return null;
          const value = point(index, axis.predictiveMedian);
          return <rect
            aria-label={`${axis.label}: experimental radar-quality median`}
            className="model-ensemble__radar-predictive-point"
            height="6"
            key={`predictive-point-${axis.key}`}
            transform={`rotate(45 ${value[0]} ${value[1]})`}
            width="6"
            x={value[0] - 3}
            y={value[1] - 3}
          />;
        })}
        {comparisonAxes !== null && comparisonSegments.map(([fromIndex, toIndex]) => {
          const from = point(fromIndex, comparisonAxes[fromIndex].plotted!);
          const to = point(toIndex, comparisonAxes[toIndex].plotted!);
          return <line className="model-ensemble__radar-prior-segment" key={`prior-${fromIndex}-${toIndex}`} x1={from[0]} x2={to[0]} y1={from[1]} y2={to[1]} />;
        })}
        {comparisonAxes?.map((axis, index) => {
          if (axis.plotted === null) return null;
          const value = point(index, axis.plotted);
          return (
            <rect
              aria-label={`${comparisonLabel}: ${axis.label}`}
              className="model-ensemble__radar-prior-point"
              height="6"
              key={`prior-point-${axis.key}`}
              transform={`rotate(45 ${value[0]} ${value[1]})`}
              width="6"
              x={value[0] - 3}
              y={value[1] - 3}
            />
          );
        })}
        {axes.map((axis, index) => {
          const end = point(index, 1);
          const label = point(index, compact ? 1.3 : 1.32);
          const value = axis.plotted === null ? null : point(index, axis.plotted);
          const marker = point(index, modelEnsembleRadarMarkerMagnitude(axis.plotted));
          const withheld = point(index, MODEL_ENSEMBLE_WITHHELD_LANE_MAGNITUDE);
          const estimateWithheld = axis.prediction !== null && axis.predictiveMedian === null;
          const rawExplicitZero = modelEnsembleIsRawExplicitZero(axis);
          const coverage = modelEnsembleAxisCoverage(axis);
          return (
            <g
              className={axis.key === selected?.key ? "is-selected" : undefined}
              key={axis.key}
            >
              <line className="model-ensemble__radar-axis" x1={center} x2={end[0]} y1={center} y2={end[1]} />
              <text className="model-ensemble__radar-label" textAnchor="middle" x={label[0]} y={label[1]}>
                {axis.shortLabel}
              </text>
              {estimateWithheld && (
                <rect
                  aria-label={`${axis.label}: experimental estimate withheld`}
                  className="model-ensemble__radar-withheld"
                  height="6"
                  transform={`rotate(45 ${withheld[0]} ${withheld[1]})`}
                  width="6"
                  x={withheld[0] - 3}
                  y={withheld[1] - 3}
                />
              )}
              {value !== null ? (
                <>
                  <circle
                    className="model-ensemble__radar-coverage-ring"
                    cx={marker[0]}
                    cy={marker[1]}
                    pathLength="100"
                    r="8"
                    strokeDasharray={`${Math.round(coverage * 100)} ${100 - Math.round(coverage * 100)}`}
                  />
                  <circle
                    aria-label={rawExplicitZero ? `${axis.label}: explicit known raw zero` : undefined}
                    className={`model-ensemble__radar-point${rawExplicitZero ? " model-ensemble__radar-point--zero" : ""}`}
                    cx={marker[0]}
                    cy={marker[1]}
                    r="4"
                  />
                </>
              ) : (
                <circle
                  aria-label={`${axis.label}: ${stateLabel(axis.metric)}`}
                  className={`model-ensemble__radar-state model-ensemble__radar-state--${modelEnsembleMetricStatus(axis.metric)}`}
                  cx={marker[0]}
                  cy={marker[1]}
                  r="5"
                />
              )}
            </g>
          );
        })}
        {segments.map(([fromIndex, toIndex]) => {
          const from = point(fromIndex, axes[fromIndex].plotted!);
          const to = point(toIndex, axes[toIndex].plotted!);
          return <line className="model-ensemble__radar-value-segment" key={`${fromIndex}-${toIndex}`} x1={from[0]} x2={to[0]} y1={from[1]} y2={to[1]} />;
        })}
      </svg>
      <MetricKnowledgeDescriptions controller={helpCards} entries={helpEntries} />
      <nav
        aria-label={`${lens.label} metric axes`}
        className="model-ensemble__axis-strip"
        onKeyDown={(event) => moveRovingFocus(event, (index) => setSelectedKey(axes[index].key))}
      >
        {axes.map((axis) => {
          const rawRate = modelEnsembleAxisRawRateLabel(axis);
          const pendingBounds = modelEnsembleAxisPendingBoundsLabel(axis);
          return (
            <button
              aria-pressed={axis.key === selected?.key}
              className={`is-${modelEnsembleMetricStatus(axis.metric)}`}
              key={axis.key}
              {...metricKnowledgeCardTriggerProps(helpCards, "strip", axis.key)}
              onClick={() => { setSelectedKey(axis.key); helpCards.togglePin({ surface: "strip", metricKey: axis.key }); }}
              type="button"
            >
              <span>{axis.shortLabel}</span>
              <b>{modelEnsembleAxisPlottedLabel(axis)}</b>
              {rawRate === null ? null : <small>{rawRate}</small>}
              {pendingBounds === null ? null : <small>{pendingBounds}</small>}
              {axis.predictiveMedian !== null
                ? <small>◇ {Math.round(axis.predictiveMedian * 100)}% radar-quality estimate</small>
                : axis.prediction !== null ? <small>Estimate withheld</small> : null}
            </button>
          );
        })}
      </nav>
      <MetricKnowledgeCardSlot compact={compact} controller={helpCards} entries={helpEntries} surface="strip" />
      {selected !== undefined && (
        <section aria-labelledby={focusedMetricHeadingId} className="model-ensemble__focused-metric">
          <header aria-label={`${selected.label} value and state`} role="group">
            <div><h5 id={focusedMetricHeadingId}>{selected.label}</h5><span>{stateLabel(selected.metric)}</span></div>
            <b>{selectedPresentation.value}</b>
          </header>
          {(() => {
            const sentences = modelEnsembleAxisGuidanceSentences(selected, {
              experimentalVisible: selected.predictiveMedian !== null,
              experimentalMedian: selected.predictiveMedian,
            });
            return (
              <div aria-live="polite" className="metric-inspector-sentences" data-basis={sentences.basis} data-kind={sentences.kind}>
                <p><span>Meaning</span>{sentences.meaning}</p>
                <p><span>Next</span>{sentences.action}</p>
              </div>
            );
          })()}
          {selectedPresentation.detail !== null && <p>{selectedPresentation.detail}</p>}
          {selected.prediction !== null && (
            <aside aria-label={`${selected.label} experimental model detail`} className="model-ensemble__predictive-detail">
              <strong>{selected.prediction.state === "calibrated" ? "Predictive interval" : "Experimental estimate"}</strong>
              {selected.predictiveMedian === null ? (
                <span>{selected.predictiveWithheldReason}</span>
              ) : (
                <span>
                  radar-quality median {Math.round(selected.predictiveMedian * 100)}% · central 50% {Math.round(selected.predictiveQ25! * 100)}–{Math.round(selected.predictiveQ75! * 100)}% · central 90% {Math.round(selected.predictiveQ05! * 100)}–{Math.round(selected.predictiveQ95! * 100)}%
                </span>
              )}
              {selected.direction === "lower_is_better" && selected.prediction.median != null && (
                <small>
                  Raw modeled lower-is-better rate: median {Math.round(selected.prediction.median! * 100)}%
                  {selected.prediction.q05 != null && selected.prediction.q95 != null
                    ? ` · central 90% ${Math.round(selected.prediction.q05! * 100)}–${Math.round(selected.prediction.q95! * 100)}%`
                    : ""}.
                </small>
              )}
              <small>
                applicability {selected.prediction.applicability_probability == null
                  ? "not estimable"
                  : `${Math.round(selected.prediction.applicability_probability! * 100)}%`} · disagreement {selected.prediction.model_disagreement == null ? "not estimable" : `${Math.round(selected.prediction.model_disagreement * 100)}%`} · {selected.prediction.effective_observation_count <= 1
                    ? "effective support not established"
                    : `effective observations ${selected.prediction.effective_observation_count}`} · {selected.prediction.calibration_version.replaceAll("-", " ")}
              </small>
              {predictiveDetailState === "loading" && <small>Loading the content-free factor distribution…</small>}
              {predictiveDetailState === "failed" && <small>Detailed factor distribution is temporarily unavailable.</small>}
              {predictiveDetail !== null && (
                <>
                  <svg aria-label="Radar-quality predictive density" className="model-ensemble__density" role="img" viewBox="0 0 200 36">
                    <title>Experimental radar-quality density across twenty five-point bins</title>
                    <path d={`M 0 36 ${displayDensityBins.map((mass, index) => `L ${index * (200 / 19)} ${36 - Math.min(34, mass * 180)}`).join(" ")} L 200 36 Z`} />
                  </svg>
                  <small>The density uses the same radar-quality direction as the diamond and whiskers.</small>
                  <ul aria-label={`${selected.label} predictive factors`} className="model-ensemble__factor-list" tabIndex={0}>
                    {predictiveDetail.factors.map((factor) => (
                      <li key={factor.factor_key}>
                        <span>{factor.factor_key.replaceAll("_", " ")}</span>
                        <small>
                          present {Math.round(factor.present_probability * 100)}% · uncertain {Math.round(factor.neutral_probability * 100)}% · absent {Math.round(factor.absent_probability * 100)}%
                        </small>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </aside>
          )}
          {selected.metric !== null && (
            <dl>
              {isModelEnsembleV2Metric(selected.metric) ? (
                <>
                  <div><dt>V2 fraction</dt><dd>{selected.metric.numerator ?? "—"}/{selected.metric.denominator ?? "—"}</dd></div>
                  <div><dt>Resolved opportunities</dt><dd>{selected.metric.observed_message_count}/{selected.metric.eligible_message_count}</dd></div>
                  <div><dt>Evidence authority</dt><dd>{selected.metric.evidence_authority.replaceAll("_", " ")}</dd></div>
                  <div><dt>Guidance state class</dt><dd data-state-class={selected.metric.guidance?.state_class ?? "absent"}>{selected.metric.guidance?.state_class.replaceAll("_", " ") ?? "not carried by this history point"}</dd></div>
                  {selected.metric.readiness !== null && (
                    <>
                      <div><dt>Evidence readiness</dt><dd>{readableEvidenceAvailability(selected.metric.readiness.availability_state)} · {selected.metric.readiness.reason_code.replaceAll("_", " ")}</dd></div>
                      <div><dt>Proof contributors</dt><dd>{selected.metric.readiness.observed_contributors.length}/{selected.metric.readiness.required_contributors.length} observed</dd></div>
                      <div><dt>Missing proof</dt><dd>{selected.metric.readiness.missing_contributors.length === 0 ? "none" : selected.metric.readiness.missing_contributors.map(readableEvidenceContributor).join(", ")}</dd></div>
                      {selected.metric.readiness.required_adapter_capabilities.length > 0 && (
                        <div><dt>Adapter-required proof families</dt><dd>{selected.metric.readiness.required_adapter_capabilities.map(readableAdapterCapability).join(", ")} · supplied by the adapter, not by user wording</dd></div>
                      )}
                      <div><dt>Product gate</dt><dd>calibration not assessed · not product-metric eligible</dd></div>
                    </>
                  )}
                  {selected.metric.value_state === "pending" && (
                    <div><dt>Censoring bounds</dt><dd>{modelEnsembleAxisPendingBoundsLabel(selected)?.replace(/^bounds /u, "") ?? "not published"}</dd></div>
                  )}
                  <div><dt>Model estimate</dt><dd>{selected.prediction?.state.replaceAll("_", " ") ?? "unavailable"}</dd></div>
                </>
              ) : isTypedMetric(selected.metric) ? (
                <>
                  <div><dt>Typed fraction</dt><dd>{selected.metric.numerator ?? "—"}/{selected.metric.denominator ?? "—"}</dd></div>
                  <div><dt>Metric coverage</dt><dd>{selected.metric.observed_message_count}/{selected.metric.eligible_message_count}</dd></div>
                  <div><dt>Model diagnostic</dt><dd>{selectedCommitteeMetric?.value_state.replaceAll("_", " ") ?? "unavailable"}</dd></div>
                  <div><dt>Calibration</dt><dd>not assessed</dd></div>
                </>
              ) : (
                <>
                  <div><dt>Known observations</dt><dd>{selected.metric.known_chunk_count}/{selected.metric.total_chunk_count}</dd></div>
                  <div><dt>Abstained</dt><dd>{selected.metric.abstained_chunk_count}</dd></div>
                  <div><dt>Unsupported</dt><dd>{selected.metric.unsupported_chunk_count}</dd></div>
                  <div><dt>Failed</dt><dd>{selected.metric.failed_chunk_count}</dd></div>
                </>
              )}
            </dl>
          )}
          {chunkTrace.length === 0 ? (
            <div className="model-ensemble__chunk-trace-note" role="note">
              Aggregate-only history point; select the live head for its per-window trace.
            </div>
          ) : (
            <div aria-label="Selected metric window trace" className="model-ensemble__chunk-trace" role="group">
              <span>{usesTypedProjection ? "Model committee diagnostic" : "Window trace"}</span>
              {chunkTrace.map((chunk) => (
                <i
                  aria-label={`Chunk ${chunk.chunk_ordinal + 1}: ${chunk.value_state.replaceAll("_", " ")}`}
                  className={`is-${chunk.value_state}`}
                  key={chunk.chunk_ordinal}
                  title={`Chunk ${chunk.chunk_ordinal + 1}: ${chunk.value_state.replaceAll("_", " ")}`}
                >
                  {chunk.value_state === "known" ? chunk.numerator : "·"}
                </i>
              ))}
              <small>{usesTypedProjection ? "does not override the typed value" : "ordered chunks, not a calibrated time trend"}</small>
            </div>
          )}
        </section>
      )}
      <figcaption id={radarCaptionId}>
        <p>
          Axes and order stay fixed for this versioned lens. Solid segments connect
          adjacent measured values only; gaps are unknown, not zero. N/A, pending,
          unknown, error, and withheld markers sit in a state lane outside the numeric
          scale; only a known radar-quality zero renders at the center (a raw zero for
          higher-is-better, a raw rate of 100% for lower-is-better).
        </p>
        <p>
          A model estimate appears as an independent diamond with per-axis whiskers only
          when at least two small experts are proven and the 90% span is informative.
          Rings around known points show resolved-versus-eligible opportunity coverage
          for canonical V2 measurements (legacy typed receipts show source-message
          coverage; legacy committee receipts show eligible-observation coverage).
        </p>
        <p>
          Structural ownership cells are not analytic observations. The outline has no
          area fill because these metrics are separate constructs, not one overall
          quality score.
          {comparisonAxes?.some((axis) => axis.plotted !== null)
            ? ` Dashed lines and diamonds show ${comparisonLabel.toLowerCase()} where numeric values exist.`
            : ""}
        </p>
      </figcaption>
    </figure>
  );
}
