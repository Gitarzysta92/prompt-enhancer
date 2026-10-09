import type { InferencePreview } from "../../shared/api/contracts";

export function InferenceReview({ preview, busy, onSend, onCancel }: {
  preview: InferencePreview; busy: boolean; onSend: () => void; onCancel: () => void;
}) {
  return <section aria-label="Review model request" className="prompt-check__card">
    <h3>Review before sending to {preview.model.name}</h3>
    <p>The request below goes to your configured {preview.model.provider} provider. Redaction can miss sensitive information. Review it before sending.</p>
    <details open><summary>Redacted model request</summary>
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "24rem", overflow: "auto" }}>{JSON.stringify(preview.request, null, 2)}</pre>
    </details>
    <button className="button button--primary" disabled={busy} onClick={onSend} type="button">Send reviewed request</button>{" "}
    <button className="button button--ghost" disabled={busy} onClick={onCancel} type="button">Cancel review</button>
  </section>;
}
