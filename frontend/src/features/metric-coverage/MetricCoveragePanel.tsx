import { useEffect, useMemo, useState } from "react";
import type {
  MetricCoverageReport,
  PromptEnhancerTransport,
  Provider,
} from "../../shared/api/contracts";
import "./MetricCoveragePanel.css";

type CoverageState =
  | { status: "loading" }
  | { status: "ready"; report: MetricCoverageReport }
  | { status: "error" };

function stateTotal(
  states: MetricCoverageReport["metrics"][number]["contract_compatible_result_states"],
): number {
  return states.known + states.unknown + states.not_applicable +
    states.abstained + states.execution_error;
}

export function MetricCoveragePanel({
  transport,
  provider,
  projectId,
}: {
  transport: PromptEnhancerTransport;
  provider: Provider;
  projectId?: string;
}) {
  const [state, setState] = useState<CoverageState>({ status: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    const request = projectId === undefined
      ? transport.getMetricCoverage(provider, controller.signal)
      : transport.getProjectMetricCoverage(projectId, provider, controller.signal);
    void request
      .then((report) => {
        if (!controller.signal.aborted) setState({ status: "ready", report });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, [projectId, provider, retryKey, transport]);

  const totals = useMemo(() => {
    if (state.status !== "ready") return null;
    return state.report.metrics.reduce(
      (result, metric) => ({
        compatible: result.compatible +
          stateTotal(metric.contract_compatible_result_states),
        incompatible: result.incompatible + metric.contract_incompatible_result_count,
        cohorts: result.cohorts + metric.compatible_provenance_cohort_count,
      }),
      { compatible: 0, incompatible: 0, cohorts: 0 },
    );
  }, [state]);

  if (state.status === "loading") {
    return (
      <section className="metric-coverage-panel" aria-busy="true">
        <p className="eyebrow">Measurement coverage</p>
        <h2>Checking the local metric snapshot...</h2>
        <p role="status">Reading content-free counts from the stored SQLite index.</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="metric-coverage-panel metric-coverage-panel--unknown">
        <p className="eyebrow">Measurement coverage</p>
        <h2>Metric coverage: Unknown</h2>
        <p role="alert">
          The content-free coverage report could not be verified. Existing project
          and session views remain available; no missing count is shown as zero.
        </p>
        <button
          className="button button--secondary button--compact"
          onClick={() => setRetryKey((value) => value + 1)}
          type="button"
        >
          Retry coverage
        </button>
      </section>
    );
  }

  const { report } = state;
  const attemptable = report.capability_report.structurally_attemptable_metric_count;
  return (
    <section className="metric-coverage-panel" aria-labelledby="metric-coverage-title">
      <header>
        <div>
          <p className="eyebrow">Measurement coverage</p>
          <h2 id="metric-coverage-title">Coaching metric coverage</h2>
          <p>
            {attemptable} of {report.metrics.length} metric definitions are structurally
            attemptable.
          </p>
        </div>
        <span className="status-pill status-pill--info">Exact SQLite counts</span>
      </header>

      <p className="metric-coverage-panel__explanation">
        Structural support describes available provider evidence channels only. It does
        not mean {attemptable} metrics were measured in any session.
      </p>
      <dl className="metric-coverage-panel__totals" aria-label="Coverage snapshot counts" role="group">
        <div><dt>Indexed sessions</dt><dd>{report.indexed_session_count}</dd></div>
        <div><dt>Latest completed snapshots</dt><dd>{report.latest_completed_snapshot_count}</dd></div>
        <div><dt>Contract-compatible stored results</dt><dd>{totals?.compatible}</dd></div>
        <div><dt>Contract-incompatible selected snapshots</dt><dd>{totals?.incompatible}</dd></div>
        <div><dt>Per-metric provenance cohorts</dt><dd>{totals?.cohorts}</dd></div>
        <div><dt>Unrecognized stored result records</dt><dd>{report.unrecognized_result_record_count}</dd></div>
      </dl>
      <dl className="metric-coverage-panel__totals" aria-label="Latest analysis attempts" role="group">
        <div><dt>Latest attempt completed</dt><dd>{report.latest_profile_runs.completed}</dd></div>
        <div><dt>Latest attempt running</dt><dd>{report.latest_profile_runs.running}</dd></div>
        <div><dt>Latest attempt failed</dt><dd>{report.latest_profile_runs.failed}</dd></div>
        <div><dt>Never run</dt><dd>{report.latest_profile_runs.never_run}</dd></div>
      </dl>
      <dl className="metric-coverage-panel__totals" aria-label="Automation scope" role="group">
        <div><dt>Effective automation grants</dt><dd>{report.effective_automation_grant_count}</dd></div>
        <div><dt>Effective automation projects</dt><dd>{report.effective_automation_project_count}</dd></div>
      </dl>
      <p className="metric-coverage-panel__boundary" role="note">
        Automation is scoped to bounded newest sessions that are new or changed. Full
        catalog automation coverage is not guaranteed; grant and project totals do not
        mean every metric or session was scheduled.
      </p>

      <details className="metric-coverage-panel__details">
        <summary>Metric-by-metric counts</summary>
        <div className="metric-coverage-panel__table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Structure</th>
                <th scope="col">Selected</th>
                <th scope="col">Not selected</th>
                <th scope="col">Scope unknown</th>
                <th scope="col">Known</th>
                <th scope="col">Unknown</th>
                <th scope="col">Not applicable</th>
                <th scope="col">Abstained</th>
                <th scope="col">Execution error</th>
                <th scope="col">Incompatible selections</th>
                <th scope="col">Absent</th>
                <th scope="col">Cohorts</th>
                <th scope="col">Automation-selected projects</th>
              </tr>
            </thead>
            <tbody>
              {report.metrics.map((metric) => (
                <tr key={`${metric.metric_key}.v${metric.metric_version}`}>
                  <th scope="row">{metric.display_name}</th>
                  <td>{metric.structural_support}</td>
                  <td>{metric.selected_run_count}</td>
                  <td>{metric.not_selected_run_count}</td>
                  <td>{metric.unknown_scope_run_count}</td>
                  <td>{metric.contract_compatible_result_states.known}</td>
                  <td>{metric.contract_compatible_result_states.unknown}</td>
                  <td>{metric.contract_compatible_result_states.not_applicable}</td>
                  <td>{metric.contract_compatible_result_states.abstained}</td>
                  <td>{metric.contract_compatible_result_states.execution_error}</td>
                  <td>{metric.contract_incompatible_result_count}</td>
                  <td>{metric.expected_result_absent_count}</td>
                  <td>{metric.compatible_provenance_cohort_count}</td>
                  <td>{metric.effective_automation_selected_project_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <p className="metric-coverage-panel__boundary" role="note">
        These counts are exact for this SQLite snapshot, not for all provider history.
        Provider-history completeness is unknown and no authoritative provider snapshot
        or cursor is available, so no provider-history percentage is shown.
      </p>
      <p className="metric-coverage-panel__boundary" role="note">
        Contract-compatible means each stored result passed the current metric contract.
        Per-metric provenance cohorts are counted without being merged into one comparison.
      </p>
      <p className="metric-coverage-panel__boundary" role="note">
        The cached provider-capability report was not captured atomically with the SQLite
        counts, so structural support and stored-result counts are separate evidence axes.
      </p>
    </section>
  );
}
