import {
  METRIC_OPPORTUNITY_CATALOG_VERSION,
  METRIC_OPPORTUNITY_FAMILIES,
  type MetricOpportunityStatus,
  type OpportunityMetricDirection,
} from "./metricOpportunityCatalog";
import { useId } from "react";
import "./MetricOpportunityMap.css";

const STATUS_COPY: Record<MetricOpportunityStatus, string> = {
  "partial-foundation": "Partial foundation",
  "not-measured": "Not measured yet",
  "private-opt-in": "Private opt-in only",
};

const DIRECTION_COPY: Record<OpportunityMetricDirection, string> = {
  higher: "Higher is favorable within a valid comparison",
  lower: "Lower is favorable within a valid comparison",
  contextual: "Context only; no universal better direction",
};

export function MetricOpportunityMap() {
  const priorities = ["P0", "P1"] as const;
  const instanceId = useId();
  return (
    <details className="metric-opportunity-map">
      <summary>
        <span>
          <span className="metric-opportunity-map__kicker">Analysis roadmap</span>
          <strong>Broader value map</strong>
          <small>
            What Coaching v1 does not fully measure yet · catalog v
            {METRIC_OPPORTUNITY_CATALOG_VERSION}
          </small>
        </span>
        <span aria-hidden="true" className="metric-opportunity-map__count">
          {METRIC_OPPORTUNITY_FAMILIES.length} families
        </span>
      </summary>
      <div className="metric-opportunity-map__content">
        <p className="metric-opportunity-map__boundary" role="note">
          These are versioned metric specifications, not inferred values. Missing
          evidence remains unknown; no roadmap item contributes to an overall score.
        </p>
        {priorities.map((priority) => {
          const families = METRIC_OPPORTUNITY_FAMILIES.filter(
            (family) => family.priority === priority,
          );
          const titleId = `${instanceId}-metric-opportunity-${priority}`;
          return (
            <section
              aria-labelledby={titleId}
              className="metric-opportunity-map__priority"
              key={priority}
            >
              <header>
                <div>
                  <span>{priority}</span>
                  <h3 id={titleId}>
                    {priority === "P0"
                      ? "Next evidence for real user benefit"
                      : "Task-specific and private extensions"}
                  </h3>
                </div>
                <p>
                  {priority === "P0"
                    ? "Build these before adding more prompt-style ratios."
                    : "Activate only when the task and consent boundary justify them."}
                </p>
              </header>
              <div className="metric-opportunity-map__grid">
                {families.map((family) => (
                  <article key={family.id}>
                    <header>
                      <span
                        className={`metric-opportunity-map__status metric-opportunity-map__status--${family.status}`}
                      >
                        {STATUS_COPY[family.status]}
                      </span>
                      <h4>{family.title}</h4>
                      <p>{family.question}</p>
                    </header>
                    <p className="metric-opportunity-map__why">
                      <strong>Why</strong>
                      {family.whyItMatters}
                    </p>
                    <ul aria-label={`${family.title} candidate metrics`}>
                      {family.candidateMetrics.map((metric) => (
                        <li key={metric.key}>
                          <span>{metric.label}</span>
                          <small>{DIRECTION_COPY[metric.direction]}</small>
                        </li>
                      ))}
                    </ul>
                    <dl>
                      <div>
                        <dt>Evidence to add</dt>
                        <dd>{family.evidenceToAdd}</dd>
                      </div>
                      <div>
                        <dt>How to use it</dt>
                        <dd>{family.recommendedAction}</dd>
                      </div>
                      <div>
                        <dt>Release gate</dt>
                        <dd>{family.validationGate}</dd>
                      </div>
                    </dl>
                    <p className="metric-opportunity-map__guardrail">
                      <strong>Guardrail</strong>
                      {family.guardrail}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </details>
  );
}
