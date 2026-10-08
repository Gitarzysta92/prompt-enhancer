import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ModelEvaluationJob,
  ModelRuntimeInventory,
  PromptEnhancerTransport,
  TextAnalysisResearchCatalog,
} from "../../shared/api/contracts";
import { ModelLabInventoryPanel } from "./ModelLabInventoryPanel";
import { ModelCompatibilityPanel } from "./ModelCompatibilityPanel";
import { MetricOperabilityPanel } from "./MetricOperabilityPanel";
import { TabList, tabId, tabPanelId } from "../../shared/ui/Tabs";

type LabView = "metrics" | "methods" | "models";
type Metric = TextAnalysisResearchCatalog["metric_roadmap"][number];
type Method = TextAnalysisResearchCatalog["methods"][number];
type Candidate = TextAnalysisResearchCatalog["model_candidates"][number];

const RESEARCH_TAB_PREFIX = "research-catalog";
const RESEARCH_TABS = [
  { id: "metrics", label: "Metric roadmap" },
  { id: "methods", label: "Method stack" },
  { id: "models", label: "Model candidates" },
] as const;
const DOWNLOAD_SESSION_MODELS_LABEL = "Download & test session models";

const PROFILE_LABELS: Record<Metric["profile"], string> = {
  prompt: "How you define the work",
  collaboration: "How the conversation develops",
  logic: "How decisions connect to action",
  agent_answer: "How useful and grounded answers are",
  outcome: "What was actually delivered",
};

const PROFILE_ORDER: Metric["profile"][] = [
  "prompt",
  "collaboration",
  "logic",
  "agent_answer",
  "outcome",
];

type CudaVramBucket = NonNullable<ModelRuntimeInventory["cuda_vram_bucket"]>;

const CUDA_VRAM_LABELS: Record<CudaVramBucket, string> = {
  below_8_gib_class: "Below the reviewed 8 GiB class",
  "8_gib_class": "8 GiB class",
  "12_gib_class": "12 GiB class",
  "16_gib_class": "16 GiB class",
  "24_gib_plus_class": "24 GiB+ class",
};

function cudaMemoryLabel(runtime: ModelRuntimeInventory | null): string {
  if (runtime === null) return "Checking…";
  if (runtime.cuda_state === "unknown") return "CUDA status unknown";
  if (runtime.cuda_state === "unavailable") return "CUDA unavailable";
  return runtime.cuda_vram_bucket
    ? CUDA_VRAM_LABELS[runtime.cuda_vram_bucket]
    : "CUDA status unknown";
}

const DIRECTION_LABELS: Record<Metric["direction"], string> = {
  higher_is_better: "Higher is better",
  lower_is_better: "Lower is better",
  contextual: "Context matters",
};

const ROADMAP_STATE: Record<Metric["state"], { label: string; tone: string }> = {
  baseline_available: { label: "Baseline available", tone: "baseline" },
  research: { label: "Research design", tone: "research" },
  needs_objective_evidence: { label: "Needs objective evidence", tone: "evidence" },
};

const METHOD_STATE: Record<Method["maturity"], { label: string; tone: string }> = {
  product_baseline: { label: "Experimental baseline", tone: "baseline" },
  evaluated_exploratory: { label: "Synthetic screen", tone: "exploratory" },
  research_candidate: { label: "Research candidate", tone: "research" },
  failed_gate: { label: "Blocked by validation", tone: "blocked" },
};

const MODEL_STATE: Record<Candidate["status"], { label: string; tone: string }> = {
  evaluated_exploratory: { label: "Exploratory result", tone: "exploratory" },
  research_shortlist: { label: "Shortlisted", tone: "research" },
  rejected_screen: { label: "Rejected by gate", tone: "blocked" },
};

function formatMetricName(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatScore(value: number): string {
  return `${(value * 100).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  })}%`;
}

function StatusBadge({ label, tone }: { label: string; tone: string }) {
  return <span className={`research-status research-status--${tone}`}>{label}</span>;
}

function MetricsView({ catalog, transport }: { catalog: TextAnalysisResearchCatalog; transport: PromptEnhancerTransport }) {
  const grouped = useMemo(
    () =>
      PROFILE_ORDER.map((profile) => ({
        profile,
        metrics: catalog.metric_roadmap.filter((metric) => metric.profile === profile),
      })).filter((group) => group.metrics.length > 0),
    [catalog.metric_roadmap],
  );

  return (
    <div className="research-roadmap">
      <MetricOperabilityPanel transport={transport} />
      {grouped.map((group) => (
        <section className="research-profile" key={group.profile}>
          <header className="research-profile__header">
            <span>{group.metrics.length}</span>
            <div>
              <h2>{PROFILE_LABELS[group.profile]}</h2>
              <p>Independent signals with their own evidence and applicability.</p>
            </div>
          </header>
          <div className="research-metric-list">
            {group.metrics.map((metric) => {
              const state = ROADMAP_STATE[metric.state];
              return (
                <article className="research-metric-row" key={metric.key}>
                  <div className="research-metric-row__main">
                    <div className="research-metric-row__title">
                      <h3>{metric.name}</h3>
                      <StatusBadge label={state.label} tone={state.tone} />
                    </div>
                    <p className="research-metric-row__question">{metric.question}</p>
                    <p className="research-metric-row__evidence">
                      <strong>Evidence:</strong> {metric.evidence}
                    </p>
                  </div>
                  <div className="research-metric-row__meta">
                    <span>{DIRECTION_LABELS[metric.direction]}</span>
                    <small>{metric.caution}</small>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function MethodsView({ catalog }: { catalog: TextAnalysisResearchCatalog }) {
  const candidates = new Map(catalog.model_candidates.map((item) => [item.key, item]));
  return (
    <div className="research-card-grid">
      {catalog.methods.map((method, index) => {
        const status = METHOD_STATE[method.maturity];
        return (
          <article className="research-method-card" key={method.key}>
            <header>
              <span className="research-method-card__number">
                {String(index + 1).padStart(2, "0")}
              </span>
              <StatusBadge label={status.label} tone={status.tone} />
            </header>
            <h2>{method.name}</h2>
            <p>{method.purpose}</p>
            <dl className="research-method-card__facts">
              <div>
                <dt>Approach</dt>
                <dd>{formatMetricName(method.approach)}</dd>
              </div>
              <div>
                <dt>Data</dt>
                <dd>{method.privacy_tier === "metadata" ? "Metadata" : "Redacted text"}</dd>
              </div>
            </dl>
            <div className="research-chip-row" aria-label="Outputs">
              {method.produces.map((output) => <span key={output}>{output}</span>)}
            </div>
            {method.candidate_model_keys.length > 0 && (
              <p className="research-method-card__models">
                <strong>Candidates:</strong>{" "}
                {method.candidate_model_keys
                  .map((key) => candidates.get(key)?.display_name ?? key)
                  .join(" · ")}
              </p>
            )}
            <p className="research-method-card__limit">{method.limitations[0]}</p>
          </article>
        );
      })}
    </div>
  );
}

function ModelEvaluationPanel({ transport }: { transport: PromptEnhancerTransport }) {
  const [runtime, setRuntime] = useState<ModelRuntimeInventory | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(transport.getTextModelRuntime !== undefined);
  const [runtimeRetry, setRuntimeRetry] = useState(0);
  const [job, setJob] = useState<ModelEvaluationJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState(false);
  const [statusRetry, setStatusRetry] = useState(0);
  const [polling, setPolling] = useState(false);
  const [starting, setStarting] = useState(false);
  const startController = useRef<AbortController | null>(null);

  useEffect(() => {
    setRuntime(null);
    setJob(null);
    setError(null);
    setStatusError(false);
    setPolling(false);
    setStarting(false);
    return () => {
      startController.current?.abort();
      startController.current = null;
    };
  }, [transport]);

  useEffect(() => {
    if (!transport.getTextModelRuntime) {
      setRuntimeLoading(false);
      return;
    }
    const controller = new AbortController();
    setRuntimeLoading(true);
    void transport.getTextModelRuntime(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setRuntime(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setRuntime(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRuntimeLoading(false);
      });
    return () => controller.abort();
  }, [runtimeRetry, transport]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status) || !transport.getTextModelEvaluation) {
      return;
    }
    const controller = new AbortController();
    setPolling(true);
    const timeout = window.setTimeout(() => {
      void transport.getTextModelEvaluation?.(job.job_id, controller.signal)
        .then((value) => {
          if (controller.signal.aborted) return;
          if (value.job_id !== job.job_id) {
            setStatusError(true);
            return;
          }
          setStatusError(false);
          setJob(value);
        })
        .catch(() => {
          if (!controller.signal.aborted) setStatusError(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setPolling(false);
        });
    }, 750);
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [job, statusRetry, transport]);

  const running = job?.status === "queued" || job?.status === "running";

  async function start({
    allowDownload,
    candidate,
    mode,
  }: {
    allowDownload: boolean;
    candidate: ModelEvaluationJob["candidate"]["candidate"];
    mode: ModelEvaluationJob["candidate"]["mode"];
  }) {
    if (!transport.startTextModelEvaluation || running || startController.current) return;
    const controller = new AbortController();
    startController.current = controller;
    const owns = () => startController.current === controller && !controller.signal.aborted;
    setStarting(true);
    setError(null);
    setStatusError(false);
    try {
      const created = await transport.startTextModelEvaluation({
        candidate,
        device: "auto",
        mode,
        allow_download: allowDownload,
      }, controller.signal);
      if (owns()) setJob(created);
    } catch {
      if (owns()) setError("The local benchmark could not be started. Another run may already be active.");
    } finally {
      if (owns()) {
        startController.current = null;
        setStarting(false);
      }
    }
  }

  if (!transport.startTextModelEvaluation || !transport.getTextModelEvaluation) {
    return (
      <aside className="model-evaluation-panel model-evaluation-panel--disabled">
        <strong>Local benchmark runner unavailable</strong>
        <p>Restart the integrated app to enable isolated GPU model screening.</p>
      </aside>
    );
  }

  return (
    <section className="model-evaluation-panel" aria-labelledby="model-evaluation-title">
      <div className="model-evaluation-panel__intro">
        <div>
          <p className="eyebrow">Synthetic model screen</p>
          <h2 id="model-evaluation-title">Prepare real local models</h2>
          <p>
            Runs fictional English/Polish cases in a separate process, one model at a time.
            It never receives a project, session, prompt, response, or provider identifier.
          </p>
        </div>
        <dl>
          <div><dt>Preferred device</dt><dd>{runtime?.preferred_device.toUpperCase() ?? (runtimeLoading ? "Checking…" : "Unavailable")}</dd></div>
          <div><dt>CUDA memory</dt><dd>{runtime === null && !runtimeLoading ? "CUDA status unknown" : cudaMemoryLabel(runtime)}</dd></div>
          <div><dt>Product activation</dt><dd>Off until calibrated</dd></div>
        </dl>
      </div>
      <div className="model-evaluation-panel__actions">
        {!runtimeLoading && runtime === null && (
          <div role="status">
            <p>Local runtime inventory is unavailable; device and memory remain unknown.</p>
            {transport.getTextModelRuntime && <button onClick={() => setRuntimeRetry((value) => value + 1)} type="button">Retry runtime status</button>}
          </div>
        )}
        <button
          disabled={running || starting}
          onClick={() =>
            void start({
              allowDownload: false,
              candidate: "session-link",
              mode: "smoke",
            })
          }
          type="button"
        >
          {starting ? "Starting benchmark…" : running ? statusError ? "Waiting for benchmark status" : "Running models…" : "Test cached session models"}
        </button>
        <button
          className="button-secondary"
          disabled={running || starting}
          onClick={() =>
            void start({
              allowDownload: true,
              candidate: "session-link",
              mode: "smoke",
            })
          }
          type="button"
        >
          {DOWNLOAD_SESSION_MODELS_LABEL}
        </button>
        <button
          className="button-secondary"
          disabled={running || starting}
          onClick={() =>
            void start({
              allowDownload: false,
              candidate: "all",
              mode: "full",
            })
          }
          type="button"
        >
          Run all cached candidates
        </button>
        <small>
          Downloads are public, revision-pinned, safetensors-only, and stored under the ignored local runtime cache.
        </small>
      </div>
      {error && <p className="model-evaluation-panel__error" role="alert">{error}</p>}
      {statusError && (
        <div>
          <p className="model-evaluation-panel__error" role="alert">
            The local benchmark status is unavailable. Its last receipt is retained; the worker may still be running.
          </p>
          <button disabled={polling} onClick={() => setStatusRetry((value) => value + 1)} type="button">
            {polling ? "Checking benchmark status…" : "Retry benchmark status"}
          </button>
        </div>
      )}
      {job && (
        <div className="model-evaluation-results" aria-live="polite">
          <header>
            <strong>{statusError ? "Benchmark status unknown" : job.status === "completed" ? "Screen complete" : job.status === "failed" ? "Screen incomplete" : job.status === "cancelled" ? "Screen cancelled" : "Screen in progress"}</strong>
            <span>{job.resolved_device?.toUpperCase() ?? job.candidate.device.toUpperCase()} · {job.candidate.mode}</span>
          </header>
          {job.status === "cancelled" && <p>The app shut down before the screen completed. No evaluation result was accepted.</p>}
          {job.error_code === "model_evaluation_cleanup_unconfirmed" && <p>The model process could not be confirmed stopped. Check the local runtime before starting another screen.</p>}
          {job.status === "failed" && job.outcomes.some((item) => item.error_code === "model_cache_missing_or_invalid") && (
            <p>One or more verified snapshots are missing. Use “{DOWNLOAD_SESSION_MODELS_LABEL}” to fetch only pinned public artifacts.</p>
          )}
          {job.outcomes.length > 0 && (
            <div className="model-evaluation-results__grid">
              {job.outcomes.map((outcome) => (
                <article key={outcome.key}>
                  <strong>{formatMetricName(outcome.key)}</strong>
                  <span>{formatMetricName(outcome.status)}</span>
                  {typeof outcome.primary_value === "number" && outcome.primary_metric && (
                    <b>{formatMetricName(outcome.primary_metric)} {formatScore(outcome.primary_value)}</b>
                  )}
                  {typeof outcome.peak_accelerator_memory_mb === "number" && (
                    <small>{Math.round(outcome.peak_accelerator_memory_mb)} MB accelerator peak</small>
                  )}
                  {outcome.error_code && <small>{formatMetricName(outcome.error_code)}</small>}
                </article>
              ))}
            </div>
          )}
        </div>
      )}
      <p className="model-evaluation-panel__boundary">
        Session analysis uses the explainable 20-metric coaching pack. Neural candidates remain separate until a private, adjudicated holdout proves they improve accuracy.
      </p>
    </section>
  );
}

function ModelsView({ catalog, transport }: { catalog: TextAnalysisResearchCatalog; transport: PromptEnhancerTransport }) {
  const sources = new Map(catalog.sources.map((source) => [source.key, source]));
  return (
    <>
      <ModelLabInventoryPanel transport={transport} />
      <ModelCompatibilityPanel transport={transport} />
      <ModelEvaluationPanel transport={transport} />
      <div className="research-model-list">
        {catalog.model_candidates.map((candidate) => {
        const status = MODEL_STATE[candidate.status];
        const modelCard = candidate.source_keys
          .map((key) => sources.get(key))
          .find((source) => source?.kind === "model_card");
        return (
          <article className="research-model-card" key={candidate.key}>
            <div className="research-model-card__identity">
              <StatusBadge label={status.label} tone={status.tone} />
              <h2>{candidate.display_name}</h2>
              <p>{candidate.task}</p>
              {modelCard && (
                <a href={modelCard.url} rel="noreferrer" target="_blank">
                  {candidate.repository_id}
                </a>
              )}
            </div>
            <dl className="research-model-card__facts">
              <div><dt>Size</dt><dd>{candidate.parameter_scale}</dd></div>
              <div><dt>License</dt><dd>{candidate.license_spdx}</dd></div>
              <div><dt>Languages</dt><dd>{candidate.language_scope}</dd></div>
              <div>
                <dt>Immutable pin</dt>
                <dd>{candidate.revision ? "Reviewed" : "Required before evaluation"}</dd>
              </div>
            </dl>
            <div className="research-model-card__decision">
              <strong>Product use is off</strong>
              <p>{candidate.decision}</p>
            </div>
            {candidate.benchmark && (
              <div className="research-benchmark" aria-label="Synthetic benchmark result">
                <span>{candidate.benchmark.case_count} fictional cases</span>
                <strong>
                  {formatMetricName(candidate.benchmark.primary_metric)}{" "}
                  {formatScore(candidate.benchmark.primary_value)}
                </strong>
                {candidate.benchmark.critical_metric && typeof candidate.benchmark.critical_value === "number" && (
                  <em>
                    {formatMetricName(candidate.benchmark.critical_metric)}{" "}
                    {formatScore(candidate.benchmark.critical_value)}
                  </em>
                )}
              </div>
            )}
          </article>
        );
        })}
      </div>
    </>
  );
}

export function ResearchLab({ transport }: { transport: PromptEnhancerTransport }) {
  const [catalog, setCatalog] = useState<TextAnalysisResearchCatalog | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [view, setView] = useState<LabView>("metrics");

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    const load = transport.getTextAnalysisResearch;
    if (!load) {
      setStatus("error");
      return () => controller.abort();
    }
    void load(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setCatalog(value);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
      });
    return () => controller.abort();
  }, [transport]);

  if (status === "loading") {
    return <section className="research-lab"><div className="async-state" role="status">Loading the local research catalog…</div></section>;
  }
  if (status === "error" || !catalog) {
    return (
      <section className="research-lab">
        <div className="async-state async-state--error" role="alert">
          <strong>The methods catalog is unavailable</strong>
          <span>Restart the local app after updating Prompt Enhancer. No session was read.</span>
        </div>
      </section>
    );
  }

  const enabledModels = catalog.model_candidates.filter((item) => item.product_enabled).length;
  const failedModels = catalog.model_candidates.filter((item) => item.status === "rejected_screen").length;

  return (
    <section className="research-lab">
      <header className="research-hero route-header">
        <div>
          <p className="eyebrow">Analysis methods · catalog v{catalog.catalog_version}</p>
          <h1 tabIndex={-1}>Methods &amp; models</h1>
          <p>
            Build useful metrics, then earn trust. Explore a concrete roadmap for measuring prompts, collaboration, observable logic,
            agent answers and verified outcomes—without pretending they are intelligence.
          </p>
        </div>
        <div className="research-privacy-note">
          <strong>Safe to explore</strong>
          <span>Opening this page reads no sessions and downloads no models.</span>
          <small>Only the explicit benchmark action can download pinned public weights.</small>
        </div>
      </header>

      <div className="research-summary" aria-label="Research catalog summary">
        <div><strong>{catalog.metric_roadmap.length}</strong><span>metric questions</span></div>
        <div><strong>{catalog.methods.length}</strong><span>analysis methods</span></div>
        <div><strong>{catalog.model_candidates.length}</strong><span>local candidates</span></div>
        <div><strong>{enabledModels}</strong><span>neural models activated</span></div>
      </div>

      <aside className="research-profile-policy">
        <div>
          <strong>One profile, not one developer score</strong>
          <p>
            The dashboard will summarize independent dimensions and their evidence coverage.
            It will not rank cognitive ability, technical worth or hidden reasoning.
          </p>
        </div>
        <span>{failedModels} unsafe candidate{failedModels === 1 ? "" : "s"} already blocked</span>
      </aside>

      <TabList
        activationMode="manual"
        className="research-view-switcher"
        idPrefix={RESEARCH_TAB_PREFIX}
        label="Research catalog view"
        onChange={setView}
        tabs={RESEARCH_TABS}
        value={view}
      />

      {RESEARCH_TABS.map(({ id }) => {
        const selected = view === id;
        return (
          <div
            aria-labelledby={tabId(RESEARCH_TAB_PREFIX, id)}
            hidden={!selected}
            id={tabPanelId(RESEARCH_TAB_PREFIX, id)}
            key={id}
            role="tabpanel"
            tabIndex={0}
          >
            {selected && (
              id === "metrics" ? (
                <MetricsView catalog={catalog} transport={transport} />
              ) : id === "methods" ? (
                <MethodsView catalog={catalog} />
              ) : (
                <ModelsView catalog={catalog} transport={transport} />
              )
            )}
          </div>
        );
      })}
    </section>
  );
}
