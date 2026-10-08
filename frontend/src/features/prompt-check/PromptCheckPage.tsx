import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  PromptCheckRecord,
  PromptCheckConfiguration,
  PromptCheckPreview,
  PromptCheckRequest,
  PromptCheckResult,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { PromptMetricRadar, PromptMetricTrend, promptMetricQualityValue } from "./promptCheckPlots";
import "./PromptCheckPage.css";

type Reading = PromptCheckResult["metrics"][number];
type StoredCheckState = "idle" | "loading" | "ready" | "not_found" | "error";

const SHORT_NAMES: Record<string, string> = {
  "prompt.task_definition_coverage": "Task definition",
  "prompt.problem_evidence_quality": "Problem evidence",
  "prompt.context_sufficiency": "Context cues",
  "prompt.constraint_precision": "Constraint precision",
  "prompt.acceptance_testability": "Acceptance checks",
  "prompt.deliverable_contract": "Deliverable",
};

export function shortName(key: string): string {
  return SHORT_NAMES[key] ?? key;
}

function parsePriorMessages(raw: string): PromptCheckRequest["prior_messages"] {
  const lines = raw.split(/\r?\n/);
  const messages: { role: "user" | "assistant"; content: string }[] = [];
  let current: { role: "user" | "assistant"; content: string } | null = null;
  for (const line of lines) {
    const match = line.match(/^\s*(user|assistant|you|agent|me|ai)\s*:\s*(.*)$/i);
    if (match) {
      if (current && current.content.trim()) messages.push({ ...current, content: current.content.trim() });
      const role = /^(user|you|me)$/i.test(match[1]) ? "user" : "assistant";
      current = { role, content: match[2] };
    } else if (current) {
      current.content += `\n${line}`;
    } else if (line.trim()) {
      current = { role: "user", content: line };
    }
  }
  if (current && current.content.trim()) messages.push({ ...current, content: current.content.trim() });
  return messages.slice(-24);
}

function readingValue(reading: Reading): number | null {
  return reading.state === "known" && typeof reading.value === "number" && Number.isFinite(reading.value) ? reading.value : null;
}

export function promptReadingLabel(reading: Reading): string {
  if (reading.state !== "known") return reading.state.replace(/_/g, " ");
  if (typeof reading.numerator === "number" && Number.isFinite(reading.numerator)
    && typeof reading.denominator === "number" && Number.isFinite(reading.denominator) && reading.denominator > 0) {
    return `${reading.numerator}/${reading.denominator}`;
  }
  const value = readingValue(reading);
  return value === null ? "Value unavailable" : new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(value);
}

/**
 * Prompt check: paste the prompt you are about to send (and, if useful, the
 * earlier turns), get the same deterministic prompt cues the dashboard
 * computes for sessions, the local model's commentary and a reformulated
 * prompt, plus a history of your checks with trend plots. Only metrics are
 * stored; the text never is.
 */
export function PromptCheckPage({
  checkId,
  navigate,
  sessionId,
  transport,
}: {
  checkId?: string;
  navigate: (route: AppRoute) => void;
  sessionId?: string;
  transport: Pick<PromptEnhancerTransport, "checkPrompt" | "getPromptCheckHistory" | "getPromptCheck" | "getPromptCheckConfiguration" | "previewPrompt">;
}) {
  const [configuration, setConfiguration] = useState<PromptCheckConfiguration | null>(
    transport.getPromptCheckConfiguration ? null : { remote: false, provider: "local", model: null });
  const [configurationError, setConfigurationError] = useState(false);
  const [preview, setPreview] = useState<{ value: PromptCheckPreview; request: PromptCheckRequest } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setConfigurationError(false);
    if (transport.getPromptCheckConfiguration) {
      setConfiguration(null);
      transport.getPromptCheckConfiguration(controller.signal).then((value) => {
        if (!controller.signal.aborted) setConfiguration(value);
      }).catch(() => { if (!controller.signal.aborted) setConfigurationError(true); });
    }
    return () => controller.abort();
  }, [transport]);
  const [prompt, setPrompt] = useState("");
  const [prior, setPrior] = useState("");
  const [wantCommentary, setWantCommentary] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PromptCheckResult | null>(null);
  const [history, setHistory] = useState<PromptCheckRecord[]>([]);
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [stored, setStored] = useState<PromptCheckRecord | null>(null);
  const [storedState, setStoredState] = useState<StoredCheckState>("idle");
  const [storedRetry, setStoredRetry] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const historyRequest = useRef<AbortController | null>(null);
  const checkRequest = useRef<AbortController | null>(null);
  const copyVersion = useRef(0);

  const loadHistory = useCallback(async () => {
    historyRequest.current?.abort();
    const controller = new AbortController();
    historyRequest.current = controller;
    const owns = () => historyRequest.current === controller && !controller.signal.aborted;
    setHistoryState("loading");
    try {
      const page = await transport.getPromptCheckHistory(60, 0, controller.signal);
      if (!owns()) return;
      setHistory(page.checks);
      setHistoryState("ready");
    } catch (caught) {
      if (!owns()) return;
      setHistoryState(caught instanceof TransportError && caught.status === 404 ? "unavailable" : "error");
    } finally {
      if (owns()) historyRequest.current = null;
    }
  }, [transport]);

  useEffect(() => {
    void loadHistory();
    return () => { historyRequest.current?.abort(); historyRequest.current = null; };
  }, [loadHistory]);

  useEffect(() => {
    setBusy(false);
    setError("");
    setCopied(false);
    setCopyError("");
    return () => {
      checkRequest.current?.abort();
      checkRequest.current = null;
      copyVersion.current += 1;
    };
  }, [checkId, sessionId, transport]);

  useEffect(() => { setResult(null); }, [sessionId, transport]);
  useEffect(() => { setPreview(null); }, [checkId, sessionId, transport]);

  useEffect(() => {
    if (!checkId) {
      setStored(null);
      setStoredState("idle");
      return;
    }
    setStored(null);
    setStoredState("loading");
    const controller = new AbortController();
    transport.getPromptCheck(checkId, controller.signal).then((record) => {
      if (controller.signal.aborted) return;
      setStored(record);
      setResult(null);
      setStoredState("ready");
    }).catch((caught) => {
      if (controller.signal.aborted) return;
      setStored(null);
      setStoredState(caught instanceof TransportError && caught.status === 404 ? "not_found" : "error");
    });
    return () => controller.abort();
  }, [checkId, storedRetry, transport]);

  async function run(approved?: { value: PromptCheckPreview; request: PromptCheckRequest }) {
    const text = prompt.trim();
    if (!text || checkRequest.current) return;
    const controller = new AbortController();
    checkRequest.current = controller;
    const owns = () => checkRequest.current === controller && !controller.signal.aborted;
    copyVersion.current += 1;
    setBusy(true);
    setError("");
    setCopied(false);
    setCopyError("");
    try {
      const request: PromptCheckRequest = approved?.request ?? {
        prompt: text,
        prior_messages: sessionId ? [] : parsePriorMessages(prior),
        session_id: sessionId ?? null,
        provider: "other",
        want_commentary: wantCommentary && !(configuration?.remote && sessionId),
      };
      if (configuration?.remote && request.want_commentary && !approved) {
        if (!transport.previewPrompt) throw new Error("Preview unavailable");
        const value = await transport.previewPrompt(request, controller.signal);
        if (owns()) setPreview({ value, request });
        return;
      }
      const value = await transport.checkPrompt(approved
        ? { ...request, remote_approval: approved.value.approval } : request, controller.signal);
      if (!owns()) return;
      setResult(value);
      setPreview(null);
      await loadHistory();
    } catch (caught) {
      if (!owns()) return;
      if (caught instanceof TransportError && caught.status === 428) {
        setPreview(null);
        setError("The preview expired or changed. Check the prompt again to review a new preview.");
        return;
      }
      setError(caught instanceof TransportError && caught.status === 422
        ? "The prompt or the earlier turns are too long or empty."
        : "The check could not be confirmed. Your draft is still here. Retry history to check whether metrics were saved.");
    } finally {
      if (owns()) { checkRequest.current = null; setBusy(false); }
    }
  }

  async function copyReformulation(text: string) {
    const version = ++copyVersion.current;
    setCopied(false);
    setCopyError("");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      if (version === copyVersion.current) setCopied(true);
    } catch {
      if (version === copyVersion.current) setCopyError("Clipboard access is unavailable. Select and copy the reformulated prompt below.");
    }
  }

  const trend = useMemo(() => [...history].reverse(), [history]);

  if (historyState === "unavailable") {
    return (
      <section aria-labelledby="prompt-check-title" className="prompt-check">
        <header className="prompt-check__head route-header">
          <div>
            <p className="eyebrow">Prompt check</p>
            <h1 id="prompt-check-title">Check a prompt</h1>
            <p className="prompt-check__note">Prompt checks are not available in this runtime.</p>
          </div>
        </header>
        <p className="prompt-check__note">Open the local application with the prompt-check service enabled. A local model is optional for commentary; deterministic cues do not require one.</p>
        <button className="button button--ghost" onClick={() => navigate({ name: "overview" })} type="button">Back to overview</button>
      </section>
    );
  }

  return (
    <section aria-labelledby="prompt-check-title" className="prompt-check">
      <header className="prompt-check__head route-header">
        <div>
          <p className="eyebrow">Prompt check · before you send it</p>
          <h1 id="prompt-check-title">Check a prompt</h1>
          <p className="prompt-check__lede">
            Paste the prompt you are about to give Claude Code, Codex or any model. You get the same deterministic cues the dashboard
            measures for whole sessions, with optional model commentary and a reformulated version. Only metrics are kept for the plots below.
            {configuration?.remote ? ` Commentary uses ${configuration.model} through your configured LiteLLM gateway. Review the redacted text before sending it.`
              : " Model commentary runs locally when a local model is active."}
          </p>
        </div>
      </header>

      {configurationError && <p role="alert">Model configuration could not be loaded. Reopen this page to retry.</p>}
      <form
        className="prompt-check__form"
        onSubmit={(event) => { event.preventDefault(); void run(); }}
      >
        {sessionId && (
          <p className="prompt-check__session-banner">
            {configuration?.remote ? "Automatic session context is unavailable for LiteLLM. Check a manually supplied prompt instead."
              : "Using the last turns of the selected session as context - the model sees where that conversation stands."}
            <button className="link-button" onClick={() => navigate({ name: "prompt_checks" })} type="button">Check without session context instead</button>
          </p>
        )}
        <label>
          <span>Prompt</span>
          <textarea aria-label="Prompt to check" maxLength={20000} disabled={busy} onChange={(e) => { setPrompt(e.currentTarget.value); setPreview(null); }} placeholder="The prompt you are about to send…" rows={6} value={prompt} />
        </label>
        <label hidden={Boolean(sessionId)}>
          <span>Earlier turns (optional - one per line as <code>user: …</code> / <code>assistant: …</code>; the check reads them as context)</span>
          <textarea aria-label="Earlier turns" maxLength={40000} disabled={busy} onChange={(e) => { setPrior(e.currentTarget.value); setPreview(null); }} placeholder={"user: We looked at the uploader yesterday\nassistant: The retry loop is in client.py"} rows={3} value={prior} />
        </label>
        <div className="prompt-check__controls">
          <label className="prompt-check__toggle">
            <input disabled={busy || Boolean(configuration?.remote && sessionId)} checked={wantCommentary && !(configuration?.remote && Boolean(sessionId))} onChange={(e) => { setWantCommentary(e.currentTarget.checked); setPreview(null); }} type="checkbox" />
            <span>{configuration?.remote ? `Ask ${configuration.model} via LiteLLM for commentary and a reformulation` : "Ask the local model for commentary and a reformulation (slower)"}</span>
          </label>
          <button aria-describedby={busy || !prompt.trim() ? "prompt-check-submit-requirement" : undefined} className="button button--primary" disabled={busy || !prompt.trim() || !configuration} type="submit">{busy ? "Checking…" : "Check prompt"}</button>
        </div>
        <span className="sr-only" id="prompt-check-submit-requirement">{busy ? "Wait for the current prompt check to finish." : "Enter a prompt before running the check."}</span>
      </form>
      {preview && (
        <section aria-label="Review before sending to LiteLLM" className="prompt-check__card">
          <h2>Review before sending to LiteLLM</h2>
          <p>This text will be sent to {preview.value.model} through your configured gateway. Redaction can miss sensitive details; review everything below. The preview expires after 10 minutes.</p>
          {preview.value.messages.map((message, index) => (
            <details key={index} open={message.role === "user"}>
              <summary>{message.role === "system" ? "Model instructions" : "Redacted prompt, context and findings"}</summary>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.content}</pre>
            </details>
          ))}
          <button className="button button--primary" disabled={busy} type="button" onClick={() => void run(preview)}>Send reviewed text to LiteLLM</button>
          <button className="button button--ghost" disabled={busy} type="button" onClick={() => setPreview(null)}>Cancel</button>
        </section>
      )}
      {error && <p className="prompt-check__error" role="alert">{error}</p>}

      {result && (
        <section aria-labelledby="prompt-check-result-title" className="prompt-check__result">
          <h2 id="prompt-check-result-title">Result</h2>
          <div className="prompt-check__result-grid">
            <article className="prompt-check__card">
              <h3>Prompt cues</h3>
              <PromptMetricRadar readings={result.metrics.map((m) => ({ key: m.key, label: shortName(m.key), value: readingValue(m), higherIsBetter: m.higher_is_better }))} />
              <ul className="prompt-check__metrics">
                {result.metrics.map((m) => (
                  <li key={m.key} data-state={m.state}>
                    <div className="prompt-check__metric-head">
                      <strong>{m.display_name}</strong>
                      <span className="prompt-check__metric-value">
                        {promptReadingLabel(m)}
                      </span>
                    </div>
                    {m.cues.length > 0 && (
                      <ul className="prompt-check__cues">
                        {m.cues.map((cue) => (
                          <li key={cue.code} data-status={cue.status}>
                            <span aria-hidden="true">{cue.status === "detected" ? "✓" : cue.status === "missing" ? "✗" : "•"}</span>
                            {cue.label}{cue.status === "counted" && cue.count !== null && cue.count !== undefined ? ` · ${cue.count}` : ""}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
              <p className="prompt-check__note">{result.other_metric_families_note}</p>
            </article>
            <article className="prompt-check__card">
              <h3>Context read from the prompt</h3>
              <dl className="prompt-check__context">
                <div><dt>Task type</dt><dd>{result.context.task_type}</dd></div>
                <div><dt>Language</dt><dd>{result.context.language}</dd></div>
                <div><dt>Size</dt><dd>{result.context.prompt_words} words · {result.context.sentence_count} sentences · {result.context.bullet_count} bullets</dd></div>
                <div><dt>References</dt><dd>{result.context.file_references} files · {result.context.code_identifiers} identifiers · {result.context.urls} links</dd></div>
                <div><dt>Relies on earlier turns</dt><dd>{result.context.depends_on_prior_context ? "yes" : "no"}{result.context.prior_context_supplied ? ` · ${result.context.prior_context_supplied} supplied` : " · none supplied"}</dd></div>
                <div><dt>Verification asked for</dt><dd>{result.context.verification_requested ? "yes" : "no"}</dd></div>
              </dl>
              {result.context.missing_elements.length > 0 && (
                <>
                  <h4>Consider adding</h4>
                  <ul className="prompt-check__missing">
                    {result.context.missing_elements.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </>
              )}
              <p className="prompt-check__summary"><strong>Summary for an agent:</strong> {result.summary}</p>
            </article>
          </div>

          <article className="prompt-check__card prompt-check__commentary" data-state={result.commentary.state}>
            <h3>{result.commentary.inference_provider === "litellm" ? `What ${result.commentary.model_alias} would change` : "What the local model would change"} <small>· model output, not a metric</small></h3>
            {result.commentary.state === "ok" ? (
              <>
                {result.commentary.findings.length > 0 && (
                  <ul className="prompt-check__findings">
                    {result.commentary.findings.map((f, index) => (
                      <li key={`${f.aspect}-${index}`} data-severity={f.severity}>
                        <span className="prompt-check__severity">{f.severity}</span>
                        <div><strong>{f.aspect}</strong> - {f.why}<br /><em>{f.suggestion}</em></div>
                      </li>
                    ))}
                  </ul>
                )}
                {result.commentary.reformulated_elements.length > 0 && (
                  <table className="prompt-check__elements">
                    <thead><tr><th scope="col">Element</th><th scope="col">You wrote</th><th scope="col">Suggested</th></tr></thead>
                    <tbody>
                      {result.commentary.reformulated_elements.map((e, index) => (
                        <tr key={`${e.element}-${index}`}><th scope="row">{e.element}</th><td>{e.original ?? "—"}</td><td>{e.suggested}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {result.commentary.reformulated_prompt && (
                  <div className="prompt-check__reformulated">
                    <div className="prompt-check__reformulated-head">
                      <h4>Reformulated prompt</h4>
                      <button
                        className="button button--ghost"
                        onClick={() => void copyReformulation(result.commentary.reformulated_prompt ?? "")}
                        type="button"
                      >
                        {copied ? "Copied" : "Copy"}
                      </button>
                    </div>
                    {copyError && <p className="prompt-check__error" role="alert">{copyError}</p>}
                    <pre>{result.commentary.reformulated_prompt}</pre>
                  </div>
                )}
                {result.commentary.notes && <p className="prompt-check__note">{result.commentary.notes}</p>}
                <p className="prompt-check__caveat">{result.commentary.caveat} ({result.commentary.model_alias})</p>
              </>
            ) : result.commentary.state === "no_active_model" ? (
              <p className="prompt-check__note">No local model is active. Activate one on the <button className="link-button" onClick={() => navigate({ name: "models" })} type="button">Models page</button> to get commentary and a reformulation; the cues above are complete without it.</p>
            ) : result.commentary.state === "skipped" ? (
              <p className="prompt-check__note">Commentary was not requested.</p>
            ) : (
              <p className="prompt-check__note">The model did not answer usably this time ({result.commentary.state.replace(/_/g, " ")}); the cues above stand.</p>
            )}
          </article>
        </section>
      )}

      {checkId && storedState === "loading" && (
        <p className="prompt-check__note" role="status">Loading stored check…</p>
      )}
      {checkId && storedState === "not_found" && (
        <div className="prompt-check__note" role="status">
          <p>No stored check was found for this link.</p>
          <button className="button button--ghost" onClick={() => setStoredRetry((value) => value + 1)} type="button">Retry stored check</button>
        </div>
      )}
      {checkId && storedState === "error" && (
        <div className="prompt-check__note" role="alert">
          <p>The stored check could not be read.</p>
          <button className="button button--ghost" onClick={() => setStoredRetry((value) => value + 1)} type="button">Retry stored check</button>
        </div>
      )}

      {storedState === "ready" && stored && (
        <section className="prompt-check__result" aria-label="Stored check">
          <h2>Stored check</h2>
          <p className="prompt-check__note">
            {new Date(stored.created_at).toLocaleString()} · {stored.provider}{stored.agent_model ? ` · ${stored.agent_model}` : ""} · {stored.task_type} · {stored.prompt_chars} characters.
            Only metrics were kept - the prompt itself was never stored.
          </p>
          <PromptMetricRadar readings={stored.metrics.map((m) => ({ key: m.key, label: shortName(m.key), value: readingValue(m as Reading), higherIsBetter: m.higher_is_better }))} />
        </section>
      )}

      <section aria-labelledby="prompt-check-history-title" className="prompt-check__history">
        <h2 id="prompt-check-history-title">Your checks over time</h2>
        {historyState === "loading" && <p className="prompt-check__note">Loading…</p>}
        {historyState === "error" && <p className="prompt-check__note" role="alert">The history could not be read.</p>}
        {(historyState === "error" || error !== "") && <button className="button button--ghost" disabled={historyState === "loading"} onClick={() => void loadHistory()} type="button">Retry history</button>}
        {historyState === "ready" && history.length === 0 && <p className="prompt-check__note">No check yet. The first one appears here with its plots.</p>}
        {historyState === "ready" && history.length > 0 && (
          <>
            <PromptMetricTrend
              series={Object.keys(SHORT_NAMES).map((key) => ({
                key,
                label: shortName(key),
                higherIsBetter: trend.map((record) => record.metrics.find((metric) => metric.key === key)).find((reading) => reading !== undefined)?.higher_is_better ?? true,
                points: trend.map((record, index) => {
                  const reading = record.metrics.find((m) => m.key === key);
                  return { x: index, value: reading ? readingValue(reading as Reading) : null, at: record.created_at };
                }),
              }))}
            />
            <div className="prompt-check__table-wrap">
              <table className="prompt-check__table">
                <caption>Quality-oriented cue values, matching the plots: higher is stronger. Missing readings are not zero.</caption>
                <thead>
                  <tr><th scope="col">When</th><th scope="col">Via</th><th scope="col">Task</th><th scope="col">Size</th>{Object.keys(SHORT_NAMES).map((key) => <th key={key} scope="col">{shortName(key)}</th>)}<th scope="col">Model</th></tr>
                </thead>
                <tbody>
                  {history.map((record) => (
                    <tr key={record.check_id}>
                      <td><button className="link-button" onClick={() => navigate({ name: "prompt_checks", checkId: record.check_id })} type="button">{new Date(record.created_at).toLocaleString()}</button></td>
                      <td>{record.provider}{record.agent_model ? ` · ${record.agent_model}` : ""}</td>
                      <td>{record.task_type}</td>
                      <td>{record.prompt_chars}</td>
                      {Object.keys(SHORT_NAMES).map((key) => {
                        const reading = record.metrics.find((m) => m.key === key);
                        const raw = reading ? readingValue(reading as Reading) : null;
                        const value = promptMetricQualityValue(raw, reading?.higher_is_better ?? true);
                        const detail = raw !== null && reading?.higher_is_better === false ? `Raw ${Math.round(raw * 100)}%; lower is better` : undefined;
                        return <td key={key} data-state={reading?.state ?? "unknown"} title={detail}>{value === null ? "—" : `${Math.round(value * 100)}%`}</td>;
                      })}
                      <td>{record.commentary_state === "ok" ? record.commentary_model_alias : record.commentary_state.replace(/_/g, " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </section>
  );
}
