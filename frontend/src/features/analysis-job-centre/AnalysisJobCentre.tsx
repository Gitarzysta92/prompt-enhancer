import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AnalysisJobRecord,
  AnalysisJobState,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import type {
  RuntimeDataMode,
  RuntimeServiceState,
} from "../../shared/platform/runtimeMode";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";

const PAGE_SIZE = 25;
const POLL_INTERVAL_MS = 5_000;
const MAX_AUTO_LIST_RETRIES = 3;
const MAX_LIST_RETRY_DELAY_MS = 20_000;

export const ANALYSIS_JOB_STATES = [
  "queued",
  "preprocessing",
  "stage_n",
  "awaiting_approval",
  "completed",
  "partial",
  "failed",
  "cancelled",
  "superseded",
] as const satisfies readonly AnalysisJobState[];

const TERMINAL_STATES = new Set<AnalysisJobState>([
  "completed", "partial", "failed", "cancelled", "superseded",
]);

const STATE_PRESENTATION: Record<
  AnalysisJobState,
  { label: string; tone: PillTone }
> = {
  queued: { label: "Queued", tone: "neutral" },
  preprocessing: { label: "Preprocessing", tone: "info" },
  stage_n: { label: "Running stage", tone: "info" },
  awaiting_approval: { label: "Awaiting approval", tone: "warning" },
  completed: { label: "Completed", tone: "positive" },
  partial: { label: "Partial", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  superseded: { label: "Superseded", tone: "neutral" },
};

const REVIEWED_REASON_COPY: Record<string, string> = {
  completed: "All scheduled local stages completed.",
  partial: "The worker preserved a partial result and did not claim full completion.",
  cancellation_requested: "Cancellation was requested by the local user.",
  authorization_revoked: "Local authorization was revoked before completion.",
  automation_grant_revoked: "The automation grant was revoked before completion.",
  input_changed: "The source fingerprint changed, so this older job was superseded.",
  provenance_changed: "The estimator or provider provenance changed, so this job was superseded.",
  identity_check_unavailable: "The worker could not revalidate the exact local identity and failed closed.",
  execution_handler_unavailable: "No reviewed local execution handler was available for this job.",
  execution_handler_failed: "A reviewed local execution stage failed without exposing provider content.",
  lease_expired: "The worker lease expired before this attempt could complete.",
  automation_publication_deadline_exceeded: "The first-claim result-publication cutoff was reached; late output was not published.",
  automation_publication_clock_regressed: "The local clock moved behind the persisted publication high-water mark, so publication failed closed.",
  automation_publication_deadline_missing: "This older attempted automation job has no restart-durable publication cutoff and cannot continue.",
};

function reasonCodeOf(error: unknown): string | null {
  return typeof error === "object" && error !== null &&
    "reasonCode" in error && typeof error.reasonCode === "string"
    ? error.reasonCode
    : null;
}

function statusOf(error: unknown): number | null {
  return typeof error === "object" && error !== null &&
    "status" in error && typeof error.status === "number"
    ? error.status
    : null;
}

function safeJobError(error: unknown, operation: "list" | "detail" | "cancel"): string {
  const reason = reasonCodeOf(error);
  if (reason === "analysis_job_not_found") {
    return "This content-free job record no longer exists. Refresh the local queue.";
  }
  if (reason === "analysis_job_conflict") {
    return "The job changed before cancellation was applied. Refresh its current state.";
  }
  if (statusOf(error) === 404) {
    return "This content-free job record is no longer available.";
  }
  if (statusOf(error) === 409) {
    return "The job changed while this action was pending. Refresh before trying again.";
  }
  if (operation === "cancel") {
    return "Cancellation could not be confirmed. Refresh the job before issuing another action.";
  }
  if (operation === "detail") {
    return "The local job detail could not be verified. No provider error or session content is shown.";
  }
  return "The local job queue could not be verified. No provider error or session content is shown.";
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function progressPercent(job: AnalysisJobRecord): number {
  return Math.round((job.progress_completed / job.progress_total) * 100);
}

function hasSameIdentity(
  left: AnalysisJobRecord["identity"],
  right: AnalysisJobRecord["identity"],
): boolean {
  return left.kind === right.kind &&
    left.provider === right.provider &&
    left.project_id === right.project_id &&
    left.session_id === right.session_id &&
    left.input_fingerprint === right.input_fingerprint &&
    left.provenance_fingerprint === right.provenance_fingerprint &&
    left.estimator_plan_version === right.estimator_plan_version &&
    left.redactor_version === right.redactor_version &&
    left.provider_schema_version === right.provider_schema_version &&
    left.automation_grant_id === right.automation_grant_id &&
    left.local_only === right.local_only &&
    left.metric_keys.length === right.metric_keys.length &&
    left.metric_keys.every((key, index) => key === right.metric_keys[index]);
}

function stateExplanation(job: AnalysisJobRecord): string {
  if (job.cancel_requested && !TERMINAL_STATES.has(job.state)) {
    return "Cancellation is recorded. An active worker will stop at its next guarded boundary.";
  }
  if (job.state === "queued" && job.last_error_code === "lease_expired") {
    return `Recovered after restart or an expired worker lease. Retry ${job.attempt_count + 1} of ${job.max_attempts} is eligible at ${formatTimestamp(job.available_at)} UTC.`;
  }
  if (job.state === "queued" && job.attempt_count > 0) {
    return `A bounded retry is scheduled (${job.attempt_count + 1} of ${job.max_attempts}) for ${formatTimestamp(job.available_at)} UTC.`;
  }
  if (job.state === "queued") return "Waiting for the one local worker; no remote execution is authorized.";
  if (job.state === "preprocessing") return "The local worker is building a bounded, content-free execution packet.";
  if (job.state === "stage_n") return `The local worker is executing reviewed stage ${job.stage_number}.`;
  if (job.state === "awaiting_approval") {
    return "Paused at an explicit approval gate. Background consent never authorizes a remote call.";
  }
  const reason = job.terminal_reason_code;
  return reason !== null
    ? REVIEWED_REASON_COPY[reason] ?? "The job ended with a reviewed content-free reason; raw worker errors remain hidden."
    : "The job state is terminal.";
}

function JobProgress({ job }: { job: AnalysisJobRecord }) {
  const percentage = progressPercent(job);
  return (
    <div className="analysis-job-progress">
      <div>
        <span>{percentage}%</span>
        <span>{job.progress_completed} / {job.progress_total} units</span>
      </div>
      <progress
        aria-label={`Job progress: ${percentage}%`}
        max={job.progress_total}
        value={job.progress_completed}
      />
    </div>
  );
}

export function AnalysisJobCentre({
  runtimeMode,
  serviceState,
  transport,
}: {
  runtimeMode: RuntimeDataMode;
  serviceState: RuntimeServiceState;
  transport: PromptEnhancerTransport;
}) {
  const [filter, setFilter] = useState<AnalysisJobState | "all">("all");
  const [offset, setOffset] = useState(0);
  const [jobs, setJobs] = useState<AnalysisJobRecord[] | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalysisJobRecord | null>(null);
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [actionError, setActionError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [autoRetryExhausted, setAutoRetryExhausted] = useState(false);
  const cancelController = useRef<AbortController | null>(null);
  const listFailureRef = useRef(0);
  const jobsRef = useRef<AnalysisJobRecord[] | null>(null);
  jobsRef.current = jobs;

  const localAvailable = runtimeMode === "local_real" && serviceState === "available";
  const selectedSummary = useMemo(
    () => jobs?.find((job) => job.job_id === selectedJobId) ?? null,
    [jobs, selectedJobId],
  );
  const selected = detail?.job_id === selectedJobId ? detail : selectedSummary;

  useEffect(() => {
    cancelController.current?.abort();
    cancelController.current = null;
    setCancelling(false);
    setActionError("");
    setConfirmCancel(false);
    return () => {
      cancelController.current?.abort();
      cancelController.current = null;
    };
  }, [localAvailable, selectedJobId, transport]);

  useEffect(() => {
    // An owner/filter/page/runtime change starts a fresh bounded read-retry budget; the list
    // effect cleanup below cancels any stale poll or retry timer for the previous surface.
    listFailureRef.current = 0;
    jobsRef.current = null;
    setJobs(null);
    setListError("");
    setAutoRetryExhausted(false);
  }, [filter, localAvailable, offset, transport]);

  useEffect(() => {
    if (!localAvailable) {
      setJobs(null);
      setSelectedJobId(null);
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    let timer: number | undefined;
    setLoading(true);
    void transport
      .listAnalysisJobs(filter === "all" ? null : filter, PAGE_SIZE, offset, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        listFailureRef.current = 0;
        setListError("");
        setAutoRetryExhausted(false);
        setJobs(page.jobs);
        const hasLiveJobs = page.jobs.some((job) => !TERMINAL_STATES.has(job.state));
        if (hasLiveJobs) {
          timer = window.setTimeout(
            () => setRefreshKey((value) => value + 1),
            POLL_INTERVAL_MS,
          );
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setListError(safeJobError(error, "list"));
        // Last verified rows are preserved and labelled stale. Only the read is retried,
        // automatically and with a bounded backoff; job commands are never retried here.
        const known = jobsRef.current;
        const liveKnownJobs = known === null || known.some((item) => !TERMINAL_STATES.has(item.state));
        const failures = listFailureRef.current + 1;
        listFailureRef.current = failures;
        if (!liveKnownJobs) return;
        if (failures > MAX_AUTO_LIST_RETRIES) {
          setAutoRetryExhausted(true);
          return;
        }
        timer = window.setTimeout(
          () => setRefreshKey((value) => value + 1),
          Math.min(POLL_INTERVAL_MS * 2 ** (failures - 1), MAX_LIST_RETRY_DELAY_MS),
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [filter, localAvailable, offset, refreshKey, transport]);

  useEffect(() => {
    if (!localAvailable || selectedJobId === null) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    void transport
      .getAnalysisJob(selectedJobId, controller.signal)
      .then((job) => {
        if (controller.signal.aborted) return;
        if (job.job_id !== selectedJobId || (selectedSummary !== null && !hasSameIdentity(selectedSummary.identity, job.identity))) {
          setDetail(null);
          setDetailError(
            "The local job identity changed unexpectedly. Refresh the queue before acting on this receipt.",
          );
          return;
        }
        setDetail(job);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setDetailError(safeJobError(error, "detail"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [localAvailable, refreshKey, selectedJobId, selectedSummary, transport]);

  function changeFilter(value: string) {
    if (value !== "all" && !ANALYSIS_JOB_STATES.includes(value as AnalysisJobState)) return;
    setFilter(value as AnalysisJobState | "all");
    setOffset(0);
    setSelectedJobId(null);
    setDetail(null);
    setConfirmCancel(false);
  }

  function manualRefresh() {
    // A person-initiated read restarts the bounded automatic retry budget. This issues reads
    // only; it never mutates or retries job commands.
    listFailureRef.current = 0;
    setAutoRetryExhausted(false);
    setRefreshKey((value) => value + 1);
  }

  function openJob(jobId: string) {
    setSelectedJobId(jobId);
    setDetail(null);
    setDetailError("");
    setActionError("");
    setConfirmCancel(false);
  }

  async function cancelSelected() {
    if (!selected || cancelController.current || !localAvailable) return;
    const target = selected;
    const controller = new AbortController();
    cancelController.current = controller;
    const owns = () => cancelController.current === controller && !controller.signal.aborted;
    setCancelling(true);
    setActionError("");
    try {
      const updated = await transport.cancelAnalysisJob(target.job_id, controller.signal);
      if (!owns()) return;
      if (updated.job_id !== target.job_id || !hasSameIdentity(target.identity, updated.identity)) {
        setActionError(
          "The cancellation response did not match the selected job identity. Refresh before trying again.",
        );
        return;
      }
      setDetail(updated);
      setJobs((current) => current?.map((job) =>
        job.job_id === updated.job_id ? updated : job,
      ) ?? null);
      setConfirmCancel(false);
    } catch (error) {
      if (owns()) setActionError(safeJobError(error, "cancel"));
    } finally {
      if (owns()) {
        cancelController.current = null;
        setCancelling(false);
      }
    }
  }

  if (runtimeMode === "synthetic_demo") {
    return (
      <section aria-labelledby="analysis-job-centre-title" className="analysis-job-centre">
        <header className="analysis-job-centre__header route-header">
          <div>
            <p className="eyebrow">Synthetic demo · fictional fixtures only</p>
            <h1 id="analysis-job-centre-title">Analysis jobs</h1>
            <p>Durable execution is disabled in demo mode.</p>
          </div>
        </header>
        <div className="analysis-job-centre__boundary" role="note">
          <strong>No jobs ran</strong>
          <span>
            This screen does not invent queue history, retries, progress, or completion.
            Start the Local real runtime to inspect the authenticated SQLite queue.
          </span>
        </div>
      </section>
    );
  }

  if (serviceState !== "available") {
    return (
      <section aria-labelledby="analysis-job-centre-title" className="analysis-job-centre">
        <header className="analysis-job-centre__header route-header">
          <div>
            <p className="eyebrow">Local real · content-free queue</p>
            <h1 id="analysis-job-centre-title">Analysis jobs</h1>
          </div>
        </header>
        <div className="analysis-job-centre__boundary" role="status">
          <strong>{serviceState === "checking" ? "Checking the local service" : "Local service unavailable"}</strong>
          <span>
            {serviceState === "checking"
              ? "Queue requests stay paused until the loopback health check succeeds."
              : "No cached or fictional queue is shown. Restart the local service, then reopen this screen."}
          </span>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="analysis-job-centre-title" className="analysis-job-centre">
      <header className="analysis-job-centre__header route-header">
        <div>
          <p className="eyebrow">Local real · SQLite queue · one local worker</p>
          <h1 id="analysis-job-centre-title">Analysis jobs</h1>
          <p>Inspect durable state, bounded retries, approval pauses, recovery, and cancellation without opening session text.</p>
        </div>
        <div className="analysis-job-centre__health" role="status">
          <span aria-hidden="true" />
          <strong>Loopback service available</strong>
          <small>Auto-refreshes while jobs are live</small>
        </div>
      </header>

      <div className="analysis-job-centre__controls">
        <label>
          <span>Queue state</span>
          <select value={filter} onChange={(event) => changeFilter(event.target.value)}>
            <option value="all">All states</option>
            {ANALYSIS_JOB_STATES.map((state) => (
              <option key={state} value={state}>{STATE_PRESENTATION[state].label}</option>
            ))}
          </select>
        </label>
        <button
          className="button button--secondary button--compact"
          disabled={loading}
          onClick={manualRefresh}
          type="button"
        >
          {loading ? "Refreshing…" : "Refresh queue"}
        </button>
      </div>

      {listError && (
        <div className="analysis-job-centre__error" role="alert">
          <strong>Queue unavailable</strong>
          <span>{listError}</span>
          {jobs !== null && (
            <small>The receipts below are the last verified response and may now be stale.</small>
          )}
          {autoRetryExhausted && (
            <small>Automatic refresh paused after repeated read failures. Retry safely resumes verified reads.</small>
          )}
          <button className="button button--secondary button--compact" onClick={manualRefresh} type="button">
            Retry safely
          </button>
        </div>
      )}

      <div className="analysis-job-centre__layout">
        <section aria-labelledby="analysis-job-list-title" className="analysis-job-list">
          <div className="analysis-job-list__heading">
            <div>
              <p className="eyebrow">Durable receipts</p>
              <h2 id="analysis-job-list-title">Jobs</h2>
            </div>
            <span>{jobs?.length ?? 0} on this page</span>
          </div>

          {loading && jobs === null ? (
            <div aria-busy="true" className="analysis-job-list__empty" role="status">Loading content-free job receipts…</div>
          ) : jobs?.length === 0 ? (
            <div className="analysis-job-list__empty" role="status">
              No durable jobs match this filter. Missing jobs are not treated as completed work.
            </div>
          ) : (
            <div className="analysis-job-list__items">
              {jobs?.map((job) => {
                const presentation = STATE_PRESENTATION[job.state];
                return (
                  <button
                    aria-pressed={selectedJobId === job.job_id}
                    className="analysis-job-card"
                    key={job.job_id}
                    onClick={() => openJob(job.job_id)}
                    type="button"
                  >
                    <span className="analysis-job-card__topline">
                      <StatusPill tone={presentation.tone}>{presentation.label}</StatusPill>
                      <time dateTime={job.updated_at}>{formatTimestamp(job.updated_at)} UTC</time>
                    </span>
                    <strong>{job.identity.kind === "session_quality" ? "Session quality" : "Synthetic validation"}</strong>
                    <span>
                      <ProviderBadge provider={job.identity.provider} />
                      {" "}Session {shortId(job.identity.session_id)} · {job.identity.metric_keys.length} metrics
                    </span>
                    <JobProgress job={job} />
                    {job.state === "queued" && job.last_error_code === "lease_expired" && (
                      <small>Recovered after restart · bounded retry pending</small>
                    )}
                    {job.cancel_requested && !TERMINAL_STATES.has(job.state) && (
                      <small>Cancellation requested</small>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <footer className="analysis-job-list__pagination" aria-label="Job pages">
            <button
              aria-describedby={offset === 0 || loading ? "analysis-jobs-newer-disabled-reason" : undefined}
              className="button button--secondary button--compact"
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              type="button"
            >
              Newer jobs
            </button>
            <span>Offset {offset}</span>
            <button
              aria-describedby={(jobs?.length ?? 0) < PAGE_SIZE || loading ? "analysis-jobs-older-disabled-reason" : undefined}
              className="button button--secondary button--compact"
              disabled={(jobs?.length ?? 0) < PAGE_SIZE || loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              type="button"
            >
              Older jobs
            </button>
            <span className="sr-only" id="analysis-jobs-newer-disabled-reason">{loading ? "Wait for the current job page to finish loading." : "You are already viewing the newest jobs."}</span>
            <span className="sr-only" id="analysis-jobs-older-disabled-reason">{loading ? "Wait for the current job page to finish loading." : "There are no older jobs after this page."}</span>
          </footer>
        </section>

        <aside aria-label="Selected job detail" className="analysis-job-detail">
          {selected === null ? (
            <div className="analysis-job-detail__empty">
              <p className="eyebrow">Exact receipt</p>
              <h2>Select a job</h2>
              <p>Details contain pseudonymous targets, versions, progress, and safe state codes—never prompts or model commentary.</p>
            </div>
          ) : (
            <>
              <header>
                <div>
                  <p className="eyebrow">Exact receipt · {shortId(selected.job_id)}</p>
                  <h2>{selected.identity.kind === "session_quality" ? "Session quality job" : "Synthetic validation job"}</h2>
                </div>
                <StatusPill tone={STATE_PRESENTATION[selected.state].tone}>
                  {STATE_PRESENTATION[selected.state].label}
                </StatusPill>
              </header>
              {detailLoading && <p aria-live="polite" className="analysis-job-detail__loading">Verifying current detail…</p>}
              {detailError && <p className="analysis-job-detail__error" role="alert">{detailError}</p>}
              <p className="analysis-job-detail__explanation">{stateExplanation(selected)}</p>
              <JobProgress job={selected} />
              <dl>
                <div><dt>Job ID</dt><dd><code>{selected.job_id}</code></dd></div>
                <div><dt>Project</dt><dd><code>{selected.identity.project_id}</code></dd></div>
                <div><dt>Session</dt><dd><code>{selected.identity.session_id}</code></dd></div>
                <div><dt>Provider</dt><dd><ProviderBadge provider={selected.identity.provider} /></dd></div>
                <div><dt>Attempts</dt><dd>{selected.attempt_count} used · {selected.max_attempts} maximum</dd></div>
                <div><dt>Updated</dt><dd><time dateTime={selected.updated_at}>{formatTimestamp(selected.updated_at)} UTC</time></dd></div>
                <div><dt>Estimator plan</dt><dd><code>{selected.identity.estimator_plan_version}</code></dd></div>
                <div><dt>Redactor</dt><dd><code>{selected.identity.redactor_version}</code></dd></div>
                <div><dt>Provider schema</dt><dd><code>{selected.identity.provider_schema_version}</code></dd></div>
                <div><dt>Execution boundary</dt><dd>Local only · durable content-free state</dd></div>
              </dl>
              <section aria-labelledby="analysis-job-metrics-title" className="analysis-job-detail__metrics">
                <h3 id="analysis-job-metrics-title">Selected metrics ({selected.identity.metric_keys.length})</h3>
                <ul>
                  {selected.identity.metric_keys.map((key) => <li key={key}><code>{key}</code></li>)}
                </ul>
              </section>

              {actionError && <p className="analysis-job-detail__error" role="alert">{actionError}</p>}
              {!TERMINAL_STATES.has(selected.state) && !selected.cancel_requested && (
                <div className="analysis-job-detail__actions">
                  {confirmCancel ? (
                    <div aria-label="Confirm job cancellation" role="group">
                      <p>Cancel this exact local job? Completed receipts are not deleted.</p>
                      <button className="button button--danger-ghost" disabled={cancelling} onClick={() => void cancelSelected()} type="button">
                        {cancelling ? "Cancelling…" : "Confirm cancellation"}
                      </button>
                      <button className="button button--secondary" disabled={cancelling} onClick={() => setConfirmCancel(false)} type="button">
                        Keep job
                      </button>
                    </div>
                  ) : (
                    <button className="button button--danger-ghost" onClick={() => setConfirmCancel(true)} type="button">
                      Cancel job
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
