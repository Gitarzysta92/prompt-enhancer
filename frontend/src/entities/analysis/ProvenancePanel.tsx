import type { AnalysisResult, AnalysisRun } from "../../shared/api/contracts";
import { formatTimestamp, shortId, titleFromKey } from "../../shared/lib/format";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill } from "../../shared/ui/StatusPill";

export function ProvenancePanel({
  run,
  results,
}: {
  run: AnalysisRun;
  results: AnalysisResult[];
}) {
  const modelBacked = results.some((result) => result.model_id !== null);
  return (
    <section aria-labelledby="provenance-heading" className="provenance-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Reproducibility</p>
          <h2 id="provenance-heading">Analysis provenance</h2>
        </div>
        <StatusPill tone="info"><Icon name="lock" /> Metadata only</StatusPill>
      </div>
      <dl className="provenance-grid">
        <div><dt>Run</dt><dd className="mono">{shortId(run.run_id)}</dd></div>
        <div><dt>Metric pack</dt><dd>{titleFromKey(run.metric_pack_key)} - v{run.metric_pack_version}</dd></div>
        <div><dt>Engine</dt><dd>{run.metric_engine_version}</dd></div>
        <div><dt>Redactor</dt><dd>{run.redactor_version}</dd></div>
        <div><dt>Data tier</dt><dd>{titleFromKey(run.data_tier)}</dd></div>
        <div><dt>Completed</dt><dd>{formatTimestamp(run.finished_at ?? run.started_at)}</dd></div>
        <div><dt>Schema</dt><dd>v{run.schema_version}</dd></div>
        <div><dt>Model invocation</dt><dd>{modelBacked ? "Recorded per result" : "None"}</dd></div>
      </dl>
      <details className="evidence-references">
        <summary>Evidence references ({results.reduce((total, result) => total + result.evidence_event_ids.length, 0)})</summary>
        <ul>
          {results.flatMap((result) =>
            result.evidence_event_ids.map((eventId) => (
              <li key={`${result.key}-${eventId}`}>
                <span>{titleFromKey(result.key)}</span>
                <code>{shortId(eventId)}</code>
              </li>
            )),
          )}
        </ul>
      </details>
    </section>
  );
}
