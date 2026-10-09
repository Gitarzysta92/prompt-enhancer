import { useEffect, useRef, useState } from "react";
import type { AgentSessionView, InferenceModel, PendingInferenceReview, PromptEnhancerTransport } from "../../shared/api/contracts";
import { InferenceReview } from "./InferenceReview";

export function AgentInferenceControl({ current, models, transport, onSessionUpdated, disabled }: {
  current: AgentSessionView; models: InferenceModel[]; transport: Partial<PromptEnhancerTransport>;
  onSessionUpdated: (value: AgentSessionView) => void; disabled: boolean;
}) {
  const [reviews, setReviews] = useState<PendingInferenceReview[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const operation = useRef<AbortController | null>(null);
  const remote = models.find((item) => item.id === (current.model_alias ?? current.settings.model_alias));
  useEffect(() => () => { operation.current?.abort(); }, [current.session_id, transport]);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    setReviews([]);
    async function poll() {
      try {
        const value = await transport.getAgentInferenceReviews?.(current.session_id, controller.signal);
        if (!controller.signal.aborted) setReviews(value ?? []);
      } catch { if (!controller.signal.aborted) setError("Could not read pending model reviews. Stop the turn if the connection does not recover."); }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 600); }
    }
    if (current.running && remote) void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [current.session_id, current.running, remote?.id, transport]);
  async function bind(model: InferenceModel) {
    if (!transport.switchAgentSessionModel || !transport.getAgentCatalogSession) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try {
      const catalog = await transport.getAgentCatalogSession(current.session_id, controller.signal);
      const value = await transport.switchAgentSessionModel(current.session_id, { model_alias: model.id, expected_revision: catalog.revision }, controller.signal);
      if (!controller.signal.aborted) onSessionUpdated(value);
    } catch { if (!controller.signal.aborted) setError("The model could not be selected. Stop any active turn and retry."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function decide(review: PendingInferenceReview, accepted: boolean) {
    const controller = new AbortController(); operation.current = controller; setBusy(true); setError("");
    try {
      await transport.decideAgentInferenceReview?.(current.session_id, review.id, accepted, controller.signal);
      if (!controller.signal.aborted) setReviews((items) => items.filter((item) => item.id !== review.id));
    } catch { if (!controller.signal.aborted) setError("This model review expired or could not be submitted."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  if (!models.length) return null;
  return <section aria-label="External Agent model">
    <p>{remote ? `Using ${remote.name} via ${remote.provider}. Each outgoing model request requires review, including new tool results.` : "An external model can power this chat without starting a local model."}</p>
    {!current.running && models.map((model) => <button key={model.id} className="button button--ghost" disabled={disabled || busy || !model.available || remote?.id === model.id} onClick={() => void bind(model)} type="button">Use {model.name}</button>)}
    {reviews.map((review) => <InferenceReview key={review.id} preview={review.preview} busy={busy || disabled} onSend={() => void decide(review, true)} onCancel={() => void decide(review, false)} />)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
