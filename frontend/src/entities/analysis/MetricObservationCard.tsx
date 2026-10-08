import type { AnalysisResult } from "../../shared/api/contracts";
import { formatPercent, titleFromKey } from "../../shared/lib/format";
import { CoverageBar } from "../../shared/ui/CoverageBar";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";
import { formatRateBasis, getMetricPresentation } from "./metricPresentation";
import { describeMetricSemantics } from "./metricSemantics";

function formatMetricValue(result: AnalysisResult): string {
  if (result.value_state !== "known") return titleFromKey(result.value_state);
  if (result.numeric_value !== null) {
    if (result.unit === "ratio") return formatPercent(result.numeric_value);
    const suffix = result.unit === "count" ? "" : ` ${result.unit}`;
    return `${new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(result.numeric_value)}${suffix}`;
  }
  return result.text_value ? titleFromKey(result.text_value) : "Observed";
}

export function MetricObservationCard({ result }: { result: AnalysisResult }) {
  const semantics = describeMetricSemantics({
    state: result.value_state,
    numericValue: result.numeric_value,
    unit: result.unit,
    confidence: result.confidence,
    observed: result.observed_count,
    eligible: result.eligible_count,
    coverage: result.coverage,
  });
  const presentation = getMetricPresentation({
    key: result.key,
    dimension: result.dimension ?? undefined,
    displayName: result.display_name ?? undefined,
  });
  const rateBasis =
    result.unit === "ratio" && result.numeric_value !== null
      ? formatRateBasis({
          key: result.key,
          numericValue: result.numeric_value,
          observed: result.observed_count,
          eligible: result.eligible_count,
        })
      : null;
  const detailId = `metric-${result.key.replace(/[^a-zA-Z0-9_-]/g, "-")}-${result.version}-detail`;
  return (
    <article
      aria-describedby={detailId}
      className={`metric-card metric-card--${result.value_state}${semantics.partial ? " metric-card--partial" : ""}`}
    >
      <div className="metric-card__header">
        <span className="metric-card__icon"><Icon name="activity" /></span>
        <StatusPill tone={semantics.tone}>{semantics.label}</StatusPill>
      </div>
      <div>
        <p className="metric-card__eyebrow">{titleFromKey(presentation.dimension)}</p>
        <h4>{presentation.displayName}</h4>
        <p className="metric-card__question">{presentation.question}</p>
      </div>
      <p className="metric-card__value">{formatMetricValue(result)}</p>
      <p className="metric-card__detail" id={detailId}>{semantics.detail}</p>
      <CoverageBar
        coverage={result.coverage}
        eligible={result.eligible_count}
        observed={result.observed_count}
      />
      <dl className="metric-card__footer">
        <div><dt>Source</dt><dd>{titleFromKey(result.source)}</dd></div>
        <div><dt>Definition</dt><dd>v{result.version}</dd></div>
        <div><dt>Usable evidence</dt><dd>{result.observed_count}</dd></div>
        <div><dt>Eligible evidence</dt><dd>{result.eligible_count}</dd></div>
        <div><dt>Confidence</dt><dd>{result.confidence == null ? "Unknown" : formatPercent(result.confidence)}</dd></div>
        {rateBasis !== null ? (
          <div>
            <dt>Rate basis</dt>
            <dd>{rateBasis}</dd>
          </div>
        ) : (
          <div><dt>Evidence</dt><dd>{result.evidence_event_ids.length} refs</dd></div>
        )}
      </dl>
    </article>
  );
}
