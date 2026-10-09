import type { PromptCheckPreview } from "../../shared/api/contracts";

export function PromptCheckReview({ preview, busy, onSend, onCancel }: {
  preview: PromptCheckPreview; busy: boolean; onSend: () => void; onCancel: () => void;
}) {
  return <section aria-label="Review before sending to LiteLLM" className="prompt-check__card">
    <h3>Review before sending to LiteLLM</h3>
    <p>This text will be sent to {preview.model} through your configured gateway. Redaction can miss sensitive details; review everything below. The preview expires after 10 minutes.</p>
    {preview.messages.map((message, index) => <details key={index} open={message.role === "user"}>
      <summary>{message.role === "system" ? "Model instructions" : "Redacted prompt, context and findings"}</summary>
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.content}</pre>
    </details>)}
    <button className="button button--primary" disabled={busy} type="button" onClick={onSend}>Send reviewed text to LiteLLM</button>{" "}
    <button className="button button--ghost" disabled={busy} type="button" onClick={onCancel}>Cancel</button>
  </section>;
}
