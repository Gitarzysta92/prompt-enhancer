import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AgentHardeningSnapshot,
  AgentMcpConnectionList,
  AgentRecoveryAction,
  AgentOrchestrationManifest,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { AgentMcpConnectionsPanel } from "./AgentMcpConnectionsPanel";
import type {
  ExternalControllerAcceptanceEvidence,
  ExternalControllerAcceptanceRun,
} from "./externalControllerAcceptance";
import "./AgentControllerPanel.css";

type ControllerTransport = Partial<Pick<
  PromptEnhancerTransport,
  | "getAgentOrchestration"
  | "getAgentHardening"
  | "listAgentMcpConnections"
  | "createAgentMcpConnection"
  | "rotateAgentMcpConnection"
  | "revokeAgentMcpConnection"
  | "releaseAgentControllerOwnership"
  | "getAgentMcpClientSetup"
  | "listAgentProjects"
>>;

type Props = {
  transport: ControllerTransport;
  userPresenceAvailable: boolean;
  selectedProjectId?: string | null;
  selectedSessionId?: string | null;
  acceptanceRun?: ExternalControllerAcceptanceRun | null;
  onAcceptanceEvidence?: (evidence: ExternalControllerAcceptanceEvidence) => void;
  onAcceptanceObservation?: (catalog: AgentMcpConnectionList) => void;
  onAcceptanceRunChange?: (run: ExternalControllerAcceptanceRun | null) => void;
};

type State = "checking" | "ready" | "unavailable";
type HealthState = "idle" | "checking" | "ready" | "unavailable";

const RECOVERY_LABELS: Record<AgentRecoveryAction, string> = {
  inspect_local_catalog: "Inspect the local catalog before trusting recovery.",
  resume_interrupted_read_only: "Interrupted chats can be resumed read-only.",
  revalidate_recovered_authority: "Review permissions before recovered chats may change files.",
  restart_after_cleanup_uncertain: "Restart before running more commands; cleanup is uncertain.",
  retry_after_history_write_failure: "Retry after the local history write failure is resolved.",
  verify_live_state: "Retry the live Agent state check.",
};

type CatalogReason = NonNullable<AgentHardeningSnapshot["catalog"]["reason_code"]>;

const CATALOG_REASON_LABELS: Record<CatalogReason, string> = {
  catalog_path_invalid: "The configured local catalog path is invalid.",
  catalog_path_unsafe: "The configured local catalog path is outside the allowed boundary.",
  catalog_schema_newer: "The local catalog was created by a newer application version.",
  catalog_migration_invalid: "The local catalog migration history is inconsistent. No data was changed.",
  catalog_storage_unavailable: "The local catalog storage could not be inspected.",
  catalog_quick_check_failed: "The local catalog integrity check did not pass.",
  catalog_foreign_key_violation: "The local catalog has relationship inconsistencies.",
  catalog_projection_mismatch: "Stored chat summaries do not match their retained histories.",
  catalog_diagnostic_unavailable: "The local catalog check could not be completed safely.",
};

type CommandRowProps = {
  command: string;
  label: string;
};

function CommandRow({ command, label }: CommandRowProps) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    if (!navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [command]);

  return (
    <div className="agent-controller__command">
      <span>{label}</span>
      <code>{command}</code>
      <button
        aria-label={`Copy ${label.toLocaleLowerCase()} command`}
        className="button button--ghost"
        onClick={() => void copy()}
        type="button"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function AgentControllerPanel({
  transport,
  userPresenceAvailable,
  selectedProjectId = null,
  selectedSessionId = null,
  acceptanceRun = null,
  onAcceptanceEvidence,
  onAcceptanceObservation,
  onAcceptanceRunChange,
}: Props) {
  const [manifest, setManifest] = useState<AgentOrchestrationManifest | null>(null);
  const [state, setState] = useState<State>("checking");
  const [attempt, setAttempt] = useState(0);
  const [health, setHealth] = useState<AgentHardeningSnapshot | null>(null);
  const [healthState, setHealthState] = useState<HealthState>("idle");
  const healthRequest = useRef<AbortController | null>(null);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const getManifest = transport.getAgentOrchestration;
    if (getManifest === undefined) {
      setManifest(null);
      setState("unavailable");
      return;
    }
    const controller = new AbortController();
    setManifest(null);
    setState("checking");
    void getManifest(controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setManifest(value);
      setState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setManifest(null);
      setState("unavailable");
    });
    return () => controller.abort();
  }, [attempt, transport.getAgentOrchestration]);

  useEffect(() => () => healthRequest.current?.abort(), []);

  const checkHealth = useCallback(() => {
    const getHealth = transport.getAgentHardening;
    if (getHealth === undefined) {
      setHealth(null);
      setHealthState("unavailable");
      return;
    }
    healthRequest.current?.abort();
    const controller = new AbortController();
    healthRequest.current = controller;
    setHealth(null);
    setHealthState("checking");
    void getHealth(controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setHealth(value);
      setHealthState("ready");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setHealth(null);
      setHealthState("unavailable");
    });
  }, [transport.getAgentHardening]);

  const counts = useMemo(() => {
    const endpoints = manifest?.endpoints ?? [];
    return {
      agent: endpoints.filter((endpoint) => endpoint.path_template.startsWith("/v1/agent/"))
        .length,
      runtime: endpoints.filter((endpoint) => endpoint.path_template.startsWith("/v1/local-models/"))
        .length,
      reviewed: endpoints.filter((endpoint) => endpoint.access === "native_user_presence_only")
        .length,
    };
  }, [manifest]);

  const label = state === "ready" ? "Ready" : state === "checking" ? "Checking" : "Unavailable";
  const healthLabel = health?.recovery_state === "clean"
    ? "Healthy"
    : health?.recovery_state === "attention_required"
      ? "Review needed"
      : "Unknown";
  const healthAnnouncement = healthState === "idle"
    ? "Project and chat health has not been checked."
    : healthState === "checking"
      ? "Checking project and chat health."
      : healthState === "unavailable"
        ? "Project and chat health could not be verified. Agent chat remains available."
        : `Project and chat health check complete: ${healthLabel}. ${health?.recovery_actions.length ?? 0} safe ${health?.recovery_actions.length === 1 ? "action" : "actions"} reported.`;

  return (
    <section aria-labelledby="agent-controller-title" className="agent-controller" data-state={state}>
      <header className="agent-controller__head">
        <span>
          <small>External orchestration</small>
          <strong id="agent-controller-title">Controller API</strong>
        </span>
        <span aria-live="polite" className="agent-controller__state">{label}</span>
      </header>

      {state === "ready" && manifest ? (
        <>
          <p className="agent-controller__summary">
            Codex, Claude Code, or another local controller can use the same projects,
            chats, events, files, diffs, and artifacts as this Agent window.
          </p>
          <dl className="agent-controller__facts">
            <div><dt>Agent routes</dt><dd>{counts.agent}</dd></div>
            <div><dt>Runtime routes</dt><dd>{counts.runtime}</dd></div>
            <div><dt>Native review gates</dt><dd>{counts.reviewed}</dd></div>
            <div><dt>Contract</dt><dd>{manifest.contract_version}</dd></div>
          </dl>
          <code className="agent-controller__endpoint">GET /v1/agent/orchestration</code>
          <p className="agent-controller__boundary">
            Controllers may inspect and prepare changes. Applying workspace changes,
            recovered authority, approvals, and manual captures still requires you in
            the native app.
          </p>
          <div className="agent-controller__details">
              <AgentMcpConnectionsPanel
                acceptanceRun={acceptanceRun}
                onAcceptanceEvidence={onAcceptanceEvidence}
                onAcceptanceObservation={onAcceptanceObservation}
                onAcceptanceRunChange={onAcceptanceRunChange}
                selectedProjectId={selectedProjectId}
                selectedSessionId={selectedSessionId}
                transport={transport}
                userPresenceAvailable={userPresenceAvailable}
              />
              <details className="agent-controller__advanced">
                <summary>Advanced: templates, stdio fallback, and scripts</summary>
                <div>
                  <p>
                    The token-free HTTP template uses an environment variable and starts no
                    bridge process. Use the stdio fallback only for a client that cannot speak
                    Streamable HTTP; it owns one headless bridge subprocess.
                  </p>
                  <CommandRow
                    command="prompt-enhancer agent-mcp-config"
                    label="Token-free direct HTTP template"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-mcp-config --transport stdio"
                    label="Headless stdio fallback"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-mcp-config --transport stdio --with-model-lifecycle"
                    label="Stdio fallback with model control"
                  />
                  <p>
                    For scripts that do not speak MCP, the single-request controller
                    bridge exposes the same validated contract.
                  </p>
                  <CommandRow
                    command="prompt-enhancer agent-controller-config"
                    label="Controller CLI contract"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller discover"
                    label="Verify connection"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller invoke --acknowledge-sensitive-context-egress"
                    label="Invoke one declared operation"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller open --acknowledge-sensitive-context-egress"
                    label="Open project and chat"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller runtime --acknowledge-sensitive-context-egress --acknowledge-model-lifecycle"
                    label="Prepare or stop model"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller turn --acknowledge-sensitive-context-egress"
                    label="Send and observe one turn"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller wait --acknowledge-sensitive-context-egress"
                    label="Continue after native review"
                  />
                  <CommandRow
                    command="prompt-enhancer agent-controller close --acknowledge-sensitive-context-egress"
                    label="Close live chat and retain history"
                  />
                  <p>
                    Invoke, open, close, runtime, turn, and wait consume one strict JSON envelope.
                    Creation and message submission are never retried after ambiguity;
                    runtime and live-close mutate at most once, close retains the durable chat,
                    and wait resumes from the returned cursor.
                    Sensitive output requires task authorization and a completed redaction
                    preview. Native review remains unavailable to either bridge.
                  </p>
                  <p>
                    Direct HTTP is loopback-only. OpenAPI: <code>{manifest.openapi_path}</code>.
                    Private connection values appear only in the one-time copy controls above.
                  </p>
                </div>
              </details>

              <section
                aria-busy={healthState === "checking"}
                aria-labelledby="agent-health-title"
                className="agent-controller__health"
              >
                <header>
                  <span>
                    <small>On-demand · content-free</small>
                    <strong id="agent-health-title">Projects &amp; chats health</strong>
                  </span>
                  {healthState === "ready" && health && (
                    <span aria-hidden="true" data-state={health.recovery_state}>
                      {healthLabel}
                    </span>
                  )}
                </header>
                <p
                  aria-atomic="true"
                  aria-live="polite"
                  className="sr-only"
                  role="status"
                >
                  {healthAnnouncement}
                </p>
                <p>
                  Checks schema, restart recovery, retention projections, and live
                  cleanup state. It never reads or returns names, paths, prompts,
                  messages, IDs, timestamps, artifacts, or attachment bytes.
                </p>
                <button
                  className="button button--ghost agent-controller__health-check"
                  disabled={healthState === "checking" || transport.getAgentHardening === undefined}
                  onClick={checkHealth}
                  type="button"
                >
                  {healthState === "checking" ? "Checking…" : healthState === "idle" ? "Run health check" : "Check again"}
                </button>
                {transport.getAgentHardening === undefined && (
                  <p role="status">This server does not expose the content-free health contract.</p>
                )}
                {healthState === "unavailable" && (
                  <p role="status">The health check could not be verified. Chat remains available.</p>
                )}
                {healthState === "ready" && health && (
                  <div className="agent-controller__health-result">
                    {health.catalog.counts || health.live.counts ? (
                      <dl className="agent-controller__health-facts">
                        {health.catalog.counts && (
                          <>
                            <div><dt>Projects</dt><dd>{health.catalog.counts.projects}</dd></div>
                            <div><dt>Chats</dt><dd>{health.catalog.counts.sessions}</dd></div>
                            <div><dt>Saved histories</dt><dd>{health.catalog.counts.retained_sessions}</dd></div>
                            <div><dt>Interrupted</dt><dd>{health.catalog.counts.interrupted_retained_sessions}</dd></div>
                          </>
                        )}
                        {health.live.counts && (
                          <>
                            <div><dt>Live chats</dt><dd>{health.live.counts.sessions}</dd></div>
                            <div><dt>Running turns</dt><dd>{health.live.counts.running_turns}</dd></div>
                          </>
                        )}
                      </dl>
                    ) : (
                      <p>Catalog or live-state observations are unavailable.</p>
                    )}
                    <p>
                      Catalog: {health.catalog.state} · schema {health.catalog.schema_version ?? "unknown"}
                      {health.catalog.projection_violations !== null
                        ? ` · ${health.catalog.projection_violations} projection issues`
                        : ""}
                    </p>
                    {health.catalog.reason_code && (
                      <p>{CATALOG_REASON_LABELS[health.catalog.reason_code]}</p>
                    )}
                    {health.live.state === "unavailable" && (
                      <p>Live cleanup state could not be verified.</p>
                    )}
                    {health.recovery_actions.length > 0 && (
                      <section
                        aria-labelledby="agent-health-actions-title"
                        className="agent-controller__health-actions"
                      >
                        <strong id="agent-health-actions-title">Next safe actions</strong>
                        <ul>
                          {health.recovery_actions.map((action) => (
                            <li key={action}>{RECOVERY_LABELS[action]}</li>
                          ))}
                        </ul>
                      </section>
                    )}
                  </div>
                )}
              </section>
          </div>
        </>
      ) : state === "checking" ? (
        <p className="agent-controller__summary">Verifying the local controller contract…</p>
      ) : (
        <div className="agent-controller__failure" role="status">
          <p>The controller contract could not be verified. Agent chat remains usable.</p>
          {transport.getAgentOrchestration !== undefined && (
            <button className="button button--ghost" onClick={refresh} type="button">Retry</button>
          )}
        </div>
      )}
    </section>
  );
}
