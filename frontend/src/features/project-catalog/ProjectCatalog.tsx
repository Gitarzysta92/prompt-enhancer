import { useEffect, useMemo, useRef, useState } from "react";
import { isLocalProvider } from "../../shared/api/contracts";
import { ProviderBadge, providersOf } from "../../shared/ui/ProviderBadge";
import type {
  CodexSession,
  PromptEnhancerTransport,
  Provider,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { isPseudonym } from "../../shared/platform/platform";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { Icon } from "../../shared/ui/Icon";
import { openLiveWindow } from "../live-window/LiveMiniWindow";
import { MetricCoveragePanel } from "../metric-coverage";
import {
  ProjectComparison,
  resolveProjectComparison,
  type ResolvedProjectComparison,
} from "./ProjectComparison";

type ProjectSort = "recent" | "name" | "sessions";

const PROJECT_RENDER_PAGE = 30;

interface ProjectCatalogItem {
  projectId: string;
  displayName: string;
  sessions: CodexSession[];
  latestStartedAt: string | null;
  completeSessionCount: number;
  /** Distinct providers that contributed sessions, in stable display order. */
  providers: string[];
}

const CATALOG_SESSION_KEYS = [
  "adapter_version",
  "ended_at",
  "events_complete",
  "installation_id",
  "project_display_name",
  "project_display_name_origin",
  "project_id",
  "project_manual_label_revision",
  "provider",
  "provider_version",
  "session_display_name",
  "session_display_name_origin",
  "session_id",
  "session_manual_label_revision",
  "source_schema_version",
  "started_at",
  "terminal_state",
] as const;
const SAFE_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const RFC3339_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/;
const SESSION_STATES = new Set([
  "completed",
  "interrupted",
  "failed",
  "blocked",
  "abandoned",
  "unknown",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => actual.includes(key));
}

function safeNullableLabel(
  value: unknown,
  maxLength: number,
): value is string | null {
  return (
    value === null ||
    (typeof value === "string" &&
      value.length >= 1 &&
      value.length <= maxLength &&
      !/[\u0000-\u001f\u007f]/.test(value))
  );
}

function safeNullableVersion(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && SAFE_VERSION.test(value));
}

function safeDate(value: unknown, nullable = false): boolean {
  if (nullable && value === null) return true;
  if (typeof value !== "string") return false;
  const match = RFC3339_DATE_TIME.exec(value);
  if (match === null) return false;
  const [
    ,
    yearText,
    monthText,
    dayText,
    hourText,
    minuteText,
    secondText,
    zone,
    offsetHourText,
    offsetMinuteText,
  ] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const offsetHour = zone === "Z" ? 0 : Number(offsetHourText);
  const offsetMinute = zone === "Z" ? 0 : Number(offsetMinuteText);
  const maxDay =
    year >= 1 && month >= 1 && month <= 12
      ? new Date(Date.UTC(year, month, 0)).getUTCDate()
      : 0;
  return (
    day >= 1 &&
    day <= maxDay &&
    hour <= 23 &&
    minute <= 59 &&
    second <= 59 &&
    offsetHour <= 23 &&
    offsetMinute <= 59 &&
    !Number.isNaN(new Date(value).valueOf())
  );
}

function safeCatalogSession(value: unknown): value is CodexSession {
  if (!isRecord(value) || !hasExactKeys(value, CATALOG_SESSION_KEYS)) return false;
  const origins = new Set(["provider", "manual", "unknown"]);
  return (
    isLocalProvider(value.provider) &&
    isPseudonym(value.installation_id as string) &&
    isPseudonym(value.project_id as string) &&
    isPseudonym(value.session_id as string) &&
    safeNullableLabel(value.project_display_name, 120) &&
    safeNullableLabel(value.session_display_name, 160) &&
    origins.has(value.project_display_name_origin as string) &&
    origins.has(value.session_display_name_origin as string) &&
    Number.isSafeInteger(value.project_manual_label_revision) &&
    (value.project_manual_label_revision as number) >= 0 &&
    Number.isSafeInteger(value.session_manual_label_revision) &&
    (value.session_manual_label_revision as number) >= 0 &&
    safeNullableVersion(value.provider_version) &&
    typeof value.adapter_version === "string" &&
    SAFE_VERSION.test(value.adapter_version) &&
    safeNullableVersion(value.source_schema_version) &&
    safeDate(value.started_at) &&
    safeDate(value.ended_at, true) &&
    (value.terminal_state === null ||
      SESSION_STATES.has(value.terminal_state as string)) &&
    typeof value.events_complete === "boolean"
  );
}

function safeCatalogResponse(value: unknown): CodexSession[] | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["sessions", "limit", "offset"]) ||
    value.limit !== 100 ||
    value.offset !== 0 ||
    !Array.isArray(value.sessions) ||
    value.sessions.length > 100 ||
    !value.sessions.every(safeCatalogSession)
  ) {
    return null;
  }
  return value.sessions;
}

function visibleLabel(value: string | null | undefined, fallback: string): string {
  return value?.trim() || fallback;
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

function timestampValue(value: string | null): number {
  if (!value) return Number.NEGATIVE_INFINITY;
  const timestamp = new Date(value).valueOf();
  return Number.isNaN(timestamp) ? Number.NEGATIVE_INFINITY : timestamp;
}

function visibleDate(value: string | null): string {
  const timestamp = timestampValue(value);
  if (!Number.isFinite(timestamp)) return "Latest activity unknown";
  return `Latest ${new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(timestamp)}`;
}

function buildCatalog(sessions: readonly CodexSession[]): ProjectCatalogItem[] {
  const grouped = new Map<string, CodexSession[]>();
  for (const session of sessions) {
    if (!isPseudonym(session.project_id) || !isPseudonym(session.session_id)) continue;
    const group = grouped.get(session.project_id) ?? [];
    group.push(session);
    grouped.set(session.project_id, group);
  }

  return [...grouped.entries()].map(([projectId, projectSessions]) => {
    const latestStartedAt = projectSessions.reduce<string | null>(
      (latest, session) =>
        timestampValue(session.started_at) > timestampValue(latest)
          ? session.started_at
          : latest,
      null,
    );
    return {
      projectId,
      displayName: projectLabel(projectSessions),
      sessions: projectSessions,
      latestStartedAt,
      completeSessionCount: projectSessions.filter((session) => session.events_complete)
        .length,
      providers: providersOf(projectSessions),
    };
  });
}

export function ProjectCatalog({
  transport,
  navigate,
  coverageProvider = "codex",
}: {
  transport: PromptEnhancerTransport;
  navigate: (route: AppRoute) => void;
  coverageProvider?: Provider;
}) {
  const [sessions, setSessions] = useState<CodexSession[] | null>(null);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<ProjectSort>("recent");
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [comparison, setComparison] = useState<ResolvedProjectComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const comparisonController = useRef<AbortController | null>(null);
  const comparisonButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setSessions(null);
    transport
      .listCodexSessions(100, 0, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        const parsed = safeCatalogResponse(response);
        if (parsed === null) {
          setError("The locally indexed project catalog response was invalid.");
          return;
        }
        setSessions(parsed);
        const availableProjects = new Set(parsed.map((session) => session.project_id));
        setSelectedProjectIds((selected) => new Set([...selected].filter((id) => availableProjects.has(id))));
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError("The locally indexed project catalog could not be loaded.");
        }
      });
    return () => controller.abort();
  }, [retryKey, transport]);

  useEffect(
    () => () => {
      comparisonController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (comparison === null) document.title = "Projects · Prompt Enhancer";
  }, [comparison]);

  const projects = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const items = buildCatalog(sessions ?? []).filter((project) => {
      if (!normalizedQuery) return true;
      return (
        project.displayName.toLocaleLowerCase().includes(normalizedQuery) ||
        project.sessions.some((session) =>
          session.session_display_name
            ?.toLocaleLowerCase()
            .includes(normalizedQuery),
        )
      );
    });
    return items.sort((left, right) => {
      if (sort === "name") {
        return left.displayName.localeCompare(right.displayName, "en", {
          sensitivity: "base",
        });
      }
      if (sort === "sessions") {
        return (
          right.sessions.length - left.sessions.length ||
          left.displayName.localeCompare(right.displayName)
        );
      }
      return (
        timestampValue(right.latestStartedAt) - timestampValue(left.latestStartedAt) ||
        left.displayName.localeCompare(right.displayName)
      );
    });
  }, [query, sessions, sort]);
  const hiddenSelectedCount = useMemo(() => {
    const visibleProjectIds = new Set(projects.map((project) => project.projectId));
    return [...selectedProjectIds].filter(
      (projectId) => !visibleProjectIds.has(projectId),
    ).length;
  }, [projects, selectedProjectIds]);
  const projectPage = useBoundedListPage({
    itemCount: projects.length,
    pageSize: PROJECT_RENDER_PAGE,
    resetKey: `${query.trim().toLocaleLowerCase()}:${sort}:${retryKey}`,
  });

  function toggleProject(projectId: string, checked: boolean) {
    if (comparisonLoading) return;
    setComparisonError("");
    setSelectedProjectIds((current) => {
      const next = new Set(current);
      if (checked) {
        if (next.size >= 25) return current;
        next.add(projectId);
      } else {
        next.delete(projectId);
      }
      return next;
    });
  }

  async function compareSelectedProjects() {
    const projectIds = [...selectedProjectIds];
    if (projectIds.length < 1 || projectIds.length > 25) return;
    comparisonController.current?.abort();
    const controller = new AbortController();
    comparisonController.current = controller;
    setComparisonError("");
    setComparisonLoading(true);
    try {
      const response = await transport.aggregateProjectQuality(
        {
          project_ids: projectIds,
          selection_mode: "all_analyzed_work",
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const resolved = resolveProjectComparison(response, projectIds.length);
      if (resolved === null) {
        setComparisonError(
          "The local aggregate returned an incompatible metric contract.",
        );
        return;
      }
      setComparison(resolved);
    } catch (reason: unknown) {
      if (controller.signal.aborted) return;
      if (reason instanceof TransportError && reason.status === 409) {
        setComparisonError(
          "One or more selected projects are no longer available in the safe local index.",
        );
      } else if (reason instanceof TransportError && reason.status === 422) {
        setComparisonError(
          "The selected work exceeds the bounded local aggregate limit.",
        );
      } else {
        setComparisonError("The local project aggregate could not be completed.");
      }
    } finally {
      if (comparisonController.current === controller) {
        comparisonController.current = null;
        setComparisonLoading(false);
      }
    }
  }

  if (comparison !== null) {
    return (
      <section className="project-catalog">
        <ProjectComparison
          comparison={comparison}
          onBack={() => {
            setComparison(null);
            window.setTimeout(() => comparisonButtonRef.current?.focus(), 0);
          }}
        />
      </section>
    );
  }

  return (
    <section className="project-catalog" aria-labelledby="project-catalog-title">
      <header className="project-catalog__header route-header">
        <div>
          <p className="eyebrow">Fast analysis loops</p>
          <h1 id="project-catalog-title">Projects</h1>
          <p>
            Choose an indexed project, then keep sessions and metric views inside one
            focused workspace.
          </p>
        </div>
        <span className="status-pill status-pill--info">
          <Icon name="lock" /> Stored local index
        </span>
      </header>

      <MetricCoveragePanel provider={coverageProvider} transport={transport} />

      <div className="project-catalog__controls" role="search">
        <label className="field project-catalog__search">
          <span>Find a project or session</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search local labels"
            type="search"
            value={query}
          />
        </label>
        <label className="field project-catalog__sort">
          <span>Sort projects</span>
          <select
            aria-label="Sort projects"
            onChange={(event) => setSort(event.target.value as ProjectSort)}
            value={sort}
          >
            <option value="recent">Latest activity</option>
            <option value="name">Project name</option>
            <option value="sessions">Session count</option>
          </select>
        </label>
      </div>

      {selectedProjectIds.size > 0 && (
        <aside
          aria-busy={comparisonLoading}
          aria-label="Project aggregate selection"
          className="project-catalog__selection"
        >
          <span aria-atomic="true" aria-live="polite" role="status">
            <strong>{selectedProjectIds.size}</strong>
            {` project${selectedProjectIds.size === 1 ? "" : "s"} selected`}
            {hiddenSelectedCount > 0 && (
              <small>
                {`${hiddenSelectedCount} hidden by the current filter`}
              </small>
            )}
            {comparisonLoading && <small>Combining selected projects locally</small>}
            {selectedProjectIds.size === 25 && <small>Selection limit reached</small>}
          </span>
          <button
            className="button button--primary button--compact"
            disabled={comparisonLoading}
            onClick={compareSelectedProjects}
            ref={comparisonButtonRef}
            type="button"
          >
            {comparisonLoading ? "Combining locally..." : "Combine selected"}
          </button>
        </aside>
      )}
      {comparisonError && (
        <p className="project-catalog__comparison-error" role="alert">
          {comparisonError}
        </p>
      )}

      {error ? (
        <ErrorState message={error} onRetry={() => setRetryKey((value) => value + 1)} />
      ) : sessions === null ? (
        <LoadingState label="Loading the local project catalog..." />
      ) : projects.length === 0 ? (
        <div className="empty-inbox">
          <span><Icon name="search" /></span>
          <h2>{query.trim() ? "No matching projects" : "No indexed projects"}</h2>
          <p>
            {query.trim()
              ? "Try a different local label."
              : "Use Data sources to run a bounded, content-discarding index first."}
          </p>
        </div>
      ) : (
        <div className="project-catalog__grid">
          {projects.slice(projectPage.start, projectPage.end).map((project) => (
            <article
              className={
                selectedProjectIds.has(project.projectId)
                  ? "project-catalog-card project-catalog-card--selected"
                  : "project-catalog-card"
              }
              key={project.projectId}
            >
              <label className="project-catalog-card__select">
                <input
                  aria-label={`Select ${project.displayName} for combined profile`}
                  checked={selectedProjectIds.has(project.projectId)}
                  disabled={
                    comparisonLoading ||
                    (!selectedProjectIds.has(project.projectId) &&
                      selectedProjectIds.size >= 25)
                  }
                  onChange={(event) =>
                    toggleProject(project.projectId, event.target.checked)
                  }
                  type="checkbox"
                />
                <span>Combine</span>
              </label>
              <button
                aria-label={`Open project ${project.displayName}`}
                onClick={() =>
                  navigate({
                    name: "project_overview",
                    projectId: project.projectId,
                  })
                }
                type="button"
              >
                <span className="project-catalog-card__icon"><Icon name="layers" /></span>
                <span className="project-catalog-card__copy">
                  <strong>{project.displayName}</strong>
                  <small>Open its sessions and signal views</small>
                  <span aria-label="Session sources" className="provider-badge-row">
                    {project.providers.map((provider) => (
                      <ProviderBadge compact key={provider} provider={provider} />
                    ))}
                  </span>
                </span>
                <Icon name="arrow" />
              </button>
              <div className="project-catalog-card__windows">
                <button
                  aria-label={`Open a live window for ${project.displayName ?? "this project"}`}
                  className="project-catalog-card__live"
                  onClick={() => { openLiveWindow({ name: "live", projectId: project.projectId }); }}
                  title="Open a small self-refreshing window for this project"
                  type="button"
                >
                  <Icon name="layers" /> Live window
                </button>
              </div>
              <dl className="project-catalog-card__facts">
                <div><dt>Sessions</dt><dd>{project.sessions.length}</dd></div>
                <div><dt>Complete streams</dt><dd>{project.completeSessionCount}</dd></div>
                <div><dt>Activity</dt><dd>{visibleDate(project.latestStartedAt)}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
      <BoundedListPager label="Project catalog pages" page={projectPage} />
      {sessions !== null && (
        <p className="project-catalog__boundary" role="note">
          This view reads at most 100 sessions from Prompt Enhancer's stored index. It
          does not read or mutate any provider's cache; each project shows the sources
          its sessions were captured from.
        </p>
      )}
    </section>
  );
}
