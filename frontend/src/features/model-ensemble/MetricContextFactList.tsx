import { FactList } from "../../shared/ui/FactList";
import type { MetricContextFacts } from "./metricContextFacts";

/** Scope · Contributors · Model · Evidence facts for one metric card. */
export function MetricContextFactList({ context, compact = false }: { context: MetricContextFacts; compact?: boolean }) {
  return (
    <section aria-label="Context and evidence" className="metric-context-facts" data-scope={context.scope}>
      <strong className="metric-context-facts__title">Context &amp; evidence</strong>
      <FactList
        compact={compact}
        facts={[
          { term: "Scope", detail: `${context.label} — ${context.description}` },
          { term: "Contributors", detail: context.contributors },
          { term: "Model", detail: context.model, missingLabel: "No model estimate reported" },
          { term: "Evidence", detail: context.evidence },
        ]}
      />
    </section>
  );
}
