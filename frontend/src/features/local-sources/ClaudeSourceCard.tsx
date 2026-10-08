import { useCallback, useEffect, useState } from "react";
import type {
  ClaudeCodeLocalSourceStatus,
  IngestionReport,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Icon } from "../../shared/ui/Icon";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";

const INDEX_LIMITS = [50, 100, 250, 500, 1000] as const;

type ClaudeTransport = Pick<PromptEnhancerTransport,
  | "getClaudeLocalSourceStatus"
  | "grantClaudeLocalHistoryConsent"
  | "revokeClaudeLocalHistoryConsent"
  | "indexClaudeLocalSessions">;

type Operation = "grant" | "revoke" | "index" | null;

const CLAUDE_STATUS_KEYS = [
  "capture_channel",
  "captured_events",
  "captured_requests",
  "captured_sessions",
  "consent_active",
  "indexed_projects",
  "indexed_sessions",
  "persists_content",
  "reads_transcripts",
  "telemetry_channel",
  "telemetry_sessions",
  "verification_capability",
] as const;
const VERIFICATION_CAPABILITY_KEYS = [
  "candidate_schema_version",
  "classifier_version",
  "live_classification_enabled",
  "normalizer_version",
  "reason_code",
  "state",
  "supported_kinds",
] as const;
const VERIFICATION_STATES = new Set([
  "supported",
  "validation_only",
  "unsupported",
  "incompatible",
  "not_authorized",
]);
const VERIFICATION_KINDS = new Set([
  "test",
  "build",
  "lint",
  "type_check",
  "security",
  "artifact_validation",
]);
const SAFE_REASON = /^[a-z][a-z0-9_.-]{0,63}$/;
const SAFE_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length
    && expected.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function isOptionalSafeVersion(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && SAFE_VERSION.test(value));
}

function safeVerificationCapability(value: unknown): boolean {
  if (!isRecord(value) || !hasExactKeys(value, VERIFICATION_CAPABILITY_KEYS)) return false;
  if (
    typeof value.state !== "string"
    || !VERIFICATION_STATES.has(value.state)
    || typeof value.live_classification_enabled !== "boolean"
    || value.live_classification_enabled !== (value.state === "supported")
    || !isOptionalSafeVersion(value.classifier_version)
    || !isOptionalSafeVersion(value.normalizer_version)
    || !isOptionalSafeVersion(value.candidate_schema_version)
    || typeof value.reason_code !== "string"
    || !SAFE_REASON.test(value.reason_code)
    || !Array.isArray(value.supported_kinds)
    || !value.supported_kinds.every(
      (kind) => typeof kind === "string" && VERIFICATION_KINDS.has(kind),
    )
  ) return false;
  if (value.state === "supported" || value.state === "validation_only") {
    return value.classifier_version !== null
      && value.normalizer_version !== null
      && value.candidate_schema_version !== null
      && value.supported_kinds.length > 0;
  }
  return true;
}

/** Fail closed on any shape that could carry more than the content-free counts. */
export function safeClaudeStatus(value: unknown): value is ClaudeCodeLocalSourceStatus {
  return (
    isRecord(value) &&
    hasExactKeys(value, CLAUDE_STATUS_KEYS) &&
    typeof value.consent_active === "boolean" &&
    nonNegativeInt(value.captured_sessions) &&
    nonNegativeInt(value.captured_events) &&
    nonNegativeInt(value.captured_requests) &&
    nonNegativeInt(value.telemetry_sessions) &&
    nonNegativeInt(value.indexed_sessions) &&
    nonNegativeInt(value.indexed_projects) &&
    value.capture_channel === "claude_code_hooks" &&
    value.telemetry_channel === "claude_code_otlp" &&
    value.reads_transcripts === false &&
    value.persists_content === false &&
    safeVerificationCapability(value.verification_capability)
  );
}

function reportSummary(report: IngestionReport): string {
  const bounded = report.truncated ? " (bounded result)" : "";
  return `Indexed ${report.sessions_seen} captured Claude Code session${report.sessions_seen === 1 ? "" : "s"} and ${report.events_seen} event${report.events_seen === 1 ? "" : "s"}${bounded}.`;
}

/**
 * Consent, capture status, and indexing for the hook-captured Claude Code
 * source. The card never claims capture is complete: it reports what the
 * receiver recorded and what indexing admitted, as two separate counts.
 */
export function ClaudeSourceCard({ transport }: { transport: ClaudeTransport }) {
  const [status, setStatus] = useState<ClaudeCodeLocalSourceStatus | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [operation, setOperation] = useState<Operation>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [indexMax, setIndexMax] = useState<number>(500);
  const [showSetup, setShowSetup] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await transport.getClaudeLocalSourceStatus(signal);
      if (signal?.aborted) return;
      if (!safeClaudeStatus(value)) {
        setLoadState("error");
        setError("The Claude Code source status had an unexpected shape and was not shown.");
        return;
      }
      setStatus(value);
      setLoadState("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      if (caught instanceof TransportError && caught.status === 404) {
        setLoadState("unavailable");
        return;
      }
      setLoadState("error");
      setError("The Claude Code source status could not be loaded.");
    }
  }, [transport]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function run(kind: Exclude<Operation, null>) {
    setOperation(kind);
    setNotice("");
    setError("");
    try {
      if (kind === "grant") {
        const next = await transport.grantClaudeLocalHistoryConsent();
        if (!safeClaudeStatus(next) || !next.consent_active) {
          await load();
          setError("The consent change could not be confirmed from the local service.");
          return;
        }
        setStatus(next);
        setNotice("Hook capture is now permitted. Install the hooks fragment in Claude Code to start recording.");
      } else if (kind === "revoke") {
        const next = await transport.revokeClaudeLocalHistoryConsent();
        if (!safeClaudeStatus(next) || next.consent_active) {
          await load();
          setError("The consent change could not be confirmed from the local service.");
          return;
        }
        setStatus(next);
        setNotice("Hook capture is now off. The receiver records nothing further; already-captured events remain until you delete them.");
      } else {
        const report = await transport.indexClaudeLocalSessions(indexMax);
        setNotice(reportSummary(report));
        await load();
      }
    } catch (caught) {
      if (caught instanceof TransportError && caught.status === 403) {
        setError("Grant hook-capture consent before indexing.");
      } else {
        setError(kind === "index"
          ? "Captured Claude Code sessions could not be indexed."
          : "The consent change could not be saved.");
      }
    } finally {
      setOperation(null);
    }
  }

  if (loadState === "unavailable") {
    return null;
  }

  return (
    <article aria-labelledby="claude-source-title" className="source-card source-card--claude">
      <div className="source-card__heading">
        <div className="source-card__identity">
          <span className="source-card__mark source-card__mark--claude">CC</span>
          <div>
            <p className="eyebrow">Hook capture</p>
            <h2 id="claude-source-title">Claude Code sessions</h2>
          </div>
        </div>
        {status !== null && (
          <span className={`status-pill ${status.consent_active ? "status-pill--positive" : "status-pill--warning"}`}>
            {status.consent_active ? "Capture permitted" : "Capture not permitted"}
          </span>
        )}
      </div>

      <p className="source-card__description">
        Claude Code invokes a local receiver for each lifecycle event. The receiver
        keeps only pseudonymous session and project identity, event kind, tool
        category, and timing — never a prompt, tool output, transcript path, or
        working directory — and records nothing unless capture is permitted here.
        Sessions that started before the hook was installed are not read.
      </p>

      <div aria-live="polite" className="notice-region">
        {notice && <div className="success-notice local-source-notice"><Icon name="check" /><span>{notice}</span></div>}
        {error && <p className="local-source-error" role="alert">{error}</p>}
      </div>

      {loadState === "loading" && <p className="source-card__description">Loading Claude Code capture status…</p>}

      {status !== null && (
        <>
          <dl className="source-card__facts">
            <div><dt>Captured sessions</dt><dd>{status.captured_sessions}</dd></div>
            <div><dt>Captured events</dt><dd>{status.captured_events}</dd></div>
            <div><dt>Indexed sessions</dt><dd>{status.indexed_sessions}</dd></div>
            <div><dt>Safe projects</dt><dd>{status.indexed_projects}</dd></div>
            <div><dt>Captured requests</dt><dd>{status.captured_requests}</dd></div>
            <div><dt>Transcripts read</dt><dd>{status.reads_transcripts ? "On this machine only" : "Never"}</dd></div>
            <div><dt>Content stored</dt><dd>{status.persists_content ? "Yes" : "Never"}</dd></div>
          </dl>
          <p className="source-card__footnote">
            <ProviderBadge compact provider="claude_code" /> Captured counts describe what the
            receiver recorded; indexed counts describe what has been admitted to the shared
            catalog. Neither claims that every provider event was captured.
          </p>

          <div className="source-card__actions">
            {status.consent_active ? (
              <button
                className="button button--danger-ghost"
                disabled={operation !== null}
                onClick={() => void run("revoke")}
                type="button"
              >
                {operation === "revoke" ? "Stopping…" : "Stop hook capture"}
              </button>
            ) : (
              <button
                className="button button--primary"
                disabled={operation !== null}
                onClick={() => void run("grant")}
                type="button"
              >
                {operation === "grant" ? "Permitting…" : "Permit hook capture"}
              </button>
            )}
            <label className="field field--inline">
              <span>Maximum sessions</span>
              <select
                aria-label="Maximum Claude Code sessions to index"
                disabled={operation !== null}
                onChange={(event) => setIndexMax(Number(event.target.value))}
                value={indexMax}
              >
                {INDEX_LIMITS.map((limit) => <option key={limit} value={limit}>{limit}</option>)}
              </select>
            </label>
            <button
              aria-describedby={
                !status.consent_active || operation !== null || status.captured_sessions === 0
                  ? "claude-source-index-disabled-reason"
                  : undefined
              }
              className="button button--secondary"
              disabled={!status.consent_active || operation !== null || status.captured_sessions === 0}
              onClick={() => void run("index")}
              type="button"
            >
              {operation === "index" ? "Indexing…" : "Index captured sessions"}
            </button>
            {(!status.consent_active || operation !== null || status.captured_sessions === 0) && (
              <span className="sr-only" id="claude-source-index-disabled-reason">
                {!status.consent_active
                  ? "Permit hook capture before indexing captured sessions."
                  : operation !== null
                    ? "Wait for the current Claude Code source operation to finish."
                    : "No captured sessions are available to index yet."}
              </span>
            )}
          </div>
          {status.consent_active && status.captured_sessions === 0 && (
            <small className="source-card__hint">
              Nothing has been captured yet. Install the hooks fragment below and start a Claude Code session.
            </small>
          )}

          <button
            aria-expanded={showSetup}
            className="button button--ghost"
            onClick={() => setShowSetup((current) => !current)}
            type="button"
          >
            {showSetup ? "Hide setup" : "How to install the hook"}
          </button>
          {showSetup && (
            <div className="source-card__setup" role="region" aria-label="Claude Code hook setup">
              <p>
                From the repository, print the hooks fragment and paste it into your Claude Code
                <code>settings.json</code> yourself. Prompt Enhancer never writes to that file.
              </p>
              <pre><code>python -m prompt_enhancer claude-hooks-config</code></pre>
              <p>
                Each configured event then runs <code>python -m prompt_enhancer claude-hook</code>,
                which is silent, always exits 0, and writes nothing while capture is off.
              </p>
              <p>
                For token, cost, and model per request, also point Claude Code&apos;s telemetry at
                this app&apos;s loopback receiver. Print the environment variables and set them where
                you launch Claude Code; the local server must be running to receive them.
              </p>
              <pre><code>python -m prompt_enhancer claude-otel-config</code></pre>
              <p>
                Only <code>api_request</code> usage and documented session counters are recorded;
                account, organization, user, prompt, tool-parameter, and error fields are never read.
                A missing export batch is a gap, never a zero.
              </p>
            </div>
          )}
        </>
      )}
    </article>
  );
}
