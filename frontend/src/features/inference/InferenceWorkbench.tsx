import { useEffect, useRef, useState } from "react";
import type { InferenceChatRequest, InferenceModel, InferencePreview, ManualAnalysisRequest, PromptEnhancerTransport } from "../../shared/api/contracts";
import { InferenceReview } from "./InferenceReview";

type Mode = "chat" | "interpret" | "judge";
type Draft = { mode: "chat"; request: InferenceChatRequest } | { mode: "interpret" | "judge"; request: ManualAnalysisRequest };
export function InferenceWorkbench({ transport }: { transport: Partial<PromptEnhancerTransport> }) {
  const [models, setModels] = useState<InferenceModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [mode, setMode] = useState<Mode>("chat");
  const [text, setText] = useState("");
  const [history, setHistory] = useState<InferenceChatRequest["messages"]>([]);
  const [preview, setPreview] = useState<{ value: InferencePreview; draft: Draft } | null>(null);
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setModels([]); setPreview(null); setHistory([]); setOutput(""); setError(""); setBusy(false);
    void transport.getInferenceModels?.(controller.signal).then((catalog) => {
      if (controller.signal.aborted) return;
      setModels(catalog.models);
      setModelId((catalog.models.find((item) => item.remote && item.available) ?? catalog.models.find((item) => item.available))?.id ?? "");
    }).catch(() => { if (!controller.signal.aborted) setError("Model providers could not be loaded."); });
    return () => { controller.abort(); operation.current?.abort(); operation.current = null; };
  }, [transport]);
  if (!transport.getInferenceModels) return null;
  const model = models.find((item) => item.id === modelId);
  function reset() { operation.current?.abort(); setPreview(null); setHistory([]); setOutput(""); setError(""); }
  async function send(draft: Draft, approval?: string) {
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError(""); setOutput(""); setPreview(null);
    const owns = () => operation.current === controller && !controller.signal.aborted;
    try {
      if (draft.mode === "chat") {
        if (!transport.streamInferenceChat) throw new Error();
        const result = await transport.streamInferenceChat({ ...draft.request, approval }, (delta) => {
          if (owns() && delta.content) setOutput((value) => value + delta.content);
        }, controller.signal);
        if (!owns()) return;
        setOutput(result.content);
        if (result.finish_reason === "stop") {
          setHistory([...draft.request.messages, { role: "assistant", content: result.content }]); setText("");
        } else setError("The reply did not finish normally. Partial output is shown but was not added to chat history.");
      } else {
        if (!transport.runManualAnalysis) throw new Error();
        const result = await transport.runManualAnalysis({ ...draft.request, approval }, controller.signal);
        if (owns()) setOutput(JSON.stringify(result.result, null, 2));
      }
    } catch { if (owns()) setError("The model request failed or its review expired. Review again to retry."); }
    finally { if (operation.current === controller) { operation.current = null; setBusy(false); } }
  }
  async function prepare() {
    if (!model || !text.trim() || busy) return;
    const draft: Draft = mode === "chat"
      ? { mode, request: { model_id: modelId, messages: [...history, { role: "user", content: text }], max_tokens: 1100, temperature: .2 } }
      : { mode, request: { model_id: modelId, kind: mode, text } };
    if (!model.remote) { await send(draft); return; }
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError("");
    try {
      const value = draft.mode === "chat"
        ? await transport.previewInferenceChat?.(draft.request, controller.signal)
        : await transport.previewManualAnalysis?.(draft.request, controller.signal);
      if (!value) throw new Error();
      if (operation.current === controller && !controller.signal.aborted) setPreview({ value, draft });
    } catch { if (!controller.signal.aborted) setError("The model request could not be prepared."); }
    finally { if (operation.current === controller) { operation.current = null; setBusy(false); } }
  }
  return <section className="local-models" aria-label="Model inference">
    <h2>Chat and reviewed analysis</h2>
    <p>Use a running local model or the configured gateway. This panel does not save text or replies to session history. Analysis results are model opinions, not measured outcomes.</p>
    <label>Model <select aria-label="Inference model" disabled={busy} value={modelId} onChange={(event) => { reset(); setModelId(event.currentTarget.value); }}>
      <option value="">Choose a model</option>
      {models.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.name} · {item.provider} · {item.availability}</option>)}
    </select></label>{" "}
    <label>Task <select aria-label="Inference task" disabled={busy} value={mode} onChange={(event) => { reset(); setMode(event.currentTarget.value as Mode); }}>
      <option value="chat">Chat</option><option value="interpret">Explain supplied session text</option><option value="judge">Judge supplied session text</option>
    </select></label>
    {model?.remote && <p>External model managed by your gateway. Availability is configured; reachability and response quality are checked when you send. Context-token count is unknown.</p>}
    <label style={{ display: "block" }}>Text<textarea aria-label="Inference text" rows={6} maxLength={28000} disabled={busy} value={text} onChange={(event) => { setText(event.currentTarget.value); setPreview(null); }} style={{ display: "block", width: "100%" }} /></label>
    <button className="button button--primary" disabled={busy || !model?.available || !text.trim()} onClick={() => void prepare()} type="button">{model?.remote ? "Review request" : "Send to local model"}</button>{" "}
    {busy && <button className="button button--ghost" onClick={() => { operation.current?.abort(); setError("Request stopped. Partial output has not been added to history."); }} type="button">Stop</button>}
    {!busy && history.length > 0 && <button className="button button--ghost" onClick={reset} type="button">Clear chat</button>}
    {preview && <InferenceReview preview={preview.value} busy={busy} onSend={() => void send(preview.draft, preview.value.approval)} onCancel={() => setPreview(null)} />}
    {error && <p role="alert">{error}</p>}
    {output && <pre aria-label="Model response" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{output}</pre>}
  </section>;
}
