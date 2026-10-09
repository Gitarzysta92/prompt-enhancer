import { useEffect, useRef, useState } from "react";
import type { InferenceModel, InferencePreview, PromptEnhancerTransport } from "../../shared/api/contracts";
import { InferenceReview } from "./InferenceReview";

export function SessionInferenceControl({ sessionId, transport, onJudged }: {
  sessionId: string; transport: Partial<PromptEnhancerTransport>; onJudged: () => void;
}) {
  const [models, setModels] = useState<InferenceModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [pending, setPending] = useState<{ kind: "judge" | "interpret"; preview: InferencePreview; modelId: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [output, setOutput] = useState("");
  const operation = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setModels([]); setPending(null); setOutput(""); setError(""); setBusy(false);
    void transport.getInferenceModels?.(controller.signal).then((catalog) => {
      if (controller.signal.aborted) return;
      const remote = catalog.models.filter((item) => item.remote && item.available);
      setModels(remote); setModelId(remote[0]?.id ?? "");
    }).catch(() => {});
    return () => { controller.abort(); operation.current?.abort(); operation.current = null; };
  }, [sessionId, transport]);
  async function preview(kind: "judge" | "interpret") {
    if (!modelId || busy || !transport.previewSessionInference) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try {
      const value = await transport.previewSessionInference(sessionId, kind, modelId, controller.signal);
      if (!controller.signal.aborted) setPending({ kind, preview: value, modelId });
    } catch { if (!controller.signal.aborted) setError("A reviewed session window is unavailable. Check local consent and source availability, or supply text on the Models page."); }
    finally { if (operation.current === controller) { operation.current = null; setBusy(false); } }
  }
  async function send() {
    if (!pending || !transport.runSessionInference) return;
    const captured = pending; const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try {
      const value = await transport.runSessionInference(sessionId, captured.kind, captured.modelId, captured.preview.approval, controller.signal);
      if (controller.signal.aborted) return;
      setPending(null);
      if ("summary" in value || "strengths" in value) setOutput(JSON.stringify(value, null, 2));
      else { setOutput("Reviewed model judgment completed."); onJudged(); }
    } catch { if (!controller.signal.aborted) { setPending(null); setError("The request failed or the session changed. Create a fresh preview before retrying."); } }
    finally { if (operation.current === controller) { operation.current = null; setBusy(false); } }
  }
  if (!models.length) return null;
  return <section aria-label="Reviewed external session analysis">
    <h4>Analyze with a gateway model</h4>
    <select aria-label="Session analysis model" disabled={busy} value={modelId} onChange={(event) => { setModelId(event.currentTarget.value); setPending(null); setOutput(""); }}>
      {models.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.provider}</option>)}
    </select>{" "}
    <button type="button" className="button button--ghost" disabled={busy} onClick={() => void preview("interpret")}>Review external explanation</button>{" "}
    <button type="button" className="button button--ghost" disabled={busy} onClick={() => void preview("judge")}>Review external judgment</button>
    {pending && <InferenceReview preview={pending.preview} busy={busy} onSend={() => void send()} onCancel={() => setPending(null)} />}
    {error && <p role="alert">{error}</p>}
    {output && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{output}</pre>}
  </section>;
}
