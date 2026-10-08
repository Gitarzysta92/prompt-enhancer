import type { SessionMetric } from "../../shared/api/contracts";
import { formatPercent, titleFromKey } from "../../shared/lib/format";
import { CoverageBar } from "../../shared/ui/CoverageBar";
import { StatusPill } from "../../shared/ui/StatusPill";
import { formatRateBasis, getMetricPresentation } from "./metricPresentation";
import { describeMetricSemantics } from "./metricSemantics";

function metricValue(metric: SessionMetric): string {
  if (metric.numeric_value !== null) {
    if (metric.unit === "ratio") return formatPercent(metric.numeric_value);
    const value = new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(
      metric.numeric_value,
    );
    return !metric.unit || metric.unit === "count"
      ? value
      : `${value} ${metric.unit}`;
  }
  return metric.text_value ? titleFromKey(metric.text_value) : "Unknown";
}

function optionalProvenance(value: string | null): string {
  return value?.trim() || "Not reported";
}

function computedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Not reported"
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(date);
}

export function SessionMetricCard({ metric }: { metric: SessionMetric }) {
  const hasValue = metric.numeric_value !== null || metric.text_value !== null;
  const semantics = describeMetricSemantics({
    state: hasValue ? "known" : "unknown",
    numericValue: metric.numeric_value,
    unit: metric.unit,
    confidence: metric.confidence,
    observed: metric.observed_count,
    eligible: metric.eligible_count,
    coverage: metric.coverage,
  });
  const presentation = getMetricPresentation({
    key: metric.key,
    dimension: metric.dimension,
    displayName: metric.display_name,
  });
  const rateBasis =
    metric.unit === "ratio" && metric.numeric_value !== null
      ? formatRateBasis({
          key: metric.key,
          numericValue: metric.numeric_value,
          observed: metric.observed_count,
          eligible: metric.eligible_count,
        })
      : null;
  const detailId = `session-metric-${metric.key.replace(/[^a-zA-Z0-9_-]/g, "-")}-${metric.version}-detail`;

  return (
    <article
      aria-describedby={detailId}
      className={`local-metric-card${semantics.partial ? " local-metric-card--partial" : ""}`}
    >
      <div className="local-metric-card__topline">
        <span className="status-pill">{titleFromKey(presentation.dimension)}</span>
        <StatusPill tone={semantics.tone}>{semantics.label}</StatusPill>
      </div>
      <h3>{presentation.displayName}</h3>
      <p className="local-metric-card__question">{presentation.question}</p>
      <strong className="local-metric-card__value">{metricValue(metric)}</strong>
      <p className="local-metric-card__detail" id={detailId}>{semantics.detail}</p>
      <CoverageBar
        coverage={metric.coverage}
        eligible={metric.eligible_count}
        observed={metric.observed_count}
      />
      <dl>
        <div><dt>Source</dt><dd>{titleFromKey(metric.source)}</dd></div>
        <div><dt>Definition</dt><dd>v{metric.version}</dd></div>
        <div><dt>Usable evidence</dt><dd>{metric.observed_count}</dd></div>
        <div><dt>Eligible evidence</dt><dd>{metric.eligible_count}</dd></div>
        <div><dt>Confidence</dt><dd>{metric.confidence === null ? "Unknown" : formatPercent(metric.confidence)}</dd></div>
        {rateBasis !== null && <div><dt>Rate basis</dt><dd>{rateBasis}</dd></div>}
      </dl>
      <details className="metric-provenance">
        <summary>Definition and provenance</summary>
        <dl>
          <div><dt>Metric key</dt><dd className="mono">{metric.key}</dd></div>
          <div><dt>Metric pack</dt><dd>{titleFromKey(metric.metric_pack_key)} v{metric.metric_pack_version}</dd></div>
          <div><dt>Engine</dt><dd>{metric.metric_engine_version}</dd></div>
          <div><dt>Redactor</dt><dd>{optionalProvenance(metric.redactor_version)}</dd></div>
          <div><dt>Model</dt><dd>{optionalProvenance(metric.model_id)}</dd></div>
          <div><dt>Model revision</dt><dd>{optionalProvenance(metric.model_revision)}</dd></div>
          <div><dt>Tokenizer</dt><dd>{optionalProvenance(metric.tokenizer_id)}</dd></div>
          <div><dt>Prompt rubric</dt><dd>{optionalProvenance(metric.prompt_version)}</dd></div>
          <div><dt>Scoring rubric</dt><dd>{optionalProvenance(metric.rubric_version)}</dd></div>
          <div><dt>Computed</dt><dd>{computedAt(metric.computed_at)}</dd></div>
        </dl>
      </details>
    </article>
  );
}
