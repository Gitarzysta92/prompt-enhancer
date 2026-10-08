import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import type {
  AutomationGrantCreateRequest,
  AutomationGrantRecord,
  AutomationPollResult,
  CodexLocalSourceStatus,
  CodexSession,
  LocalProvider,
  MetricReadiness,
  PromptEnhancerTransport,
  SessionMetricReadinessReport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { isPseudonym, routePath } from "../../shared/platform/platform";
import type {
  RuntimeDataMode,
  RuntimeServiceState,
} from "../../shared/platform/runtimeMode";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";

const SESSION_PAGE_LIMIT = 100;
const DEFAULT_NEWEST_SESSION_LIMIT = 20;
const FIXED_CHECK_INTERVAL_SECONDS = 15 * 60;
const FIXED_MAXIMUM_SESSION_SECONDS = 1_800 as const;
const FIXED_RESOURCE_POLICY = Object.freeze({
  route: "balanced" as const,
  max_gpu_workers: 1 as const,
  max_cpu_workers: 1 as const,
  pause_on_battery: true as const,
  maximum_session_seconds: FIXED_MAXIMUM_SESSION_SECONDS,
});
const SESSION_KEYS = [
  "adapter_version", "ended_at", "events_complete", "installation_id",
  "project_display_name", "project_display_name_origin", "project_id",
  "project_manual_label_revision", "provider", "provider_version",
  "session_display_name", "session_display_name_origin", "session_id",
  "session_manual_label_revision", "source_schema_version", "started_at",
  "terminal_state",
] as const;
const CONSENT_STATUS_KEYS = new Set([
  "consent_active", "indexed_projects", "indexed_sessions",
  "verification_capability",
]);
const VERIFICATION_KEYS = new Set([
  "candidate_schema_version", "classifier_version", "live_classification_enabled",
  "normalizer_version", "reason_code", "state", "supported_kinds",
]);
const SAFE_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const TERMINAL_SESSION_STATES = new Set([
  "completed", "interrupted", "failed", "blocked", "abandoned", "unknown",
]);
const VERIFICATION_STATES = new Set([
  "supported", "validation_only", "unsupported", "incompatible", "not_authorized",
]);
const VERIFICATION_KINDS = new Set([
  "test", "build", "lint", "type_check", "security", "artifact_validation",
]);
const ELIGIBLE_READINESS_STATES = new Set([
  "known", "unknown", "abstained", "not_applicable",
]);

type Confirmation = { kind: "renew" | "revoke"; grantId: string } | null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: ReadonlySet<string> | readonly string[],
): boolean {
  const keys = expected instanceof Set ? [...expected] : [...expected];
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => actual.includes(key));
}

function isSafeNullableString(value: unknown, maxLength: number): boolean {
  return value === null || (
    typeof value === "string" && value.length >= 1 && value.length <= maxLength &&
    !/[\u0000-\u001f\u007f]/.test(value)
  );
}

function isSafeNullableVersion(value: unknown): boolean {
  return value === null || (typeof value === "string" && SAFE_VERSION.test(value));
}

function isUtcTimestamp(value: unknown): value is string {
  return typeof value === "string" && /(?:Z|\+00:00)$/.test(value) &&
    Number.isFinite(Date.parse(value));
}

function isProjectSession(value: unknown, projectId: string): value is CodexSession {
  if (!isRecord(value) || !hasExactKeys(value, SESSION_KEYS)) return false;
  const origins = new Set(["provider", "manual", "unknown"]);
  // Automation grants enqueue text-analysis jobs for the providers the local
  // runtime has a reviewed text surface for: Codex (app-server) and Claude
  // Code (transcript text window, ADR 0011). A project belongs to one provider.
  return (value.provider === "codex" || value.provider === "claude_code") &&
    value.project_id === projectId &&
    typeof value.session_id === "string" && isPseudonym(value.session_id) &&
    typeof value.installation_id === "string" && isPseudonym(value.installation_id) &&
    isSafeNullableString(value.project_display_name, 120) &&
    isSafeNullableString(value.session_display_name, 160) &&
    origins.has(value.project_display_name_origin as string) &&
    origins.has(value.session_display_name_origin as string) &&
    Number.isSafeInteger(value.project_manual_label_revision) &&
    (value.project_manual_label_revision as number) >= 0 &&
    Number.isSafeInteger(value.session_manual_label_revision) &&
    (value.session_manual_label_revision as number) >= 0 &&
    isSafeNullableVersion(value.provider_version) &&
    typeof value.adapter_version === "string" && SAFE_VERSION.test(value.adapter_version) &&
    isSafeNullableVersion(value.source_schema_version) &&
    isUtcTimestamp(value.started_at) &&
    (value.ended_at === null || isUtcTimestamp(value.ended_at)) &&
    (value.terminal_state === null || TERMINAL_SESSION_STATES.has(value.terminal_state as string)) &&
    typeof value.events_complete === "boolean";
}

function parseProjectSessions(
  value: unknown,
  projectId: string,
): CodexSession[] | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["sessions", "limit", "offset", "total", "has_more"]) ||
    value.limit !== SESSION_PAGE_LIMIT || value.offset !== 0 ||
    !Number.isSafeInteger(value.total) || (value.total as number) < 0 ||
    typeof value.has_more !== "boolean" || !Array.isArray(value.sessions) ||
    value.sessions.length > SESSION_PAGE_LIMIT ||
    value.sessions.length > (value.total as number) ||
    value.has_more !== (value.sessions.length < (value.total as number)) ||
    !value.sessions.every((session) => isProjectSession(session, projectId))
  ) {
    return null;
  }
  const sessions = value.sessions as CodexSession[];
  if (new Set(sessions.map((session) => session.session_id)).size !== sessions.length) {
    return null;
  }
  return [...sessions].sort(
    (left, right) => Date.parse(right.started_at) - Date.parse(left.started_at),
  );
}

function parseConsentActive(value: unknown, provider: LocalProvider): boolean | null {
  if (provider === "codex") return parseConsentStatus(value)?.consent_active ?? null;
  if (!isRecord(value) || typeof value.consent_active !== "boolean") return null;
  return value.consent_active;
}

function parseConsentStatus(value: unknown): CodexLocalSourceStatus | null {
  if (!isRecord(value) || !hasExactKeys(value, CONSENT_STATUS_KEYS)) return null;
  const verification = value.verification_capability;
  if (
    typeof value.consent_active !== "boolean" ||
    !Number.isSafeInteger(value.indexed_projects) ||
    (value.indexed_projects as number) < 0 ||
    !Number.isSafeInteger(value.indexed_sessions) ||
    (value.indexed_sessions as number) < 0 ||
    !isRecord(verification) || !hasExactKeys(verification, VERIFICATION_KEYS) ||
    typeof verification.live_classification_enabled !== "boolean" ||
    typeof verification.reason_code !== "string" ||
    !SAFE_VERSION.test(verification.reason_code) ||
    !VERIFICATION_STATES.has(verification.state as string) ||
    !Array.isArray(verification.supported_kinds) ||
    verification.supported_kinds.some((kind) => !VERIFICATION_KINDS.has(kind as string)) ||
    new Set(verification.supported_kinds).size !== verification.supported_kinds.length ||
    !isSafeNullableVersion(verification.candidate_schema_version) ||
    !isSafeNullableVersion(verification.classifier_version) ||
    !isSafeNullableVersion(verification.normalizer_version)
  ) {
    return null;
  }
  return value as unknown as CodexLocalSourceStatus;
}

function readinessEligible(metric: MetricReadiness): boolean {
  return ELIGIBLE_READINESS_STATES.has(metric.state) &&
    metric.reason_code !== "provider_compatibility_unverified";
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function formatTimestamp(value: string): string {
  return `${new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value))} UTC`;
}

function grantTone(state: AutomationGrantRecord["state"]): PillTone {
  if (state === "active") return "positive";
  if (state === "expired") return "warning";
  return "neutral";
}

function usesReviewedResourcePolicy(grant: AutomationGrantRecord): boolean {
  const policy = grant.scope.resource_policy;
  return policy.route === FIXED_RESOURCE_POLICY.route &&
    policy.max_gpu_workers === FIXED_RESOURCE_POLICY.max_gpu_workers &&
    policy.max_cpu_workers === FIXED_RESOURCE_POLICY.max_cpu_workers &&
    policy.pause_on_battery === FIXED_RESOURCE_POLICY.pause_on_battery &&
    policy.maximum_session_seconds === FIXED_RESOURCE_POLICY.maximum_session_seconds;
}

function grantErrorCopy(code: string | null): string | null {
  if (code === null) return null;
  if (code === "candidate_scope_mismatch") {
    return "A candidate did not match this exact provider/project scope; no job was scheduled for it.";
  }
  if (code === "automation_check_failed") {
    return "The last local check failed safely. Provider error text was discarded.";
  }
  if (code === "automation_resource_policy_unsupported") {
    return "This historical resource profile is not executable or renewable under the reviewed automation policy.";
  }
  if (code === "automation_paused_for_power_source") {
    return "Admission was paused because local power was battery or unknown. No provider refresh or job scheduling occurred.";
  }
  return "The last check recorded an unrecognized content-free failure code; raw error text remains hidden.";
}

function safeActionError(error: unknown): string {
  const reason = error instanceof TransportError ? error.reasonCode : null;
  if (reason === "automation_consent_required" ||
      (error instanceof TransportError && error.status === 403)) {
    return "Standing redacted-content consent is no longer active. Re-authorize the local source before continuing.";
  }
  if (reason === "automation_metric_unsupported") {
    return "At least one selected metric is not supported by the reviewed automation pack.";
  }
  if (reason === "automation_project_not_indexed") {
    return "This exact project is no longer present in the safe local index.";
  }
  if (reason === "automation_resource_policy_unsupported") {
    return "This historical resource profile is readable but is not executable or renewable.";
  }
  if (reason === "automation_grant_not_found" ||
      (error instanceof TransportError && error.status === 404)) {
    return "This grant no longer exists. Refresh the project automation settings.";
  }
  if (reason === "automation_grant_conflict" ||
      (error instanceof TransportError && error.status === 409)) {
    return "The grant changed or an equivalent scope already exists. Refresh before trying again.";
  }
  return "The local automation command could not be verified. No provider error or session content is shown.";
}

function projectRouteClick(
  event: ReactMouseEvent<HTMLAnchorElement>,
  destination: AppRoute,
  navigate: (route: AppRoute) => void,
) {
  if (
    event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
    event.shiftKey || event.altKey ||
    (event.currentTarget.target && event.currentTarget.target !== "_self")
  ) return;
  event.preventDefault();
  navigate(destination);
}

export function ProjectAutomationSettings({
  projectId,
  runtimeMode,
  serviceState,
  transport,
  navigate,
}: {
  projectId: string;
  runtimeMode: RuntimeDataMode;
  serviceState: RuntimeServiceState;
  transport: PromptEnhancerTransport;
  navigate: (route: AppRoute) => void;
}) {
  const [sessions, setSessions] = useState<CodexSession[] | null>(null);
  const [consentActive, setConsentActive] = useState<boolean | null>(null);
  const [provider, setProvider] = useState<LocalProvider>("codex");
  const [readiness, setReadiness] = useState<SessionMetricReadinessReport | null>(null);
  const [grants, setGrants] = useState<AutomationGrantRecord[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [readinessError, setReadinessError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedMetrics, setSelectedMetrics] = useState<Set<string>>(() => new Set());
  const [newestLimit, setNewestLimit] = useState(String(DEFAULT_NEWEST_SESSION_LIMIT));
  const [acknowledged, setAcknowledged] = useState(false);
  const [actionPending, setActionPending] = useState("");
  const [actionError, setActionError] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [pollResult, setPollResult] = useState<AutomationPollResult | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const localAvailable = runtimeMode === "local_real" && serviceState === "available";

  useEffect(() => {
    actionController.current?.abort();
    actionController.current = null;
    setActionPending("");
    setActionError("");
    setSelectedMetrics(new Set());
    setNewestLimit(String(DEFAULT_NEWEST_SESSION_LIMIT));
    setAcknowledged(false);
    setConfirmation(null);
    setPollResult(null);
  }, [localAvailable, projectId]);

  useEffect(() => {
    if (!localAvailable) {
      setSessions(null);
      setConsentActive(null);
      setReadiness(null);
      setGrants(null);
      return;
    }
    const controller = new AbortController();
    setAcknowledged(false);
    setConfirmation(null);
    setLoading(true);
    setLoadError("");
    setReadinessError("");
    void (async () => {
      try {
        const sessionPage = await transport.listProjectSessions(
          projectId, SESSION_PAGE_LIMIT, 0, controller.signal,
        );
        if (controller.signal.aborted) return;
        const verifiedSessions = parseProjectSessions(sessionPage, projectId);
        if (verifiedSessions === null) {
          setLoadError("The local project or consent response could not be verified.");
          return;
        }
        // The project's provider decides which consent and grants apply.
        const projectProvider: LocalProvider =
          verifiedSessions[0]?.provider === "claude_code" ? "claude_code" : "codex";
        const [sourceStatus, allGrants] = await Promise.all([
          projectProvider === "claude_code"
            ? transport.getClaudeLocalSourceStatus(controller.signal)
            : transport.getCodexLocalSourceStatus(controller.signal),
          transport.listAutomationGrants(projectProvider, false, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const verifiedConsent = parseConsentActive(sourceStatus, projectProvider);
        if (verifiedConsent === null) {
          setLoadError("The local project or consent response could not be verified.");
          return;
        }
        setProvider(projectProvider);
        setSessions(verifiedSessions);
        setConsentActive(verifiedConsent);
        setGrants(allGrants.filter((grant) => grant.scope.project_id === projectId));
        const newest = verifiedSessions[0];
        if (newest === undefined) {
          setReadiness(null);
          return;
        }
        try {
          const report = await transport.getSessionMetricReadiness(
            newest.session_id,
            "coaching_profile_v1",
            controller.signal,
          );
          if (controller.signal.aborted) return;
          if (report.provider !== projectProvider || report.session_id !== newest.session_id) {
            setReadinessError("Metric readiness did not match the exact project session.");
            return;
          }
          setReadiness(report);
          const eligible = new Set(
            report.metrics.filter(readinessEligible).map((metric) => metric.metric_key),
          );
          setSelectedMetrics((current) =>
            new Set([...current].filter((key) => eligible.has(key))),
          );
        } catch {
          if (!controller.signal.aborted) {
            setReadinessError(
              "Metric readiness could not be verified for the newest indexed session.",
            );
          }
        }
      } catch {
        if (!controller.signal.aborted) {
          setLoadError(
            "The project automation boundary could not be loaded. No cached or fictional state is shown.",
          );
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [localAvailable, projectId, refreshKey, transport]);

  useEffect(() => () => actionController.current?.abort(), []);

  const projectGrants = useMemo(
    () => [...(grants ?? [])].sort((left, right) => {
      const stateRank = { active: 0, expired: 1, revoked: 2 } as const;
      return stateRank[left.state] - stateRank[right.state] ||
        Date.parse(right.renewed_at) - Date.parse(left.renewed_at);
    }),
    [grants],
  );
  const eligibleMetricKeys = useMemo(
    () => new Set(
      (readiness?.metrics ?? []).filter(readinessEligible).map((metric) => metric.metric_key),
    ),
    [readiness],
  );
  const parsedNewestLimit = Number(newestLimit);
  const newestLimitValid = Number.isSafeInteger(parsedNewestLimit) &&
    parsedNewestLimit >= 1 && parsedNewestLimit <= 100;
  const projectIndexed = (sessions?.length ?? 0) > 0;
  const readinessVerified = readiness !== null && readinessError === "";
  const selectedEligible = selectedMetrics.size > 0 &&
    [...selectedMetrics].every((key) => eligibleMetricKeys.has(key));
  const canCreate = localAvailable && !loading && !actionPending && consentActive &&
    projectIndexed && readinessVerified && selectedEligible && newestLimitValid && acknowledged;

  function beginAction(key: string): AbortController | null {
    if (actionPending) return null;
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setActionPending(key);
    setActionError("");
    return controller;
  }

  function finishAction(controller: AbortController) {
    if (actionController.current === controller) {
      actionController.current = null;
      setActionPending("");
    }
  }

  function upsertGrant(record: AutomationGrantRecord) {
    if (record.scope.provider !== provider || record.scope.project_id !== projectId) {
      setActionError(
        "The grant response did not match this exact provider and project. Refresh before continuing.",
      );
      return;
    }
    setGrants((current) => {
      const without = (current ?? []).filter((grant) => grant.grant_id !== record.grant_id);
      return [...without, record];
    });
  }

  async function createGrant() {
    if (!canCreate) return;
    const controller = beginAction("create");
    if (controller === null) return;
    const request: AutomationGrantCreateRequest = {
      provider,
      project_id: projectId,
      metric_keys: [...selectedMetrics].sort(),
      newest_session_limit: parsedNewestLimit,
      check_interval_seconds: FIXED_CHECK_INTERVAL_SECONDS,
      resource_policy: { ...FIXED_RESOURCE_POLICY },
    };
    try {
      const created = await transport.createAutomationGrant(request, controller.signal);
      if (!controller.signal.aborted) {
        upsertGrant(created);
        setAcknowledged(false);
      }
    } catch (error) {
      if (!controller.signal.aborted) setActionError(safeActionError(error));
    } finally {
      finishAction(controller);
    }
  }

  async function renewGrant(grant: AutomationGrantRecord) {
    if (!consentActive || !projectIndexed || !readinessVerified ||
        !grant.scope.metric_keys.every((key) => eligibleMetricKeys.has(key))) return;
    const controller = beginAction(`renew:${grant.grant_id}`);
    if (controller === null) return;
    try {
      const renewed = await transport.renewAutomationGrant(
        grant.grant_id,
        grant.scope,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        upsertGrant(renewed);
        setConfirmation(null);
      }
    } catch (error) {
      if (!controller.signal.aborted) setActionError(safeActionError(error));
    } finally {
      finishAction(controller);
    }
  }

  async function revokeGrant(grant: AutomationGrantRecord) {
    const controller = beginAction(`revoke:${grant.grant_id}`);
    if (controller === null) return;
    try {
      const revoked = await transport.revokeAutomationGrant(
        grant.grant_id,
        grant.scope,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        upsertGrant(revoked);
        setConfirmation(null);
      }
    } catch (error) {
      if (!controller.signal.aborted) setActionError(safeActionError(error));
    } finally {
      finishAction(controller);
    }
  }

  async function pollNow() {
    const controller = beginAction("poll");
    if (controller === null) return;
    try {
      const result = await transport.pollAutomationGrants(controller.signal);
      if (controller.signal.aborted) return;
      const refreshed = await transport.listAutomationGrants(provider, false, controller.signal);
      if (!controller.signal.aborted) {
        setPollResult(result);
        setGrants(refreshed.filter((grant) => grant.scope.project_id === projectId));
      }
    } catch (error) {
      if (!controller.signal.aborted) setActionError(safeActionError(error));
    } finally {
      finishAction(controller);
    }
  }

  if (runtimeMode === "synthetic_demo") {
    return (
      <section aria-labelledby="automation-settings-title" className="automation-settings">
        <header className="automation-settings__header route-header">
          <div>
            <p className="eyebrow">Synthetic demo · fictional fixtures only</p>
            <h1 id="automation-settings-title">Project automation</h1>
          </div>
        </header>
        <div className="automation-settings__boundary" role="note">
          <strong>Automation is not running</strong>
          <span>
            Demo mode does not create standing consent, poll sessions, or invent grant and job history.
            Start Local real mode to configure an indexed project.
          </span>
        </div>
      </section>
    );
  }

  if (serviceState !== "available") {
    return (
      <section aria-labelledby="automation-settings-title" className="automation-settings">
        <header className="automation-settings__header route-header">
          <div>
            <p className="eyebrow">Local real · project-scoped settings</p>
            <h1 id="automation-settings-title">Project automation</h1>
          </div>
        </header>
        <div className="automation-settings__boundary" role="status">
          <strong>{serviceState === "checking" ? "Checking the local service" : "Local service unavailable"}</strong>
          <span>
            {serviceState === "checking"
              ? "Automation requests stay paused until the loopback health check succeeds."
              : "No cached or fictional grant state is shown. Restart the local service and try again."}
          </span>
        </div>
      </section>
    );
  }

  const projectDestination: AppRoute = { name: "project_overview", projectId };
  const jobDestination: AppRoute = { name: "analysis_jobs" };
  return (
    <section aria-labelledby="automation-settings-title" className="automation-settings">
      <header className="automation-settings__header route-header">
        <div>
          <p className="eyebrow">
            Local real · {provider === "claude_code" ? "Claude Code" : "Codex"} · project {shortId(projectId)}
          </p>
          <h1 id="automation-settings-title">Project automation</h1>
          <p>
            Schedule reviewed local analysis only for new or changed sessions in this exact project.
            A grant schedules work; it never proves that a model ran or that a metric is valid.
            After a source is consented, every indexed project receives the standard grant
            automatically; create one here only to choose a narrower scope.
          </p>
        </div>
        <nav aria-label="Automation destinations">
          <a
            href={routePath(projectDestination)}
            onClick={(event) => projectRouteClick(event, projectDestination, navigate)}
          >
            Project metrics
          </a>
          <a
            href={routePath(jobDestination)}
            onClick={(event) => projectRouteClick(event, jobDestination, navigate)}
          >
            Open Job Centre
          </a>
        </nav>
      </header>

      <aside className="automation-settings__remote-boundary" role="note">
        <strong>Remote execution is never unattended</strong>
        <span>
          This renewable grant covers local scheduling only. Every remote Codex or Claude call still
          requires a fresh per-run redaction preview and one-shot approval for the exact destination and model.
        </span>
      </aside>

      {loading && sessions === null ? (
        <div aria-busy="true" className="automation-settings__loading" role="status">
          Verifying the local project, consent, readiness, and grants…
        </div>
      ) : loadError ? (
        <div className="automation-settings__error" role="alert">
          <strong>Automation settings unavailable</strong>
          <span>{loadError}</span>
          <button className="button button--secondary" onClick={() => setRefreshKey((value) => value + 1)} type="button">
            Retry safely
          </button>
        </div>
      ) : (
        <>
          <section aria-labelledby="automation-readiness-title" className="automation-readiness">
            <header>
              <div>
                <p className="eyebrow">Activation gates</p>
                <h2 id="automation-readiness-title">Consent and measurement readiness</h2>
              </div>
              <button
                className="button button--secondary button--compact"
                disabled={loading || Boolean(actionPending)}
                onClick={() => setRefreshKey((value) => value + 1)}
                type="button"
              >
                {loading ? "Refreshing…" : "Refresh settings"}
              </button>
            </header>
            <div className="automation-readiness__gates">
              <div data-ready={consentActive === true}>
                <strong>{consentActive === null ? "Consent not verified" : consentActive ? "Consent active" : "Consent required"}</strong>
                <span>Redacted-content access for the local {provider === "claude_code" ? "Claude Code" : "Codex"} source</span>
              </div>
              <div data-ready={projectIndexed}>
                <strong>{projectIndexed ? "Project indexed" : "Project not indexed"}</strong>
                <span>{projectIndexed ? `${sessions?.length ?? 0} recent sessions verified` : "Index this project before creating a grant"}</span>
              </div>
              <div data-ready={readinessVerified}>
                <strong>{readinessVerified ? "Readiness verified" : "Readiness unavailable"}</strong>
                <span>{readinessVerified ? `Newest session ${shortId(readiness!.session_id)}` : readinessError || "No indexed session is available"}</span>
              </div>
            </div>
          </section>

          <div className="automation-settings__layout">
            <section aria-labelledby="automation-create-title" className="automation-create">
              <header>
                <p className="eyebrow">New renewable grant</p>
                <h2 id="automation-create-title">Choose what stays current</h2>
                <p>Only the selected reviewed metric keys enter this project scope.</p>
              </header>

              <fieldset className="automation-create__metrics" disabled={!readinessVerified || Boolean(actionPending)}>
                <legend>Project metrics</legend>
                <div className="automation-create__metric-tools">
                  <span>{selectedMetrics.size} selected · {eligibleMetricKeys.size} currently attemptable</span>
                  <button
                    className="button button--secondary button--compact"
                    onClick={() => {
                      setSelectedMetrics(new Set(eligibleMetricKeys));
                      setAcknowledged(false);
                    }}
                    type="button"
                  >
                    Select attemptable
                  </button>
                  <button
                    className="button button--secondary button--compact"
                    onClick={() => {
                      setSelectedMetrics(new Set());
                      setAcknowledged(false);
                    }}
                    type="button"
                  >
                    Clear
                  </button>
                </div>
                <div className="automation-create__metric-list">
                  {(readiness?.metrics ?? []).map((metric) => {
                    const eligible = readinessEligible(metric);
                    return (
                      <label data-eligible={eligible} key={metric.metric_key}>
                        <input
                          aria-label={metric.display_name}
                          checked={selectedMetrics.has(metric.metric_key)}
                          disabled={!eligible}
                          onChange={(event) => {
                            setSelectedMetrics((current) => {
                              const next = new Set(current);
                              if (event.target.checked) next.add(metric.metric_key);
                              else next.delete(metric.metric_key);
                              return next;
                            });
                            setAcknowledged(false);
                          }}
                          type="checkbox"
                        />
                        <span>
                          <strong>{metric.display_name}</strong>
                          <small>{metric.metric_key}</small>
                        </span>
                        <StatusPill tone={eligible ? "info" : "warning"}>
                          {eligible ? "Attemptable" : metric.state.replace("_", " ")}
                        </StatusPill>
                      </label>
                    );
                  })}
                  {readinessVerified && readiness?.metrics.length === 0 && (
                    <p>No reviewed automation metrics were returned.</p>
                  )}
                </div>
              </fieldset>

              <label className="automation-create__newest field">
                <span>Newest sessions per check</span>
                <input
                  aria-label="Newest sessions per check"
                  aria-describedby="automation-newest-help"
                  disabled={Boolean(actionPending)}
                  inputMode="numeric"
                  max={100}
                  min={1}
                  onChange={(event) => {
                    setNewestLimit(event.target.value);
                    setAcknowledged(false);
                  }}
                  type="number"
                  value={newestLimit}
                />
                <small id="automation-newest-help">
                  Default 20; allowed 1–100. Only new, changed, or provenance-incompatible fingerprints are scheduled.
                </small>
              </label>
              {!newestLimitValid && <p className="automation-create__validation" role="alert">Choose a whole number from 1 to 100.</p>}

              <dl className="automation-create__policy">
                <div><dt>Execution</dt><dd>Local only</dd></div>
                <div><dt>Route</dt><dd>Balanced</dd></div>
                <div><dt>CPU admission</dt><dd>1 concurrent lane per grant</dd></div>
                <div><dt>GPU admission</dt><dd>Ceiling 1; current use 0</dd></div>
                <div><dt>Check cadence</dt><dd>Every 15 minutes while the service runs</dd></div>
                <div><dt>Grant lifetime</dt><dd>30 days, then renew explicitly</dd></div>
                <div><dt>Power guard</dt><dd>Battery/unknown pauses new admission only</dd></div>
                <div><dt>Runtime budget</dt><dd>1,800 seconds declared; hard deadline not yet enforced</dd></div>
              </dl>

              <label className="automation-create__consent">
                <input
                  checked={acknowledged}
                  disabled={!consentActive || !projectIndexed || !readinessVerified || Boolean(actionPending)}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  type="checkbox"
                />
                <span>
                  I authorize this local service to schedule selected metrics for new or changed sessions
                  in this exact project for 30 days. I can revoke the grant at any time.
                </span>
              </label>

              <button
                className="button button--primary automation-create__submit"
                disabled={!canCreate}
                onClick={() => void createGrant()}
                type="button"
              >
                {actionPending === "create" ? "Creating local grant…" : "Create 30-day local grant"}
              </button>
            </section>

            <section aria-labelledby="automation-grants-title" className="automation-grants">
              <header>
                <div>
                  <p className="eyebrow">Durable consent receipts</p>
                  <h2 id="automation-grants-title">Project grants</h2>
                </div>
                <span>{projectGrants.length}</span>
              </header>

              {projectGrants.length === 0 ? (
                <div className="automation-grants__empty">
                  <strong>No grant exists for this project</strong>
                  <span>Nothing is scheduled until the explicit authorization above succeeds.</span>
                </div>
              ) : (
                <div className="automation-grants__list">
                  {projectGrants.map((grant) => {
                    const reviewedPolicy = usesReviewedResourcePolicy(grant);
                    const renewAllowed = reviewedPolicy && consentActive && projectIndexed && readinessVerified &&
                      grant.scope.metric_keys.every((key) => eligibleMetricKeys.has(key));
                    const errorCopy = grantErrorCopy(grant.last_error_code);
                    const confirming = confirmation?.grantId === grant.grant_id
                      ? confirmation.kind
                      : null;
                    return (
                      <article key={grant.grant_id}>
                        <header>
                          <div>
                            <strong>Grant {shortId(grant.grant_id)}</strong>
                            <small>Revision {grant.revision}</small>
                          </div>
                          <StatusPill tone={grantTone(grant.state)}>{grant.state}</StatusPill>
                        </header>
                        <dl>
                          <div><dt>Newest</dt><dd>{grant.scope.newest_session_limit} sessions</dd></div>
                          <div><dt>Next check</dt><dd>{formatTimestamp(grant.next_check_at)}</dd></div>
                          <div><dt>Expires</dt><dd>{formatTimestamp(grant.expires_at)}</dd></div>
                          <div><dt>Route</dt><dd>{grant.scope.resource_policy.route}</dd></div>
                          <div><dt>Cadence</dt><dd>{grant.scope.check_interval_seconds} seconds</dd></div>
                          <div><dt>CPU admission ceiling</dt><dd>{grant.scope.resource_policy.max_cpu_workers}</dd></div>
                          <div><dt>GPU admission ceiling</dt><dd>{grant.scope.resource_policy.max_gpu_workers}; current reviewed session-quality use 0</dd></div>
                          <div><dt>Declared runtime budget</dt><dd>{grant.scope.resource_policy.maximum_session_seconds} seconds; hard deadline unenforced</dd></div>
                          <div><dt>Power admission</dt><dd>{grant.scope.resource_policy.pause_on_battery ? "Battery/unknown pauses new work only" : "Historical continue policy (unsupported)"}</dd></div>
                          <div><dt>Boundary</dt><dd>{grant.scope.local_only ? "Local only" : "Invalid"}</dd></div>
                        </dl>
                        <details className="automation-grants__metric-scope">
                          <summary>{grant.scope.metric_keys.length} selected {grant.scope.metric_keys.length === 1 ? "metric" : "metrics"}</summary>
                          <ul>
                            {grant.scope.metric_keys.map((key) => <li key={key}>{key}</li>)}
                          </ul>
                        </details>
                        {errorCopy && <p className="automation-grants__warning">{errorCopy}</p>}
                        {!reviewedPolicy ? (
                          <p className="automation-grants__warning">
                            This historical grant uses an unsupported resource profile. Its stored values remain readable, but it is not executable or renewable.
                          </p>
                        ) : null}
                        {confirming ? (
                          <div aria-label={`Confirm ${confirming} grant`} className="automation-grants__confirm" role="group">
                            <p>
                              {confirming === "revoke"
                                ? "Revoke this exact grant and cancel its active jobs? Durable receipts remain."
                                : "Renew this exact scope for a fresh 30 days? Current consent and readiness will be checked again."}
                            </p>
                            <button
                              className={confirming === "revoke" ? "button button--danger-ghost" : "button button--primary"}
                              disabled={Boolean(actionPending)}
                              onClick={() => void (confirming === "revoke" ? revokeGrant(grant) : renewGrant(grant))}
                              type="button"
                            >
                              Confirm {confirming}
                            </button>
                            <button
                              className="button button--secondary"
                              disabled={Boolean(actionPending)}
                              onClick={() => setConfirmation(null)}
                              type="button"
                            >
                              Keep unchanged
                            </button>
                          </div>
                        ) : (
                          <div className="automation-grants__actions">
                            <button
                              className="button button--secondary button--compact"
                              disabled={!renewAllowed || Boolean(actionPending)}
                              onClick={() => setConfirmation({ kind: "renew", grantId: grant.grant_id })}
                              type="button"
                            >
                              Renew 30 days
                            </button>
                            {grant.state === "active" && (
                              <button
                                className="button button--danger-ghost button--compact"
                                disabled={Boolean(actionPending)}
                                onClick={() => setConfirmation({ kind: "revoke", grantId: grant.grant_id })}
                                type="button"
                              >
                                Revoke grant
                              </button>
                            )}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}

              <footer className="automation-grants__poll">
                <div>
                  <strong>Run the due-grant scheduler now</strong>
                  <span>This checks all due local grants, not only this project. Jobs appear in the Job Centre.</span>
                </div>
                <button
                  className="button button--secondary"
                  disabled={Boolean(actionPending)}
                  onClick={() => void pollNow()}
                  type="button"
                >
                  {actionPending === "poll" ? "Checking due grants…" : "Check due grants now"}
                </button>
              </footer>
              {pollResult && (
                <div aria-live="polite" className="automation-grants__poll-result" role="status">
                  <strong>Scheduler receipt</strong>
                  <span>{pollResult.grants_checked} grants checked · {pollResult.candidates_seen} candidates seen</span>
                  <span>{pollResult.jobs_created} jobs created · {pollResult.jobs_reused} reused · {pollResult.jobs_superseded} superseded</span>
                  <span>{pollResult.grants_power_paused} power-paused · {pollResult.grants_policy_unsupported} unsupported profiles</span>
                  <span>{pollResult.grants_revoked} grants revoked · {pollResult.failures} safe failures</span>
                  <span>Session-quality result publication cutoff: {pollResult.session_quality_result_publication_deadline_enforced ? "enforced" : "not enforced"}</span>
                  <span>Blocking-call force-stop: {pollResult.blocking_execution_preemption_enforced ? "enforced" : "not provided"}</span>
                  <span>Hard runtime deadline: {pollResult.maximum_session_runtime_deadline_enforced ? "enforced" : "not enforced"}</span>
                </div>
              )}
            </section>
          </div>
        </>
      )}

      {actionError && (
        <div className="automation-settings__error" role="alert">
          <strong>Automation command not applied</strong>
          <span>{actionError}</span>
        </div>
      )}
    </section>
  );
}
