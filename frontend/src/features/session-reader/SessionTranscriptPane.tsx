import { useEffect, useState } from "react";
import type { PromptEnhancerTransport, SessionTranscript, SessionTranscriptTurn } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Icon } from "../../shared/ui/Icon";
import "./SessionTranscriptPane.css";

const ROLES = new Set(["user", "assistant", "plan", "tool_call", "tool_result", "system"]);
const SOURCES = new Set(["codex_app_server", "claude_transcript_file"]);
const MAX_TURN = 20_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Fail closed on anything outside the reader contract; never render guesses. */
export function safeTranscript(value: unknown): value is SessionTranscript {
  if (!isRecord(value) || value.contract_version !== "session-reader.v1") return false;
  if (value.persisted !== false || value.local_only !== true) return false;
  if (!SOURCES.has(value.source as string)) return false;
  if (!Array.isArray(value.turns) || value.turns.length > 2_000) return false;
  return value.turns.every((turn) =>
    isRecord(turn)
    && ROLES.has(turn.role as string)
    && typeof turn.text === "string" && turn.text.length <= MAX_TURN
    && (turn.at === null || typeof turn.at === "string")
    && (turn.tool_name === null || typeof turn.tool_name === "string")
    && typeof turn.truncated === "boolean",
  );
}

const ROLE_LABEL: Record<SessionTranscriptTurn["role"], string> = {
  user: "You",
  assistant: "Assistant",
  plan: "Plan",
  tool_call: "Tool call",
  tool_result: "Tool result",
  system: "System",
};

function timeLabel(value: string | null): string {
  if (!value) return "";
  const t = new Date(value).valueOf();
  if (Number.isNaN(t)) return "";
  return new Intl.DateTimeFormat("en", { timeStyle: "medium", timeZone: "UTC" }).format(t) + " UTC";
}

/**
 * Reads one session on demand and shows the conversation. Nothing is fetched
 * until the person asks; nothing is kept once they leave. The pane says where
 * the text came from and whether the reader truncated it.
 */
export function SessionTranscriptPane({
  sessionId,
  transport,
  autoLoad = false,
}: {
  sessionId: string;
  transport: Pick<PromptEnhancerTransport, "getSessionTranscript">;
  /** Read as soon as the pane mounts (calibration); the default waits for the button. */
  autoLoad?: boolean;
}) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "off" | "consent" | "missing" | "error">("idle");
  const [transcript, setTranscript] = useState<SessionTranscript | null>(null);
  const [expandedTools, setExpandedTools] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!autoLoad) return;
    let cancelled = false;
    setState("loading");
    setTranscript(null);
    transport.getSessionTranscript(sessionId)
      .then((value) => {
        if (cancelled) return;
        if (!safeTranscript(value)) { setState("error"); return; }
        setTranscript(value);
        setState("ready");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof TransportError && caught.status === 404) setState("off");
        else if (caught instanceof TransportError && caught.status === 403) setState("consent");
        else if (caught instanceof TransportError && caught.status === 409) setState("missing");
        else setState("error");
      });
    return () => { cancelled = true; };
  }, [autoLoad, sessionId, transport]);

  async function load() {
    setState("loading");
    setTranscript(null);
    try {
      const value = await transport.getSessionTranscript(sessionId);
      if (!safeTranscript(value)) {
        setState("error");
        return;
      }
      setTranscript(value);
      setState("ready");
    } catch (caught) {
      if (caught instanceof TransportError) {
        if (caught.status === 404) { setState(caught.message.includes("session_not_found") ? "missing" : "off"); return; }
        if (caught.status === 403) { setState("consent"); return; }
      }
      setState("error");
    }
  }

  return (
    <section aria-labelledby="session-reader-title" className="session-reader">
      <header className="session-reader__head">
        <div>
          <p className="eyebrow">Read on demand</p>
          <h2 id="session-reader-title">Read this session</h2>
        </div>
        {state !== "ready" && (
          <button className="button button--secondary" disabled={state === "loading"} onClick={() => void load()} type="button">
            {state === "loading" ? "Reading…" : "Read this session"}
          </button>
        )}
      </header>
      <p className="session-reader__note">
        Loads the conversation from your local provider only when you ask, shows it here, and keeps nothing.
      </p>

      {state === "off" && (
        <p className="session-reader__state" role="note">
          Reading is switched off. Start the local server with <code>PROMPT_ENHANCER_SESSION_READER=enabled</code> to read your own sessions here.
        </p>
      )}
      {state === "consent" && <p className="session-reader__state" role="alert">Grant this source&apos;s local-history access on the Data sources page first.</p>}
      {state === "missing" && <p className="session-reader__state" role="alert">The provider no longer has this session, or its transcript is not on this machine.</p>}
      {state === "error" && <p className="session-reader__state" role="alert">The session could not be read. Nothing was stored.</p>}

      {transcript !== null && (
        <>
          <p className="session-reader__meta">
            {transcript.turns.length} of {transcript.turn_count_total} turn{transcript.turn_count_total === 1 ? "" : "s"}
            {transcript.truncated ? " · truncated to the reader bound" : ""}
            {" · from "}
            {transcript.source === "codex_app_server" ? "the Codex app server" : "your Claude Code transcript file"}
            {transcript.provider_version ? ` · provider ${transcript.provider_version}` : ""}
          </p>
          <ol className="session-reader__turns">
            {transcript.turns.map((turn, index) => {
              const isTool = turn.role === "tool_call" || turn.role === "tool_result";
              const expanded = expandedTools.has(index);
              return (
                <li className={`session-turn session-turn--${turn.role}`} key={index}>
                  <div className="session-turn__head">
                    <strong>{ROLE_LABEL[turn.role]}{turn.tool_name ? ` · ${turn.tool_name}` : ""}</strong>
                    <small>{timeLabel(turn.at ?? null)}{turn.truncated ? " · truncated" : ""}</small>
                  </div>
                  {isTool && !expanded ? (
                    <button
                      aria-expanded={false}
                      className="session-turn__toggle"
                      onClick={() => setExpandedTools((current) => new Set(current).add(index))}
                      type="button"
                    >
                      <Icon name="arrow" /> Show {turn.role === "tool_call" ? "input" : "result"} ({turn.text.length} chars)
                    </button>
                  ) : (
                    <pre className="session-turn__text">{turn.text}</pre>
                  )}
                </li>
              );
            })}
          </ol>
          <button className="button button--ghost" onClick={() => { setTranscript(null); setState("idle"); }} type="button">
            Close and discard
          </button>
        </>
      )}
    </section>
  );
}
