import { useCallback, useEffect, useRef, useState } from "react";
import type { PromptEnhancerTransport, SessionInterpretation, SessionJudgments } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import "./ModelJudgePane.css";
import { SessionInferenceControl } from "../inference/SessionInferenceControl";

const LABEL_TEXT: Record<string, string> = {
  low: "low",
  medium: "medium",
  high: "high",
  cannot_judge: "cannot judge",
};

/**
 * One context per session/transport pair on screen. Every async step captures
 * the context it started in, so a slow answer for a session the reader has
 * already left cannot write over the session that replaced it.
 */
type JudgeContext = { sessionId: string; controller: AbortController; action: "explain" | "judge" | null };

/**
 * What the local model judge said about this session, shown apart from the
 * metrics on purpose: three labels per model, the questions they answer, and
 * the standing caveat. No label here is ever a metric value.
 */
export function ModelJudgePane({
  sessionId,
  transport,
}: {
  sessionId: string;
  transport: Pick<PromptEnhancerTransport, "getModelJudgments"> & Partial<Pick<PromptEnhancerTransport, "judgeSessionWithModel" | "interpretSessionWithModel" | "getInferenceModels" | "previewSessionInference" | "runSessionInference">>;
}) {
  const [data, setData] = useState<SessionJudgments | null>(null);
  const [reading, setReading] = useState<SessionInterpretation | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [state, setState] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const contextRef = useRef<JudgeContext | null>(null);

  // True only while the context that started a step is still the one on screen.
  // Success, error, finally and any follow-up reload all ask this before they
  // touch state, so nothing from a replaced context leaks through.
  const owns = useCallback((context: JudgeContext) => contextRef.current === context && !context.controller.signal.aborted, []);

  const load = useCallback(async (context: JudgeContext) => {
    try {
      const value = await transport.getModelJudgments(context.sessionId, context.controller.signal);
      if (!owns(context)) return;
      if (value.session_id !== context.sessionId || value.judgments.some((judgment) => judgment.session_id !== context.sessionId)) {
        throw new Error("model-judgments-owner-mismatch");
      }
      setData(value);
      setState("ready");
    } catch (caught) {
      if (!owns(context)) return;
      setState(caught instanceof TransportError && caught.status === 404 ? "unavailable" : "error");
    }
  }, [owns, transport]);

  useEffect(() => {
    const context: JudgeContext = { sessionId, controller: new AbortController(), action: null };
    contextRef.current = context;
    // The replacement context starts unlocked and empty: work still in flight
    // for the previous one can no longer flip these back or fill them in.
    setState("loading");
    setMessage("");
    setReading(null);
    setData(null);
    setExplaining(false);
    setBusy(false);
    void load(context);
    return () => {
      context.controller.abort();
      if (contextRef.current === context) contextRef.current = null;
    };
  }, [load, sessionId]);

  async function explain() {
    const context = contextRef.current;
    if (!context || context.action !== null || !transport.interpretSessionWithModel) return;
    context.action = "explain";
    setExplaining(true);
    setMessage("");
    try {
      const value = await transport.interpretSessionWithModel(context.sessionId, context.controller.signal);
      if (!owns(context)) return;
      if (value.session_id !== context.sessionId) throw new Error("model-interpretation-owner-mismatch");
      setReading(value);
    } catch (caught) {
      if (!owns(context)) return;
      setMessage(caught instanceof TransportError && (caught.reasonCode === "no_active_model" || caught.reasonCode === "model_not_active")
        ? "No local model is active - activate one on the Models page."
        : caught instanceof TransportError && caught.reasonCode === "model_reply_invalid"
        ? "The model returned an incomplete or invalid explanation. Try again; any previous explanation is unchanged."
        : "The model could not explain this session right now.");
    } finally {
      if (owns(context)) {
        context.action = null;
        setExplaining(false);
      }
    }
  }

  async function judgeNow() {
    const context = contextRef.current;
    if (!context || context.action !== null || !transport.judgeSessionWithModel) return;
    context.action = "judge";
    setBusy(true);
    setMessage("");
    try {
      const outcome = await transport.judgeSessionWithModel(context.sessionId, context.controller.signal);
      if (!owns(context)) return;
      if (outcome.session_id !== context.sessionId) throw new Error("model-judgment-owner-mismatch");
      setMessage(outcome.raw_valid ? `Judged by ${outcome.model_alias}.` : "The model did not answer in the required format.");
      await load(context);
    } catch (caught) {
      if (!owns(context)) return;
      setMessage(caught instanceof TransportError && (caught.reasonCode === "no_active_model" || caught.reasonCode === "model_not_active")
        ? "No local model is active - activate one on the Models page."
        : caught instanceof TransportError && caught.reasonCode === "model_reply_invalid"
        ? "The model returned an incomplete or invalid reply. Existing judgments were kept. Try again."
        : "The model judge is not available right now.");
    } finally {
      if (owns(context)) {
        context.action = null;
        setBusy(false);
      }
    }
  }

  if (state === "unavailable") return null;
  if (state === "loading") return <section className="model-judge-pane" aria-busy="true"><p className="model-judge-pane__note">Looking for model judgments…</p></section>;
  if (state === "error" || !data) return (
    <section className="model-judge-pane">
      <p className="model-judge-pane__note" role="alert">Model judgments could not be read.</p>
      <button className="button button--ghost" onClick={() => {
        const context = contextRef.current;
        if (context && context.action === null) { setState("loading"); void load(context); }
      }} type="button">Retry model judgments</button>
    </section>
  );

  const byModel = new Map<string, SessionJudgments["judgments"]>();
  for (const judgment of data.judgments) {
    const list = byModel.get(judgment.model_alias) ?? [];
    list.push(judgment);
    byModel.set(judgment.model_alias, list);
  }
  const metricKeys = Object.keys(data.questions);

  return (
    <section aria-labelledby="model-judge-pane-title" className="model-judge-pane">
      <header className="model-judge-pane__head">
        <div>
          <p className="eyebrow">Model judge · experimental, not a metric</p>
          <h3 id="model-judge-pane-title">What the local model thinks of this session</h3>
        </div>
        <div className="model-judge-pane__actions">
          {transport.interpretSessionWithModel && (
            <button className="button button--primary" disabled={explaining || busy || !data.active_model_alias} onClick={() => void explain()} title={data.active_model_alias ? `Ask ${data.active_model_alias} to explain this session` : "Activate a model on the Models page first"} type="button">
              {explaining ? "Explaining…" : "Explain this session"}
            </button>
          )}
          {transport.judgeSessionWithModel && (
            <button className="button button--ghost" disabled={busy || explaining || !data.active_model_alias} onClick={() => void judgeNow()} title={data.active_model_alias ? `Ask ${data.active_model_alias} now` : "Activate a model on the Models page first"} type="button">
              {busy ? "Judging…" : byModel.size > 0 ? "Judge again" : "Judge now"}
            </button>
          )}
        </div>
      </header>
      <SessionInferenceControl key={sessionId} sessionId={sessionId} transport={transport} onJudged={() => {
        const context = contextRef.current; if (context) void load(context);
      }} />
      {byModel.size === 0 ? (
        <p className="model-judge-pane__note">
          {data.active_model_alias
            ? `No judgment stored yet; ${data.active_model_alias} judges new sessions automatically after each index.`
            : "No judgment stored and no local model is active."}
        </p>
      ) : (
        <div className="model-judge-pane__table-wrap">
          <table className="model-judge-pane__table">
            <thead>
              <tr>
                <th scope="col">Question</th>
                {[...byModel.keys()].map((alias) => <th key={alias} scope="col">{alias}{alias === data.active_model_alias ? " · active" : ""}</th>)}
              </tr>
            </thead>
            <tbody>
              {metricKeys.map((key) => (
                <tr key={key}>
                  <th scope="row"><span className="model-judge-pane__metric">{key}</span><span className="model-judge-pane__question">{data.questions[key]}</span></th>
                  {[...byModel.entries()].map(([alias, list]) => {
                    const hit = list.find((j) => j.metric_key === key);
                    return (
                      <td key={alias} data-label={hit?.label ?? "none"}>
                        {hit ? <>
                          <span className={`model-judge-pane__label model-judge-pane__label--${hit.label}`}>{LABEL_TEXT[hit.label] ?? hit.label}</span>
                          <small className="model-judge-pane__protocol">{hit.prompt_version}</small>
                          {hit.window_fingerprint === "0".repeat(64)
                            ? <small className="model-judge-pane__protocol">Window identity missing · excluded from agreement</small>
                            : !data.accepted_prompt_versions
                            ? <small className="model-judge-pane__protocol">Protocol eligibility unavailable</small>
                            : !data.accepted_prompt_versions.includes(hit.prompt_version)
                            ? <small className="model-judge-pane__protocol">Historical protocol · excluded from agreement</small>
                            : !hit.case_fingerprint || hit.case_fingerprint === "0".repeat(64) || !data.accepted_case_version || hit.case_version !== data.accepted_case_version
                            ? <small className="model-judge-pane__protocol">Reviewed case unverified · excluded from agreement</small>
                            : null}
                        </> : <span className="model-judge-pane__none">—</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reading && (
        <section className="model-judge-pane__reading" aria-label="Model interpretation">
          {reading.summary && <p className="model-judge-pane__reading-summary">{reading.summary}</p>}
          <div className="model-judge-pane__reading-grid">
            <div>
              <h4>What went well</h4>
              {reading.strengths.length ? <ul>{reading.strengths.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="model-judge-pane__note">nothing singled out</p>}
            </div>
            <div>
              <h4>What to change next time</h4>
              {reading.improvements.length ? <ul>{reading.improvements.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="model-judge-pane__note">nothing singled out</p>}
            </div>
          </div>
          {reading.reframed_prompt && (
            <div className="model-judge-pane__reframed">
              <h4>How the first request could have been phrased</h4>
              <pre>{reading.reframed_prompt}</pre>
            </div>
          )}
          <p className="model-judge-pane__caveat">{reading.caveat} ({reading.model_alias}, {reading.metrics_seen} metric readings; {reading.prompt_version ?? "protocol unknown"})</p>
        </section>
      )}
      {message && <p className="model-judge-pane__note" aria-live="polite">{message}</p>}
      <p className="model-judge-pane__caveat">{data.caveat}</p>
    </section>
  );
}
