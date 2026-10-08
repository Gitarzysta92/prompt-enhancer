import { SessionTranscriptPane } from "../session-reader/SessionTranscriptPane";
import { SessionTimelinePane } from "../session-timeline/SessionTimelinePane";
import { ModelJudgePane } from "../model-judge/ModelJudgePane";
import { SessionRadarCard } from "../session-radar/SessionRadarCard";
import { ProjectTimelinePane } from "../project-timeline/ProjectTimelinePane";
import { openLiveWindow } from "../live-window/LiveMiniWindow";
import { isLocalProvider } from "../../shared/api/contracts";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { SessionMetricCard } from "../../entities/analysis/SessionMetricCard";
import { MetricCoveragePanel } from "../metric-coverage";
import {
  METRIC_TAXONOMY,
  metricCategoryDefinition,
  metricCategoryFor,
} from "../../entities/analysis/metricTaxonomy";
import type {
  CodexSession,
  Provider,
  ProviderCompatibilityStatus,
  ProjectSessionListResponse,
  PromptEnhancerTransport,
  SessionAnalysisRunResponse,
  SessionCoachingProjection,
  SessionMetric,
  SessionMetricReadinessReport,
  SessionQualityAggregate,
  SessionTextAnalysisCapability,
} from "../../shared/api/contracts";
import type {
  AppRoute,
  MetricCategory,
} from "../../shared/platform/platform";
import { routePath } from "../../shared/platform/platform";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { Icon, type IconName } from "../../shared/ui/Icon";
import {
  createAggregateQualityMetricProfile,
  createQualityMetricProfile,
  isQualityProfileCategory,
  QualityProfileView,
} from "../quality-profile";
import {
  CoachingLoop,
  createCoachingLoopViewModel,
} from "../coaching-loop";
import { ModelLinkExperimentPanel } from "../model-link-experiment";
import { ModelEnsemblePanel } from "../model-ensemble";

export type ProjectWorkspaceRoute = Extract<
  AppRoute,
  {
    name:
      | "project_overview"
      | "project_sessions"
      | "project_metrics"
      | "session_metrics";
  }
>;

const SAFE_ID = /^[a-f0-9]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function activeRedactedConsent(value: unknown): boolean | null {
  if (
    !isRecord(value) ||
    typeof value.consent_active !== "boolean" ||
    !Number.isSafeInteger(value.indexed_sessions) ||
    (value.indexed_sessions as number) < 0 ||
    !Number.isSafeInteger(value.indexed_projects) ||
    (value.indexed_projects as number) < 0 ||
    !isRecord(value.verification_capability)
  ) {
    return null;
  }
  return value.consent_active;
}

function isProjectSession(
  value: unknown,
  expectedProjectId: string,
): value is CodexSession {
  if (!isRecord(value)) return false;
  return (
    typeof value.session_id === "string" &&
    SAFE_ID.test(value.session_id) &&
    typeof value.installation_id === "string" &&
    SAFE_ID.test(value.installation_id) &&
    value.project_id === expectedProjectId &&
    isLocalProvider(value.provider) &&
    isNullableString(value.project_display_name) &&
    isNullableString(value.session_display_name) &&
    ["provider", "manual", "unknown"].includes(
      value.project_display_name_origin as string,
    ) &&
    ["provider", "manual", "unknown"].includes(
      value.session_display_name_origin as string,
    ) &&
    Number.isSafeInteger(value.project_manual_label_revision) &&
    (value.project_manual_label_revision as number) >= 0 &&
    Number.isSafeInteger(value.session_manual_label_revision) &&
    (value.session_manual_label_revision as number) >= 0 &&
    isNullableString(value.provider_version) &&
    typeof value.adapter_version === "string" &&
    isNullableString(value.source_schema_version) &&
    typeof value.started_at === "string" &&
    isNullableString(value.ended_at) &&
    isNullableString(value.terminal_state) &&
    typeof value.events_complete === "boolean"
  );
}

function isCompleteProjectSessionPage(
  value: unknown,
  expectedProjectId: string,
  expectedLimit: number,
  expectedOffset = 0,
): value is ProjectSessionListResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.sessions) ||
    value.limit !== expectedLimit ||
    value.offset !== expectedOffset ||
    !Number.isSafeInteger(value.total) ||
    (value.total as number) < 0 ||
    typeof value.has_more !== "boolean"
  ) {
    return false;
  }
  const total = value.total as number;
  const expectedPageSize = Math.min(Math.max(0, total - expectedOffset), expectedLimit);
  if (
    value.sessions.length !== expectedPageSize ||
    value.has_more !== (expectedOffset + expectedPageSize < total) ||
    !value.sessions.every((session) =>
      isProjectSession(session, expectedProjectId),
    )
  ) {
    return false;
  }
  const sessionIds = value.sessions.map((session) => session.session_id);
  return new Set(sessionIds).size === sessionIds.length;
}

function visibleLabel(value: string | null | undefined, fallback: string): string {
  return value?.trim() || fallback;
}

function safeTimestamp(value: string): string {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.valueOf())
    ? "Started time unknown"
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "UTC",
      }).format(timestamp);
}

function projectLabel(sessions: readonly CodexSession[]): string {
  const labeled =
    sessions.find(
      (session) =>
        session.project_display_name_origin === "manual" &&
        session.project_display_name?.trim(),
    ) ??
    sessions.find(
      (session) =>
        session.project_display_name_origin === "provider" &&
        session.project_display_name?.trim(),
    ) ??
    sessions.find((session) => session.project_display_name?.trim());
  return visibleLabel(labeled?.project_display_name, "Unnamed project");
}

function selectedCategory(route: ProjectWorkspaceRoute): MetricCategory | null {
  return route.name === "project_metrics" || route.name === "session_metrics"
    ? route.category
    : null;
}

function selectedSessionId(route: ProjectWorkspaceRoute): string | null {
  return route.name === "session_metrics" ? route.sessionId : null;
}

function PlannedCategoryState({ category }: { category: MetricCategory }) {
  const definition = metricCategoryDefinition(category);
  return (
    <section className="metric-plan-state" aria-labelledby="metric-plan-title">
      <span className="metric-plan-state__icon"><Icon name="branch" /></span>
      <div>
        <p className="eyebrow">Calibration before scoring</p>
        <h2 id="metric-plan-title" tabIndex={-1}>{definition.label} is planned, not measured</h2>
        <p>{definition.description}</p>
        <p>
          This view will remain unavailable until its rubric, model revision,
          abstention policy, privacy boundary, and labeled validation set are recorded.
          No placeholder score or inferred value is shown.
        </p>
        <p>
          Any future assessment will use only observable requirements, plans, actions,
          decisions, outcomes, and evidence. It will not claim access to hidden
          reasoning or private chain-of-thought.
        </p>
      </div>
    </section>
  );
}

function ProjectMetricScopeState({ category }: { category: MetricCategory }) {
  const definition = metricCategoryDefinition(category);
  return (
    <section className="metric-scope-state" aria-labelledby="metric-scope-title">
      <span className="metric-scope-state__icon"><Icon name="activity" /></span>
      <div>
        <p className="eyebrow">Session evidence required</p>
        <h2 id="metric-scope-title" tabIndex={-1}>Choose a session for {definition.shortLabel.toLowerCase()}</h2>
        <p>
          Project-wide metric rollups are not calculated in the browser. Choose one
          indexed session above to load exactly one stored metric response.
        </p>
      </div>
    </section>
  );
}

function MetricSnapshotBoundary({
  session,
  metrics,
}: {
  session: CodexSession;
  metrics: readonly SessionMetric[];
}) {
  const packIdentities = new Set(
    metrics.map(
      (metric) => `${metric.metric_pack_key}@${metric.metric_pack_version}`,
    ),
  );
  const mixed = packIdentities.size > 1;
  const legacy =
    metrics.length > 0 && metrics[0].metric_pack_key === "legacy.unknown.session";
  return (
    <div
      className={`snapshot-boundary${session.events_complete && !mixed && !legacy ? "" : " snapshot-boundary--partial"}`}
      role="note"
    >
      <strong>
        {mixed
          ? "Mixed metric-pack provenance - comparison blocked"
          : legacy
            ? "Legacy metric-pack provenance unavailable"
            : session.events_complete
              ? "Indexed event stream marked complete"
              : "Partial event stream - current snapshot only"}
      </strong>
      <p>
        {mixed
          ? "Stored rows disagree about their metric-pack identity. Run an explicit bounded analysis before comparing them."
          : legacy
            ? "These rows predate stored pack identity and must not be compared with current-pack results."
            : "Coverage remains metric-specific. Stream completeness does not turn descriptive observations into a quality or success score."}
      </p>
    </div>
  );
}

const CATEGORY_ICONS: Readonly<Record<MetricCategory, IconName>> = {
  readiness: "check",
  execution: "split",
  tools: "activity",
  "model-usage": "layers",
  outcome: "tasks",
  "prompt-quality": "merge",
  reasoning: "branch",
  other: "search",
};

const CATEGORY_SIGNAL_LABELS: Readonly<Record<MetricCategory, string>> = {
  readiness: "Readiness signals",
  execution: "Execution-flow signals",
  tools: "Tool reliability signals",
  "model-usage": "Model-usage signals",
  outcome: "Outcome-evidence signals",
  "prompt-quality": "Prompt & collaboration signals",
  reasoning: "Logic & decision signals",
  other: "Additional observation signals",
};

const COMPACT_MASTHEAD_ROOT_MARGIN = "64px 0px 0px 0px";

type ProjectSection = "metric-deck" | "sessions";

function projectSection(route: ProjectWorkspaceRoute): ProjectSection {
  return route.name === "project_sessions" || route.name === "session_metrics"
    ? "sessions"
    : "metric-deck";
}

function routeLinkClick(
  event: ReactMouseEvent<HTMLAnchorElement>,
  destination: AppRoute,
  currentRoute: AppRoute,
  navigate: (route: AppRoute) => void,
) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    (event.currentTarget.target && event.currentTarget.target !== "_self")
  ) {
    return;
  }
  event.preventDefault();
  if (routePath(destination) === routePath(currentRoute)) return;
  navigate(destination);
}

function ProjectSectionNavigation({
  enabled,
  navigate,
  route,
  sessionTotal,
  variant,
}: {
  enabled: boolean;
  navigate: (route: AppRoute) => void;
  route: ProjectWorkspaceRoute;
  sessionTotal: number | null;
  variant: "full" | "compact";
}) {
  const activeSection = projectSection(route);
  const metricDestination: AppRoute = {
    name: "project_overview",
    projectId: route.projectId,
  };
  const sessionsDestination: AppRoute = {
    name: "project_sessions",
    projectId: route.projectId,
  };
  const automationDestination: AppRoute = {
    name: "project_automation",
    projectId: route.projectId,
  };
  const metricCurrent =
    activeSection === "metric-deck"
      ? route.name === "project_overview"
        ? "page"
        : "location"
      : undefined;
  const sessionsCurrent =
    activeSection === "sessions"
      ? route.name === "project_sessions"
        ? "page"
        : "location"
      : undefined;

  return (
    <nav
      aria-hidden={enabled ? undefined : true}
      aria-label={
        variant === "compact"
          ? "Project sections while scrolling"
          : "Project sections"
      }
      className={`project-workspace__primary-actions project-workspace__primary-actions--${variant}`}
      data-active={activeSection}
      data-project-section-nav={variant}
    >
      <a
        aria-current={metricCurrent}
        data-section="metric-deck"
        href={routePath(metricDestination)}
        onClick={(event) =>
          routeLinkClick(event, metricDestination, route, navigate)
        }
        tabIndex={enabled ? undefined : -1}
      >
        <Icon name="layers" />
        <span className="project-workspace__section-label">Metric deck</span>
      </a>
      <a
        aria-current={sessionsCurrent}
        aria-label={
          sessionTotal === null
            ? "Sessions"
            : `Sessions, ${sessionTotal} indexed`
        }
        data-section="sessions"
        href={routePath(sessionsDestination)}
        onClick={(event) =>
          routeLinkClick(event, sessionsDestination, route, navigate)
        }
        tabIndex={enabled ? undefined : -1}
      >
        <Icon name="tasks" />
        <span className="project-workspace__section-label">Sessions</span>
        {sessionTotal !== null && (
          <span className="project-workspace__section-count">{sessionTotal}</span>
        )}
      </a>
      <a
        data-section="automation"
        href={routePath(automationDestination)}
        onClick={(event) =>
          routeLinkClick(event, automationDestination, route, navigate)
        }
        tabIndex={enabled ? undefined : -1}
      >
        <Icon name="activity" />
        <span className="project-workspace__section-label">Automation</span>
      </a>
    </nav>
  );
}

function mastheadRouteIdentity(route: ProjectWorkspaceRoute): string {
  if (route.name === "session_metrics") {
    return `${route.name}:${route.projectId}:${route.sessionId}:${route.category}`;
  }
  if (route.name === "project_metrics") {
    return `${route.name}:${route.projectId}:${route.category}`;
  }
  return `${route.name}:${route.projectId}`;
}

const PRIORITIZED_METRIC_TAXONOMY = [
  ...METRIC_TAXONOMY.filter((definition) => definition.id === "prompt-quality"),
  ...METRIC_TAXONOMY.filter((definition) => definition.id !== "prompt-quality"),
] as const;

function MetricCategoryDeck({
  onOpen,
}: {
  onOpen: (category: MetricCategory) => void;
}) {
  return (
    <nav aria-label="Metric categories" className="project-metric-deck">
      {PRIORITIZED_METRIC_TAXONOMY.map((definition) => (
        <button
          className={`project-metric-card project-metric-card--${definition.id} project-metric-card--${definition.availability}${
            definition.id === "prompt-quality"
              ? " project-metric-card--featured"
              : ""
          }`}
          key={definition.id}
          onClick={() => onOpen(definition.id)}
          type="button"
        >
          <span className="project-metric-card__icon">
            <Icon name={CATEGORY_ICONS[definition.id]} />
          </span>
          <span className="project-metric-card__copy">
            <strong>{definition.shortLabel}</strong>
            <span>{definition.question}</span>
          </span>
          <span className="project-metric-card__meta">
            {definition.id === "prompt-quality"
              ? "Start here · radar profile"
              : definition.availability === "local-analysis"
              ? "Local coaching"
              : definition.availability === "planned"
                ? "Planned"
                : "Ready"}
          </span>
          <Icon className="project-metric-card__arrow" name="arrow" />
        </button>
      ))}
    </nav>
  );
}

export function ProjectWorkspace({
  route,
  transport,
  navigate,
  coverageProvider = "codex",
}: {
  route: ProjectWorkspaceRoute;
  transport: PromptEnhancerTransport;
  navigate: (route: AppRoute) => void;
  coverageProvider?: Provider;
}) {
  const [sessions, setSessions] = useState<CodexSession[] | null>(null);
  const [projectSessionTotal, setProjectSessionTotal] = useState(0);
  const [projectSessionsTruncated, setProjectSessionsTruncated] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [catalogRetryKey, setCatalogRetryKey] = useState(0);
  const [metrics, setMetrics] = useState<SessionMetric[] | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState("");
  const [metricsRetryKey, setMetricsRetryKey] = useState(0);
  const [qualityRun, setQualityRun] = useState<SessionAnalysisRunResponse | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState("");
  const [qualityNotice, setQualityNotice] = useState<{ sessionId: string; category: string; text: string } | null>(null);
  const [qualityRetryKey, setQualityRetryKey] = useState(0);
  const [metricReadiness, setMetricReadiness] =
    useState<SessionMetricReadinessReport | null>(null);
  const [metricReadinessLoading, setMetricReadinessLoading] = useState(false);
  const [metricReadinessError, setMetricReadinessError] = useState("");
  const [metricReadinessRefreshKey, setMetricReadinessRefreshKey] = useState(0);
  const [coachingProjection, setCoachingProjection] =
    useState<SessionCoachingProjection | null>(null);
  const [coachingLoading, setCoachingLoading] = useState(false);
  const [coachingError, setCoachingError] = useState("");
  const [qualityAggregate, setQualityAggregate] =
    useState<SessionQualityAggregate | null>(null);
  const [qualityAggregateLoading, setQualityAggregateLoading] = useState(false);
  const [qualityAggregateError, setQualityAggregateError] = useState("");
  const [qualityAggregateRetryKey, setQualityAggregateRetryKey] = useState(0);
  const [analysisCapability, setAnalysisCapability] =
    useState<SessionTextAnalysisCapability | null>(null);
  const [providerCompatibility, setProviderCompatibility] =
    useState<ProviderCompatibilityStatus | null>(null);
  const [compatibilityLoading, setCompatibilityLoading] = useState(false);
  const [compactMasthead, setCompactMasthead] = useState(false);
  const [legacyQualityExpanded, setLegacyQualityExpanded] = useState(false);
  const compatibilityRequestGeneration = useRef(0);
  const mastheadSentinelRef = useRef<HTMLSpanElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const observedRouteIdentity = useRef<string | null>(null);
  const pendingFocusRouteIdentity = useRef<string | null>(null);
  const sessionId = selectedSessionId(route);
  const lookupScope = `${route.projectId}/${sessionId ?? ""}`;
  const [resolvedSession, setResolvedSession] = useState<{ scope: string; session: CodexSession; transport: PromptEnhancerTransport } | null>(null);
  const [lookupNext, setLookupNext] = useState<{ scope: string; offset: number } | null>(null);
  const [lookupCursor, setLookupCursor] = useState<{ scope: string; offset: number } | null>(null);
  const [lookupFinished, setLookupFinished] = useState<string | null>(null);
  const [lookupError, setLookupError] = useState("");
  const lookupOffset = lookupCursor?.scope === lookupScope ? lookupCursor.offset : 100;

  useEffect(() => { setLookupCursor(null); }, [lookupScope]);

  useEffect(() => {
    const controller = new AbortController();
    setSessions(null);
    setProjectSessionTotal(0);
    setProjectSessionsTruncated(false);
    setCatalogError("");
    void (async () => {
      try {
        const response = await transport.listProjectSessions(route.projectId, 100, 0, controller.signal);
        if (controller.signal.aborted) return;
        if (!isCompleteProjectSessionPage(response, route.projectId, 100)) {
          setCatalogError("The project-scoped catalog response was inconsistent.");
          return;
        }
        setSessions(response.sessions);
        setProjectSessionTotal(response.total);
        setProjectSessionsTruncated(response.has_more);
      } catch {
        if (!controller.signal.aborted) {
          setCatalogError("The locally indexed sessions could not be loaded.");
        }
      }
    })();
    return () => controller.abort();
  }, [catalogRetryKey, route.projectId, transport]);

  useEffect(() => {
    setResolvedSession(null);
    setLookupNext(null);
    setLookupError("");
    setLookupFinished(null);
    if (!sessionId || !sessions || !projectSessionsTruncated
      || sessions.some((session) => session.session_id === sessionId && session.project_id === route.projectId)) return;
    const controller = new AbortController();
    void (async () => {
      try {
        // Resolve only the explicitly selected session beyond the visible first
        // page. Metadata reads are bounded; project-wide analysis stays capped.
        let offset = lookupOffset;
        const pageBudget = offset === 100 ? 9 : 10;
        const seen = new Set(sessions.map((session) => session.session_id));
        for (let page = 0; page < pageBudget; page += 1) {
          const next = await transport.listProjectSessions(route.projectId, 100, offset, controller.signal);
          if (controller.signal.aborted) return;
          if (!isCompleteProjectSessionPage(next, route.projectId, 100, offset) || next.total !== projectSessionTotal
            || next.sessions.some((session) => seen.has(session.session_id))) {
            setLookupError("The project-scoped catalog changed or was inconsistent. Retry to verify the session's project.");
            return;
          }
          next.sessions.forEach((session) => seen.add(session.session_id));
          const found = next.sessions.find((session) => session.session_id === sessionId);
          if (found) {
            setResolvedSession({ scope: lookupScope, session: found, transport });
            break;
          }
          if (!next.has_more) break;
          offset += next.sessions.length;
          if (page === pageBudget - 1) setLookupNext({ scope: lookupScope, offset });
        }
      } catch {
        if (!controller.signal.aborted) setLookupError("The older session's project membership could not be checked. Retry the metadata lookup.");
      } finally {
        if (!controller.signal.aborted) setLookupFinished(lookupScope);
      }
    })();
    return () => controller.abort();
  }, [lookupOffset, lookupScope, projectSessionTotal, projectSessionsTruncated, route.projectId, sessionId, sessions, transport]);

  const projectSessions = useMemo(
    () =>
      (sessions ?? [])
        .filter((session) => session.project_id === route.projectId)
        .sort(
          (left, right) =>
            new Date(right.started_at).valueOf() - new Date(left.started_at).valueOf(),
        ),
    [route.projectId, sessions],
  );
  const category = selectedCategory(route);
  const currentSession = sessionId
    ? projectSessions.find((session) => session.session_id === sessionId)
      ?? (resolvedSession?.scope === lookupScope && resolvedSession.transport === transport ? resolvedSession.session : undefined)
    : undefined;
  const categoryPlanned = category
    ? metricCategoryDefinition(category).availability === "planned"
    : false;
  const qualityCategory = isQualityProfileCategory(category);
  const routeIdentity = mastheadRouteIdentity(route);
  const workspaceView =
    route.name === "project_overview"
      ? "deck"
      : route.name === "project_sessions"
        ? "sessions"
        : "signals";

  useEffect(() => {
    const sentinel = mastheadSentinelRef.current;
    if (!sentinel || typeof IntersectionObserver === "undefined") {
      setCompactMasthead(false);
      return;
    }
    let active = true;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!active || !entry) return;
        const nextCompact = !entry.isIntersecting;
        setCompactMasthead((current) =>
          current === nextCompact ? current : nextCompact,
        );
      },
      {
        root: null,
        rootMargin: COMPACT_MASTHEAD_ROOT_MARGIN,
        threshold: 0,
      },
    );
    observer.observe(sentinel);
    return () => {
      active = false;
      observer.takeRecords();
      observer.disconnect();
    };
  }, [routeIdentity]);

  useLayoutEffect(() => {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    const hiddenVariant = compactMasthead ? "full" : "compact";
    const visibleVariant = compactMasthead ? "compact" : "full";
    const hiddenNavigation = workspace.querySelector<HTMLElement>(
      `[data-project-section-nav="${hiddenVariant}"]`,
    );
    if (!hiddenNavigation?.contains(document.activeElement)) return;
    workspace
      .querySelector<HTMLElement>(
        `[data-project-section-nav="${visibleVariant}"] [data-section="${projectSection(route)}"]`,
      )
      ?.focus({ preventScroll: true });
  }, [compactMasthead, route, routeIdentity]);

  useEffect(() => {
    if (!sessionId || !currentSession || !qualityCategory) {
      setAnalysisCapability(null);
      return;
    }
    const controller = new AbortController();
    setAnalysisCapability(null);
    transport
      .getSessionTextAnalysisCapability(controller.signal)
      .then(async (capability) => {
        if (controller.signal.aborted) return;
        if (!capability.available) {
          setAnalysisCapability(capability);
          return;
        }
        let status: unknown;
        try {
          status = await transport.getCodexLocalSourceStatus(controller.signal);
        } catch {
          if (!controller.signal.aborted) {
            setAnalysisCapability({
              available: false,
              reason_code: "consent_status_invalid",
              data_tier: null,
              content_persistence: false,
              network_inference: false,
              raw_transcripts: false,
            });
          }
          return;
        }
        if (controller.signal.aborted) return;
        const consentActive = activeRedactedConsent(status);
        if (consentActive === null) {
          setAnalysisCapability({
            available: false,
            reason_code: "consent_status_invalid",
            data_tier: null,
            content_persistence: false,
            network_inference: false,
            raw_transcripts: false,
          });
        } else if (!consentActive) {
          setAnalysisCapability({
            available: false,
            reason_code: "redacted_content_consent_required",
            data_tier: null,
            content_persistence: false,
            network_inference: false,
            raw_transcripts: false,
          });
        } else {
          setAnalysisCapability(capability);
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setAnalysisCapability({
          available: false,
          reason_code: "capability_response_invalid",
          data_tier: null,
          content_persistence: false,
          network_inference: false,
          raw_transcripts: false,
        });
      });
    return () => controller.abort();
  }, [currentSession, qualityCategory, sessionId, transport]);

  useEffect(() => {
    if (!sessionId || !currentSession || !qualityCategory) {
      compatibilityRequestGeneration.current += 1;
      setProviderCompatibility(null);
      setCompatibilityLoading(false);
      return;
    }
    const loadCompatibility = transport.getProviderCompatibility;
    if (!loadCompatibility) {
      compatibilityRequestGeneration.current += 1;
      setProviderCompatibility(null);
      setCompatibilityLoading(false);
      return;
    }
    const controller = new AbortController();
    const requestGeneration = ++compatibilityRequestGeneration.current;
    setProviderCompatibility(null);
    setCompatibilityLoading(true);
    loadCompatibility(currentSession.provider, controller.signal)
      .then((status) => {
        if (
          !controller.signal.aborted &&
          compatibilityRequestGeneration.current === requestGeneration
        ) {
          setProviderCompatibility(status);
        }
      })
      .catch(() => {
        if (
          !controller.signal.aborted &&
          compatibilityRequestGeneration.current === requestGeneration
        ) {
          setProviderCompatibility(null);
        }
      })
      .finally(() => {
        if (compatibilityRequestGeneration.current === requestGeneration) {
          setCompatibilityLoading(false);
        }
      });
    return () => {
      controller.abort();
      compatibilityRequestGeneration.current += 1;
    };
  }, [currentSession, qualityCategory, sessionId, transport]);

  async function checkProviderCompatibility(signal: AbortSignal) {
    if (!currentSession || !transport.checkProviderCompatibility) {
      throw new Error("Compatibility check is unavailable.");
    }
    const requestGeneration = ++compatibilityRequestGeneration.current;
    setCompatibilityLoading(true);
    setProviderCompatibility(null);
    try {
      const status = await transport.checkProviderCompatibility(
        currentSession.provider,
        signal,
      );
      if (
        !signal.aborted &&
        compatibilityRequestGeneration.current === requestGeneration
      ) {
        setProviderCompatibility(status);
      }
    } finally {
      if (compatibilityRequestGeneration.current === requestGeneration) {
        setCompatibilityLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!sessionId || !currentSession || categoryPlanned || qualityCategory) {
      setMetrics(null);
      setMetricsError("");
      setMetricsLoading(false);
      return;
    }
    const controller = new AbortController();
    setMetrics(null);
    setMetricsError("");
    setMetricsLoading(true);
    transport
      .getSessionMetrics(sessionId, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        if (response.session_id !== sessionId) {
          setMetricsError("The stored metric response did not match the selected session.");
          return;
        }
        setMetrics(response.metrics);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setMetricsError("Stored metrics for this session could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMetricsLoading(false);
      });
    return () => controller.abort();
  }, [categoryPlanned, currentSession, metricsRetryKey, qualityCategory, sessionId, transport]);

  useEffect(() => {
    if (!sessionId || !currentSession || !qualityCategory || !legacyQualityExpanded) {
      setQualityRun(null);
      setQualityError("");
      setQualityLoading(false);
      return;
    }
    const controller = new AbortController();
    setQualityRun(null);
    setQualityError("");
    setQualityLoading(true);
    transport
      .getLatestSessionQualityAnalysis(sessionId, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setQualityRun(response);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status =
          typeof error === "object" &&
          error !== null &&
          "status" in error &&
          typeof error.status === "number"
            ? error.status
            : null;
        if (status === 404) {
          setQualityRun(null);
          return;
        }
        setQualityError("The latest immutable quality run could not be loaded.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setQualityLoading(false);
      });
    return () => controller.abort();
  }, [currentSession, legacyQualityExpanded, qualityCategory, qualityRetryKey, sessionId, transport]);

  useEffect(() => {
    if (!sessionId || !currentSession || !qualityCategory || !legacyQualityExpanded) {
      setMetricReadiness(null);
      setMetricReadinessError("");
      setMetricReadinessLoading(false);
      return;
    }
    const controller = new AbortController();
    setMetricReadiness(null);
    setMetricReadinessError("");
    setMetricReadinessLoading(true);
    transport
      .getSessionMetricReadiness(sessionId, "coaching_profile_v1", controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        if (
          response.session_id !== sessionId ||
          response.provider !== currentSession.provider ||
          response.preset_id !== "coaching_profile_v1"
        ) {
          setMetricReadinessError(
            "Metric readiness did not match the selected session and was ignored.",
          );
          return;
        }
        setMetricReadiness(response);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setMetricReadinessError(
            "Content-free metric readiness could not be loaded.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMetricReadinessLoading(false);
      });
    return () => controller.abort();
  }, [
    currentSession,
    legacyQualityExpanded,
    metricReadinessRefreshKey,
    qualityCategory,
    qualityRetryKey,
    sessionId,
    transport,
  ]);

  useEffect(() => {
    const runId = qualityRun?.run.run_id;
    if (!sessionId || !currentSession || !qualityCategory || !legacyQualityExpanded || !runId) {
      setCoachingProjection(null);
      setCoachingError("");
      setCoachingLoading(false);
      return;
    }
    if (!transport.getSessionCoachingSummary) {
      setCoachingProjection(null);
      setCoachingError("Restart the updated local app to load the coaching summary.");
      setCoachingLoading(false);
      return;
    }
    const controller = new AbortController();
    setCoachingProjection(null);
    setCoachingError("");
    setCoachingLoading(true);
    transport
      .getSessionCoachingSummary(runId, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        if (createCoachingLoopViewModel(response) === null) {
          setCoachingError("The coaching summary did not match the supported content-free contract.");
          return;
        }
        setCoachingProjection(response);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status =
          typeof error === "object" &&
          error !== null &&
          "status" in error &&
          typeof error.status === "number"
            ? error.status
            : null;
        setCoachingError(
          status === 409
            ? "Run the current Coaching v1 analysis to create a compatible summary."
            : "The content-free coaching summary could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setCoachingLoading(false);
      });
    return () => controller.abort();
  }, [currentSession, legacyQualityExpanded, qualityCategory, qualityRun, sessionId, transport]);

  useEffect(() => {
    if (
      route.name !== "project_metrics" ||
      !qualityCategory ||
      projectSessions.length === 0 ||
      projectSessionsTruncated
    ) {
      setQualityAggregate(null);
      setQualityAggregateError("");
      setQualityAggregateLoading(false);
      return;
    }
    const controller = new AbortController();
    setQualityAggregate(null);
    setQualityAggregateError("");
    setQualityAggregateLoading(true);
    transport
      .aggregateSessionQuality(
        { session_ids: projectSessions.map((session) => session.session_id) },
        controller.signal,
      )
      .then((response) => {
        if (!controller.signal.aborted) setQualityAggregate(response);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setQualityAggregateError(
            "The selected project quality profile could not be aggregated.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setQualityAggregateLoading(false);
      });
    return () => controller.abort();
  }, [
    projectSessions,
    projectSessionsTruncated,
    qualityAggregateRetryKey,
    qualityCategory,
    route.name,
    transport,
  ]);

  const visibleMetrics = useMemo(
    () =>
      category && metrics
        ? metrics.filter((metric) => metricCategoryFor(metric) === category)
        : [],
    [category, metrics],
  );
  const visibleProjectName = projectLabel(projectSessions);
  const completeSessions = projectSessions.filter(
    (session) => session.events_complete,
  ).length;
  const qualityProfileOwnsTitle =
    qualityCategory &&
    route.name === "project_metrics" &&
    sessions !== null &&
    projectSessions.length > 0 &&
    !projectSessionsTruncated &&
    !qualityAggregateLoading &&
    !qualityAggregateError;
  useEffect(() => {
    if (sessions === null) return;
    if (qualityProfileOwnsTitle) return;
    if (route.name === "project_overview" || route.name === "project_sessions") {
      const viewName = route.name === "project_overview" ? "Metric deck" : "Sessions";
      document.title = `${viewName} · ${visibleProjectName} · Prompt Enhancer`;
    } else if (category) {
      document.title = `${CATEGORY_SIGNAL_LABELS[category]} · ${visibleProjectName} · Prompt Enhancer`;
    }
  }, [
    category,
    qualityProfileOwnsTitle,
    route.name,
    routeIdentity,
    sessions,
    visibleProjectName,
  ]);

  useLayoutEffect(() => {
    const previousRouteIdentity = observedRouteIdentity.current;
    observedRouteIdentity.current = routeIdentity;
    if (previousRouteIdentity !== null && previousRouteIdentity !== routeIdentity) {
      pendingFocusRouteIdentity.current = routeIdentity;
    }
    if (pendingFocusRouteIdentity.current !== routeIdentity || sessions === null) return;
    if (qualityProfileOwnsTitle) {
      pendingFocusRouteIdentity.current = null;
      return;
    }

    const headingId =
      route.name === "project_overview"
        ? "project-overview-title"
        : route.name === "project_sessions"
          ? "session-index-title"
          : route.name === "project_metrics"
            ? "metric-scope-title"
            : qualityCategory
              ? "model-ensemble-title"
            : categoryPlanned
              ? "metric-plan-title"
              : "session-metrics-title";
    const heading = workspaceRef.current?.querySelector<HTMLElement>(`#${headingId}`);
    if (!heading) return;
    heading.focus();
    pendingFocusRouteIdentity.current = null;
  }, [
    categoryPlanned,
    qualityCategory,
    qualityProfileOwnsTitle,
    route.name,
    routeIdentity,
    sessions,
  ]);
  useEffect(() => setLegacyQualityExpanded(false), [routeIdentity]);
  const coachingModel = useMemo(
    () => createCoachingLoopViewModel(coachingProjection),
    [coachingProjection],
  );

  function openCategory(nextCategory: MetricCategory) {
    if (sessionId) {
      navigate({
        name: "session_metrics",
        projectId: route.projectId,
        sessionId,
        category: nextCategory,
      });
      return;
    }
    if (!isQualityProfileCategory(nextCategory) && projectSessions[0]) {
      navigate({
        name: "session_metrics",
        projectId: route.projectId,
        sessionId: projectSessions[0].session_id,
        category: nextCategory,
      });
      return;
    }
    navigate({
      name: "project_metrics",
      projectId: route.projectId,
      category: nextCategory,
    });
  }

  function focusSession(nextSessionId: string) {
    if (!nextSessionId) return;
    navigate({
      name: "session_metrics",
      projectId: route.projectId,
      sessionId: nextSessionId,
      category: category ?? "prompt-quality",
    });
  }

  async function prepareQualityPreview(
    requestedSessionId: string,
    request: Parameters<PromptEnhancerTransport["prepareSessionQualityAnalysisPreview"]>[1],
    signal: AbortSignal,
  ) {
    if (!sessionId || requestedSessionId !== sessionId) {
      throw new Error("Selected session is unavailable.");
    }
    setQualityNotice(null);
    return transport.prepareSessionQualityAnalysisPreview(
      requestedSessionId,
      request,
      signal,
    );
  }

  async function approveQualityPreview(
    requestedSessionId: string,
    previewId: string,
    request: Parameters<PromptEnhancerTransport["approveSessionQualityAnalysisPreview"]>[1],
    idempotencyKey: string,
    signal: AbortSignal,
  ) {
    if (!sessionId || requestedSessionId !== sessionId) {
      throw new Error("Selected session is unavailable.");
    }
    if (request.expected_binding.session_id !== requestedSessionId) {
      throw new Error("Preview session is unavailable.");
    }
    const outcome = await transport.approveSessionQualityAnalysisPreview(
      previewId,
      request,
      idempotencyKey,
      signal,
    );
    if (signal.aborted) return;
    const detail = await transport.getSessionQualityAnalysisRun(
      outcome.run_id,
      signal,
    );
    if (signal.aborted) return;
    const nextProfile = category
      ? createQualityMetricProfile(category, detail, sessionId)
      : null;
    if (
      outcome.status !== "completed" ||
      outcome.analysis_profile_key !== "coaching_profile" ||
      outcome.analysis_profile_version !== 1 ||
      detail.run.status !== "completed" ||
      detail.run.run_id !== outcome.run_id ||
      detail.run.session_id !== requestedSessionId ||
      nextProfile?.latest.integrity !== "coherent"
    ) {
      throw new Error("The immutable result is not complete.");
    }
    setQualityRun(detail);
    setQualityError("");
    setQualityNotice({ sessionId: requestedSessionId, category: category ?? "", text: "Analysis completed and stored locally. The latest metric profile is now shown." });
    setMetricReadinessRefreshKey((value) => value + 1);
  }

  return (
    <section
      aria-labelledby="project-workspace-title"
      className="project-workspace"
      data-masthead={compactMasthead ? "compact" : "full"}
      ref={workspaceRef}
    >
      {qualityNotice && qualityNotice.sessionId === sessionId && qualityNotice.category === category && <p className="workspace-panel__description" role="status">{qualityNotice.text}</p>}
      <div
        aria-hidden={compactMasthead ? undefined : true}
        className="project-workspace__masthead-anchor"
        data-visible={compactMasthead ? "true" : "false"}
      >
        <div className="project-workspace__compact-masthead">
          <div className="project-workspace__compact-identity">
            <span className="project-workspace__compact-icon">
              <Icon name="layers" />
            </span>
            <strong>{sessions === null ? "Loading project..." : visibleProjectName}</strong>
          </div>
          <ProjectSectionNavigation
            enabled={compactMasthead}
            navigate={navigate}
            route={route}
            sessionTotal={sessions === null ? null : projectSessionTotal}
            variant="compact"
          />
        </div>
      </div>
      <header className="project-workspace__header route-header route-header--workspace">
        <span
          aria-hidden="true"
          className="project-workspace__masthead-sentinel"
          ref={mastheadSentinelRef}
        />
        <div className="project-workspace__topbar">
          <button
            aria-label="Back to all projects"
            className="project-workspace__back"
            onClick={() => navigate({ name: "projects" })}
            type="button"
          >
            <Icon name="chevron" />
            <span>Projects</span>
          </button>
          <div className="project-workspace__identity">
            <p className="eyebrow">Project</p>
            <h1 id="project-workspace-title">
              {sessions === null ? "Loading project..." : visibleProjectName}
            </h1>
            <p>
              {sessions === null
                ? "Reading the local index..."
                : `${projectSessionTotal} indexed session${projectSessionTotal === 1 ? "" : "s"}`}
            </p>
          </div>
          <ProjectSectionNavigation
            enabled={!compactMasthead}
            navigate={navigate}
            route={route}
            sessionTotal={sessions === null ? null : projectSessionTotal}
            variant="full"
          />
        </div>
        {category && (
          <div className="project-workspace__context" aria-label="Current signals">
            <span className="project-workspace__context-icon">
              <Icon name={CATEGORY_ICONS[category]} />
            </span>
            <span className="project-workspace__context-copy">
              <small>Signals</small>
              <strong>{CATEGORY_SIGNAL_LABELS[category]}</strong>
            </span>
            {currentSession ? (
              <button
                className="project-workspace__context-session"
                onClick={() =>
                  navigate({ name: "project_sessions", projectId: route.projectId })
                }
                type="button"
              >
                <span>
                  <small>Session</small>
                  <strong>
                    {visibleLabel(currentSession.session_display_name, "Unnamed session")}
                  </strong>
                  <ProviderBadge compact provider={currentSession.provider} />
                </span>
                <span>Change</span>
                <Icon name="arrow" />
              </button>
            ) : (
              <span className="project-workspace__context-scope">Project rollup</span>
            )}
          </div>
        )}
      </header>

      <div
        className="project-workspace__view"
        data-workspace-view={workspaceView}
        key={routeIdentity}
      >
      {catalogError ? (
        <ErrorState
          message={catalogError}
          onRetry={() => setCatalogRetryKey((value) => value + 1)}
        />
      ) : sessions === null ? (
        <LoadingState label="Loading this project's stored session index..." />
      ) : projectSessions.length === 0 ? (
        <ErrorState
          actionLabel="Back to projects"
          message="This project is not present in the current bounded local index."
          onRetry={() => navigate({ name: "projects" })}
        />
      ) : route.name === "project_overview" ? (
        <section className="project-overview" aria-labelledby="project-overview-title">
          <div className="project-overview__heading">
            <div>
              <p className="eyebrow">Metric deck</p>
              <h2 id="project-overview-title" tabIndex={-1}>What do you want to review?</h2>
              <p>
                Start with Prompt quality for the visual radar, or open another
                focused review. No setup is required.
              </p>
            </div>
            <div className="project-overview__actions">
              <button
                className="button button--ghost"
                onClick={() => { openLiveWindow({ name: "live", projectId: route.projectId }); }}
                title="Opens a small window that follows this project and refreshes itself; open one per project or session"
                type="button"
              >
                <Icon name="layers" />
                <span>Open live window</span>
              </button>
            </div>
            <dl className="project-overview__facts" aria-label="Indexed scope">
              <div><dt>Sessions</dt><dd>{projectSessionTotal}</dd></div>
              <div><dt>Complete</dt><dd>{completeSessions}</dd></div>
              <div><dt>Partial</dt><dd>{projectSessions.length - completeSessions}</dd></div>
            </dl>
          </div>
          <MetricCoveragePanel
            projectId={route.projectId}
            provider={coverageProvider}
            transport={transport}
          />
          <ProjectTimelinePane
            key={`project-timeline-${route.projectId}`}
            onOpenSession={(openedSessionId) =>
              navigate({
                name: "session_metrics",
                projectId: route.projectId,
                sessionId: openedSessionId,
                category: "prompt-quality",
              })}
            projectId={route.projectId}
            transport={transport}
          />
          <MetricCategoryDeck onOpen={openCategory} />
          {projectSessionsTruncated && (
            <div className="snapshot-boundary snapshot-boundary--partial" role="note">
              <strong>Project scope exceeds the 100-session review boundary</strong>
              <p>
                This page shows the newest 100 indexed sessions. Project-wide analysis
                stays blocked until a smaller explicit selection or another page is chosen.
              </p>
            </div>
          )}
        </section>
      ) : route.name === "project_sessions" ? (
        <section className="project-session-index" aria-labelledby="session-index-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Indexed scope</p>
              <h2 id="session-index-title" tabIndex={-1}>Sessions</h2>
              <p>Choose a session to open its coaching dashboard.</p>
            </div>
          </div>
          <ul className="project-session-index__list">
            {projectSessions.map((session) => (
              <li key={session.session_id}>
                <button
                  aria-label={`Open ${visibleLabel(session.session_display_name, "Unnamed session")}`}
                  className="project-session-card"
                  onClick={() => focusSession(session.session_id)}
                  type="button"
                >
                  <span className="project-session-card__icon">
                    <Icon name={session.events_complete ? "check" : "clock"} />
                  </span>
                  <span className="project-session-card__copy">
                    <strong>{visibleLabel(session.session_display_name, "Unnamed session")}</strong>
                    <small>{safeTimestamp(session.started_at)}</small>
                  </span>
                  <ProviderBadge compact provider={session.provider} />
                  <span className={`status-pill${session.events_complete ? " status-pill--info" : ""}`}>
                    {session.events_complete ? "Complete" : "Partial"}
                  </span>
                  <Icon className="project-session-card__arrow" name="arrow" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : route.name === "project_metrics" && category && qualityCategory ? (
        projectSessionsTruncated ? (
          <section className="metric-scope-state" aria-labelledby="metric-scope-title">
            <span className="metric-scope-state__icon"><Icon name="activity" /></span>
            <div>
              <p className="eyebrow">Bounded selection required</p>
              <h2 id="metric-scope-title" tabIndex={-1}>Choose at most 100 sessions</h2>
              <p>
                This project contains {projectSessionTotal} indexed sessions. A
                project-wide profile is blocked because the current review boundary
                cannot silently omit older sessions.
              </p>
            </div>
          </section>
        ) : qualityAggregateLoading ? (
          <LoadingState label="Aggregating compatible immutable session profiles..." />
        ) : qualityAggregateError ? (
          <ErrorState
            message={qualityAggregateError}
            onRetry={() => setQualityAggregateRetryKey((value) => value + 1)}
          />
        ) : (
          <>
            {qualityAggregate &&
              qualityAggregate.missing_run_count > 0 &&
              projectSessions.length > 0 && (
                <section className="metric-scope-state" aria-label="Coaching analysis required">
                  <span className="metric-scope-state__icon"><Icon name="activity" /></span>
                  <div>
                    <p className="eyebrow">Coaching v1 coverage</p>
                    <h2>
                      {qualityAggregate.missing_run_count} of {qualityAggregate.selected_session_count} sessions need analysis
                    </h2>
                    <p>
                      Older metric packs remain preserved but are not mixed into this profile.
                      Open a session and run the one-click local analysis to add comparable results.
                    </p>
                    <button
                      className="button button--primary button--compact"
                      onClick={() => focusSession(projectSessions[0].session_id)}
                      type="button"
                    >
                      Open a session to analyze
                    </button>
                  </div>
                </section>
              )}
            <QualityProfileView
              profile={createAggregateQualityMetricProfile(
                category,
                qualityAggregate,
              )!}
              primaryContent={
                <section className="project-quality-rollup" aria-labelledby="project-quality-rollup-title">
                  <div>
                    <p className="eyebrow">Project control deck</p>
                    <h3 id="project-quality-rollup-title">Comparable session coverage</h3>
                    <p>
                      Project-level coaching is not synthesized across different task
                      types. Open a session for one evidence-bounded coaching loop.
                    </p>
                  </div>
                  <dl>
                    <div>
                      <dt>Selected</dt>
                      <dd>{qualityAggregate?.selected_session_count ?? projectSessions.length}</dd>
                    </div>
                    <div>
                      <dt>Compatible runs</dt>
                      <dd>{qualityAggregate?.completed_run_count ?? 0}</dd>
                    </div>
                    <div>
                      <dt>Need analysis</dt>
                      <dd>{qualityAggregate?.missing_run_count ?? projectSessions.length}</dd>
                    </div>
                  </dl>
                  <button
                    className="button button--primary button--compact"
                    onClick={() => focusSession(projectSessions[0].session_id)}
                    type="button"
                  >
                    Open newest session
                  </button>
                </section>
              }
            />
          </>
        )
      ) : route.name === "project_metrics" && category ? (
        <ProjectMetricScopeState category={category} />
      ) : !currentSession || !category ? (
        lookupError ? <ErrorState message={lookupError} onRetry={() => { setLookupCursor(null); setCatalogRetryKey((value) => value + 1); }} />
        : projectSessionsTruncated && lookupFinished !== lookupScope ? <LoadingState label="Finding the selected session in older indexed pages..." />
        : lookupNext?.scope === lookupScope ? (
          <section className="metric-scope-state" aria-label="Older session lookup">
            <div>
              <h2>The selected session is beyond the pages checked so far</h2>
              <p>More indexed sessions remain. Only project metadata is searched; no analysis is started.</p>
              <button className="button button--secondary" onClick={() => setLookupCursor(lookupNext)} type="button">
                Search next 1,000 sessions
              </button>
            </div>
          </section>
        ) : (
          <ErrorState
            actionLabel="Open project sessions"
            message="The selected session is not part of this indexed project."
            onRetry={() => navigate({ name: "project_sessions", projectId: route.projectId })}
          />
        )
      ) : qualityCategory ? (
        <>
          <SessionRadarCard
            key={`radar-${currentSession.session_id}`}
            sessionId={currentSession.session_id}
            transport={transport}
          />
          <p className="session-live-actions session-live-actions--row">
            <button
              className="button button--primary"
              onClick={() => { navigate({ name: "prompt_checks", sessionId: currentSession.session_id }); }}
              title="Write the next prompt for this session with the model seeing the conversation so far"
              type="button"
            >
              Draft the next prompt
            </button>
            <button
              className="button button--ghost"
              onClick={() => { openLiveWindow({ name: "live", projectId: route.projectId, sessionId: currentSession.session_id }); }}
              title="Opens a small window that follows this session and refreshes itself"
              type="button"
            >
              <Icon name="layers" />
              <span>Live window</span>
            </button>
          </p>
          <div className="project-canonical-metrics">
            <ModelEnsemblePanel
              analysisCapability={analysisCapability}
              category={category}
              compatibilityLoading={compatibilityLoading}
              key={`model-ensemble-${currentSession.session_id}-${category}`}
              projectId={route.projectId}
              providerCompatibility={providerCompatibility}
              sessionId={currentSession.session_id}
              transport={transport}
            />
          </div>
          <SessionTimelinePane
            key={`timeline-${currentSession.session_id}`}
            sessionId={currentSession.session_id}
            transport={transport}
          />
          <details className="session-fold" key={`judge-fold-${currentSession.session_id}`}>
            <summary>Model judge - what the local model thinks (experimental, not a metric)</summary>
            <ModelJudgePane
              key={`judge-${currentSession.session_id}`}
              sessionId={currentSession.session_id}
              transport={transport}
            />
          </details>
          <details className="session-fold" key={`reader-fold-${currentSession.session_id}`}>
            <summary>Read this session - the transcript, on demand</summary>
            <SessionTranscriptPane
              key={`reader-${currentSession.session_id}`}
              sessionId={currentSession.session_id}
              transport={transport}
            />
          </details>
          <details
            className="project-model-ensemble project-model-ensemble--legacy"
            onToggle={(event) => setLegacyQualityExpanded(event.currentTarget.open)}
          >
            <summary>
              <span>
                <Icon name="activity" />
                <span>
                  <strong>Legacy coaching profile</strong>
                  <small>Prior v1 candidates · not the canonical measurement snapshot</small>
                </span>
              </span>
              <span>Optional legacy view</span>
            </summary>
            {legacyQualityExpanded ? qualityLoading ? (
              <LoadingState label="Loading the legacy qualitative profile..." />
            ) : qualityError ? (
              <ErrorState
                message={qualityError}
                onRetry={() => setQualityRetryKey((value) => value + 1)}
              />
            ) : (
              <QualityProfileView
                analysisCapability={analysisCapability}
                compatibilityLoading={compatibilityLoading}
                key={currentSession.session_id}
                onCheckProviderCompatibility={
                  transport.checkProviderCompatibility
                    ? checkProviderCompatibility
                    : undefined
                }
                onAnalyzeLocally={{
                  exactSessionId: currentSession.session_id,
                  preparePreview: prepareQualityPreview,
                  approvePreview: approveQualityPreview,
                }}
                onRetryMetricReadiness={() =>
                  setMetricReadinessRefreshKey((value) => value + 1)
                }
                metricReadiness={metricReadiness}
                metricReadinessError={metricReadinessError}
                metricReadinessLoading={metricReadinessLoading}
                manageDocumentContext={false}
                providerCompatibility={providerCompatibility}
                profile={createQualityMetricProfile(
                  category,
                  qualityRun,
                  currentSession.session_id,
                )!}
                sessionDescriptor={`${visibleLabel(currentSession.session_display_name, "Unnamed session")} · ${safeTimestamp(currentSession.started_at)} · ${currentSession.session_id.slice(0, 8)}`}
                primaryContent={
                  coachingLoading ? (
                    <section className="project-coaching-state" aria-live="polite">
                      <span className="project-coaching-state__icon"><Icon name="activity" /></span>
                      <div>
                        <p className="eyebrow">Coaching loop</p>
                        <h3>Building the content-free coaching summary</h3>
                        <p>No provider content is read by this summary step.</p>
                      </div>
                    </section>
                  ) : coachingModel ? (
                    <CoachingLoop model={coachingModel} />
                  ) : (
                    <section className="project-coaching-state" role={coachingError ? "alert" : "note"}>
                      <span className="project-coaching-state__icon"><Icon name="activity" /></span>
                      <div>
                        <p className="eyebrow">Coaching loop</p>
                        <h3>No evidence-bounded coaching summary yet</h3>
                        <p>
                          {coachingError ||
                            "Use the legacy analyzer once. The summary will abstain unless this session belongs to one reviewed task."}
                        </p>
                      </div>
                    </section>
                  )
                }
              />
            ) : null}
          </details>
          <details className="project-model-lab">
              <summary>
                <span>
                  <Icon name="layers" />
                  <span>
                    <strong>Local model lab</strong>
                    <small>Optional neural-link experiment—not a coaching score</small>
                  </span>
                </span>
                <span>Open experiment</span>
              </summary>
              <ModelLinkExperimentPanel
                analysisCapability={analysisCapability}
                compatibilityLoading={compatibilityLoading}
                key={`model-link-${currentSession.session_id}`}
                providerCompatibility={providerCompatibility}
                sessionId={currentSession.session_id}
                transport={transport}
              />
          </details>
        </>
      ) : categoryPlanned ? (
        <PlannedCategoryState category={category} />
      ) : (
        <section className="project-session-metrics" aria-labelledby="session-metrics-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{metricCategoryDefinition(category).label}</p>
              <h2 id="session-metrics-title" tabIndex={-1}>
                {visibleLabel(currentSession.session_display_name, "Unnamed session")}
              </h2>
              <p>{metricCategoryDefinition(category).question}</p>
            </div>
          </div>
          <SessionRadarCard
            key={`radar-${currentSession.session_id}-${category}`}
            sessionId={currentSession.session_id}
            transport={transport}
          />
          {metricsLoading ? (
            <LoadingState label="Loading one stored session metric response..." />
          ) : metricsError ? (
            <ErrorState
              message={metricsError}
              onRetry={() => setMetricsRetryKey((value) => value + 1)}
            />
          ) : metrics === null ? null : (
            <>
              <MetricSnapshotBoundary metrics={metrics} session={currentSession} />
              {visibleMetrics.length === 0 ? (
                <div className="no-analysis">
                  <span><Icon name="activity" /></span>
                  <div>
                    <h3>No stored metrics in this category</h3>
                    <p>
                      This is an unavailable observation, not a zero. Run an explicit
                      bounded analysis if this category is supported by the current pack.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="local-metric-grid">
                  {visibleMetrics.map((metric) => (
                    <SessionMetricCard
                      key={`${metric.key}@${metric.version}`}
                      metric={metric}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      )}
      </div>
    </section>
  );
}
