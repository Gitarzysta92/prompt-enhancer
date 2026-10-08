import { useEffect, useState } from "react";
import type { CalibrationReview, PromptEnhancerTransport } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";

const FINGERPRINT = /^(?!0{64}$)[a-f0-9]{64}$/;
type ReviewTransport = Pick<PromptEnhancerTransport, "reviewCalibrationCase">;

export function safeCalibrationReview(value: unknown, sessionId: string, provider?: string): value is CalibrationReview {
  if (typeof value !== "object" || value === null) return false;
  const data = value as CalibrationReview;
  return data.contract_version === "calibration-case.v1" && data.case_version === "calibration-case.v1"
    && data.window_schema_version === "model-judge-window.v2"
    && data.session_id === sessionId && ["codex", "claude_code", "synthetic"].includes(data.provider)
    && (provider === undefined || data.provider === provider)
    && typeof data.case_fingerprint === "string" && FINGERPRINT.test(data.case_fingerprint)
    && typeof data.window_fingerprint === "string" && FINGERPRINT.test(data.window_fingerprint)
    && typeof data.review_id === "string" && /^[a-f0-9]{32}$/.test(data.review_id)
    && typeof data.expires_at === "string" && Number.isFinite(Date.parse(data.expires_at))
    && data.persisted === false && data.local_only === true && typeof data.earlier_records_omitted === "boolean"
    && Array.isArray(data.records) && data.records.length > 0 && data.records.length <= 120
    && data.records[0]?.role === "user"
    && data.records.every((record, index) => typeof record === "object" && record !== null
      && Number.isInteger(record.sequence) && record.sequence >= 0
      && (index === 0 || record.sequence > data.records[index - 1].sequence)
      && ["user", "agent", "plan"].includes(record.role)
      && typeof record.content === "string" && record.content.trim().length > 0 && record.content.length <= 15000)
    && data.records.reduce((total, record) => total + record.content.length, 0) <= 15000;
}

function reviewFailure(error: unknown): string {
  if (error instanceof TransportError && error.reasonCode === "calibration_review_disabled") {
    return "Case review is off. Start the local server with PROMPT_ENHANCER_SESSION_READER=enabled before reviewing and saving ratings.";
  }
  if (error instanceof TransportError && error.reasonCode === "calibration_review_consent_required") {
    return "Redacted-content consent is required for this provider. Review its permission on the Data sources page.";
  }
  return "The reviewed case could not be verified. No rating will be saved against unknown evidence.";
}

export function CalibrationCasePane({ sessionId, provider, transport, disabled, onReviewChange }: {
  sessionId: string;
  provider: CalibrationReview["provider"];
  transport: ReviewTransport;
  disabled: boolean;
  onReviewChange: (value: CalibrationReview | null) => void;
}) {
  const [windowCharacters, setWindowCharacters] = useState<6000 | 15000>(15000);
  const [retry, setRetry] = useState(0);
  const [loaded, setLoaded] = useState<{ transport: ReviewTransport; value: CalibrationReview; windowCharacters: number } | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);
  const review = loaded?.transport === transport && loaded.value.session_id === sessionId && loaded.windowCharacters === windowCharacters ? loaded.value : null;

  useEffect(() => {
    const controller = new AbortController();
    let expiry: ReturnType<typeof setTimeout> | undefined;
    setLoaded(null);
    setLoading(true);
    setExpired(false);
    setMessage("");
    onReviewChange(null);
    void (async () => {
      try {
        const value = await transport.reviewCalibrationCase(sessionId, windowCharacters, controller.signal);
        if (controller.signal.aborted) return;
        if (!safeCalibrationReview(value, sessionId, provider)) throw new Error("invalid calibration case");
        const lifetime = Date.parse(value.expires_at) - Date.now();
        if (lifetime <= 0) throw new Error("expired calibration case");
        setLoaded({ transport, value, windowCharacters });
        onReviewChange(value);
        expiry = setTimeout(() => {
          if (!controller.signal.aborted) {
            setExpired(true);
            onReviewChange(null);
          }
        }, Math.min(lifetime, 15 * 60 * 1000));
      } catch (error) {
        if (!controller.signal.aborted) setMessage(reviewFailure(error));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => { controller.abort(); clearTimeout(expiry); };
  }, [sessionId, provider, transport, windowCharacters, retry, onReviewChange]);

  return <section className="calibration__case" aria-label="Reviewed calibration case" aria-busy={loading}>
    <div className="calibration__case-head">
      <h3>Evidence to rate</h3>
      <label>Evidence window
        <select value={windowCharacters} disabled={disabled} onChange={(event) => setWindowCharacters(Number(event.currentTarget.value) as 6000 | 15000)}>
          <option value={15000}>Standard · 15,000 characters</option>
          <option value={6000}>Short · 6,000 characters</option>
        </select>
      </label>
      <button className="button button--ghost" type="button" disabled={disabled || loading} onClick={() => setRetry((value) => value + 1)}>Refresh case</button>
    </div>
    <p className="calibration__note">Rate only the redacted evidence below, not the full session. The task request and recent tail match the judge’s evidence format. Use Short if the judge had to retry with a smaller window.</p>
    {loading && <p role="status">Preparing the reviewed case…</p>}
    {message && <p role="alert">{message}</p>}
    {review && <>
      <p className="calibration__note">Case {review.case_fingerprint.slice(0, 12)} · {review.records.length} record{review.records.length === 1 ? "" : "s"} · {review.earlier_records_omitted ? "Some records or characters are omitted." : "No additional truncation in this rendered window."}</p>
      <div className="calibration__case-records" tabIndex={0} aria-label="Redacted case evidence">
        {review.records.map((record) => <article key={record.sequence}>
          <h4>{record.role === "user" ? "User" : record.role === "plan" ? "Plan" : "Agent"} · record {record.sequence + 1}</h4>
          <pre>{record.content}</pre>
        </article>)}
      </div>
    </>}
    {expired && <p role="status">This review receipt expired. Your draft is still here; refresh and review the case again before saving.</p>}
  </section>;
}
