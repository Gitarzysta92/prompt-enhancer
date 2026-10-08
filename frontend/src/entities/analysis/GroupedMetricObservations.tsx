import type { AnalysisResult } from "../../shared/api/contracts";
import { MetricObservationCard } from "./MetricObservationCard";
import { groupMetricItems, normalizeMetricKey } from "./metricPresentation";

export function GroupedMetricObservations({ results }: { results: AnalysisResult[] }) {
  const groups = groupMetricItems(results, (result) => ({
    key: result.key,
    dimension: result.dimension ?? undefined,
    displayName: result.display_name ?? undefined,
  }));
  const eventStreamMetric = results.find(
    (result) => normalizeMetricKey(result.key) === "workflow.observed_event_count",
  );
  const snapshotComplete =
    eventStreamMetric?.value_state === "known" &&
    eventStreamMetric.coverage >= 1 &&
    eventStreamMetric.confidence !== null;
  return (
    <div className="metric-groups">
      <div
        className={`snapshot-boundary${snapshotComplete ? "" : " snapshot-boundary--partial"}`}
        role="note"
      >
        <strong>
          {snapshotComplete
            ? "Assigned task event streams marked complete"
            : eventStreamMetric
              ? "Partial task evidence - current snapshot only"
              : "Task stream completeness not reported"}
        </strong>
        <p>
          {snapshotComplete
            ? "Coverage still applies per metric and does not turn descriptive counts into quality judgments."
            : "Metric-level coverage can be complete for observed evidence while assigned session history remains incomplete or unknown."}
        </p>
      </div>
      {groups.map(({ presentation, items }) => {
        const headingId = `metric-group-${presentation.id}`;
        return (
          <section
            aria-labelledby={headingId}
            className={`metric-group metric-group--${presentation.id}`}
            key={presentation.id}
          >
            <header className="metric-group__header">
              <div>
                <p className="eyebrow">{presentation.eyebrow}</p>
                <h3 id={headingId}>{presentation.title}</h3>
                <p className="metric-group__question">{presentation.question}</p>
                <p>{presentation.description}</p>
              </div>
              <span className="count-badge" aria-label={`${items.length} metrics`}>
                {items.length}
              </span>
            </header>
            <div className="metric-grid">
              {items.map((result) => (
                <MetricObservationCard
                  key={`${result.key}-${result.version}`}
                  result={result}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
