import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AnalysisResult,
  AnalysisRun,
  PromptEnhancerTransport,
  TaskRevision,
} from "../../shared/api/contracts";
import type { AppRoute } from "../../shared/platform/platform";
import { GroupedMetricObservations } from "../../entities/analysis/GroupedMetricObservations";
import { ProvenancePanel } from "../../entities/analysis/ProvenancePanel";
import { TaskSummary } from "../../entities/task/TaskSummary";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { Icon } from "../../shared/ui/Icon";

function TaskStateHeader({ state }: { state: "loading" | "error" }) {
  return (
    <header className="page-header route-header">
      <div>
        <p className="eyebrow">Reviewed task</p>
        <h1 id="task-detail-title">Task analysis</h1>
        <p>
          {state === "loading"
            ? "Loading the selected immutable task revision and its analysis evidence."
            : "The selected task revision is unavailable; no task or analysis result is being inferred."}
        </p>
      </div>
    </header>
  );
}

export function TaskDetail({
  taskId,
  revision,
  transport,
  navigate,
}: {
  taskId: string;
  revision: number;
  transport: PromptEnhancerTransport;
  navigate: (route: AppRoute) => void;
}) {
  const [task, setTask] = useState<TaskRevision | null>(null);
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [results, setResults] = useState<AnalysisResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const loadRef = useRef<AbortController | null>(null);
  const analysisRef = useRef<AbortController | null>(null);

  const load = useCallback(async (keepResults = false) => {
    loadRef.current?.abort();
    const controller = new AbortController();
    loadRef.current = controller;
    const ownsRequest = () => loadRef.current === controller && !controller.signal.aborted;
    if (keepResults) setActionError(null);
    else { setLoading(true); setError(null); }
    try {
      const [taskResponse, runsResponse] = await Promise.all([
        transport.getTaskRevision(taskId, revision, controller.signal),
        transport.listAnalysisRuns(taskId, controller.signal),
      ]);
      if (!ownsRequest()) return;
      const matchingRun = runsResponse.runs.find((item) => item.task_revision === revision) ?? null;
      const detail = matchingRun ? await transport.getAnalysisRun(matchingRun.run_id, controller.signal) : null;
      if (!ownsRequest()) return;
      // Publish the task, run and results together; never mix two route snapshots.
      setTask(taskResponse.task);
      setRun(matchingRun);
      setResults(detail?.results ?? []);
    } catch {
      if (!ownsRequest()) return;
      if (keepResults) setActionError("The latest results could not be loaded. The previous results are still shown; reload before starting another run.");
      else setError("Task detail could not be loaded. Try again.");
    } finally {
      if (ownsRequest()) { loadRef.current = null; setLoading(false); }
    }
  }, [revision, taskId, transport]);

  useEffect(() => {
    setTask(null);
    setRun(null);
    setResults([]);
    setActionError(null);
    setAnalyzing(false);
    void load();
    return () => {
      loadRef.current?.abort();
      loadRef.current = null;
      analysisRef.current?.abort();
      analysisRef.current = null;
    };
  }, [load]);

  async function runAnalysis() {
    if (analysisRef.current) return;
    const controller = new AbortController();
    analysisRef.current = controller;
    const ownsRequest = () => analysisRef.current === controller && !controller.signal.aborted;
    setAnalyzing(true);
    setActionError(null);
    try {
      await transport.startAnalysis(taskId, revision, nextIdempotencyKey("analysis"), controller.signal);
      if (ownsRequest()) await load(true);
    } catch {
      if (ownsRequest()) setActionError("Could not confirm the analysis result. Your task and previous results are still available. Reload results before trying another run.");
    } finally {
      if (ownsRequest()) { analysisRef.current = null; setAnalyzing(false); }
    }
  }

  return (
    <div className="task-page">
      <button className="breadcrumb" onClick={() => navigate({ name: "discovery" })} type="button">
        <Icon name="chevron" /> Discovery inbox
      </button>
      {loading ? (
        <>
          <TaskStateHeader state="loading" />
          <LoadingState label="Loading task analysis" />
        </>
      ) : error ? (
        <>
          <TaskStateHeader state="error" />
          <ErrorState message={error} onRetry={() => void load()} />
        </>
      ) : task ? (
        <>
          <TaskSummary task={task} />
          {actionError && <ErrorState message={actionError} onRetry={() => void load(true)} actionLabel="Reload results" />}
          <section aria-labelledby="metrics-heading" className="metrics-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Latest immutable run</p>
                <h2 id="metrics-heading">Metric observations</h2>
                <p>Each result keeps its state, coverage, evidence, and definition version.</p>
              </div>
              {run && (
                <div className="task-analysis-actions">
                  <button
                    className="button button--secondary"
                    disabled={analyzing}
                    onClick={() => void runAnalysis()}
                    title="Creates a new immutable run for this task revision; earlier runs remain available"
                    type="button"
                  >
                    <Icon name="activity" /> {analyzing ? "Analyzing..." : "Run latest pack"}
                  </button>
                  <span className={`run-status run-status--${run.status}`}>{run.status}</span>
                </div>
              )}
            </div>
            {run ? (
              <GroupedMetricObservations results={results} />
            ) : (
              <div className="no-analysis">
                <span><Icon name="activity" /></span>
                <div><h3>No analysis run yet</h3><p>The task revision exists; metrics remain unknown until an explicit run is created.</p></div>
                <button
                  className="button button--primary"
                  disabled={analyzing}
                  onClick={() => void runAnalysis()}
                  type="button"
                >
                  <Icon name="activity" /> {analyzing ? "Analyzing..." : "Run analysis"}
                </button>
              </div>
            )}
          </section>
          {run && <ProvenancePanel results={results} run={run} />}
        </>
      ) : null}
    </div>
  );
}
