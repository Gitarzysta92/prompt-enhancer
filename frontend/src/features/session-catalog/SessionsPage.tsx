import { useEffect, useMemo, useRef, useState } from "react";
import {
  isLocalProvider,
  providerLabel,
  type CodexSession,
  type LocalProvider,
  type PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { isPseudonym } from "../../shared/platform/platform";
import type { RuntimeDataMode } from "../../shared/platform/runtimeMode";
import { ErrorState, LoadingState } from "../../shared/ui/AsyncState";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { Icon } from "../../shared/ui/Icon";
import { openLiveWindow } from "../live-window/LiveMiniWindow";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import "./Sessions.css";

const PAGE = 100;
const MAX_PAGES = 10;
const RENDER_PAGE = 50;

type Filter = "all" | LocalProvider;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeLabel(value: unknown, max: number): value is string | null {
  return value === null || (typeof value === "string" && value.length >= 1 && value.length <= max && !/[\u0000-\u001f\u007f]/.test(value));
}

/** Fail closed on any row that is not the content-free catalog shape. */
export function safeSessionRow(value: unknown): value is CodexSession {
  return (
    isRecord(value) &&
    isLocalProvider(value.provider) &&
    typeof value.session_id === "string" && isPseudonym(value.session_id) &&
    typeof value.project_id === "string" && isPseudonym(value.project_id) &&
    typeof value.installation_id === "string" && isPseudonym(value.installation_id) &&
    safeLabel(value.project_display_name, 120) &&
    safeLabel(value.session_display_name, 160) &&
    typeof value.started_at === "string" &&
    (value.ended_at === null || typeof value.ended_at === "string") &&
    typeof value.events_complete === "boolean"
  );
}

function ms(value: string | null): number | null {
  if (!value) return null;
  const t = new Date(value).valueOf();
  return Number.isNaN(t) ? null : t;
}

export function durationLabel(started: string, ended: string | null): string {
  const a = ms(started);
  const b = ms(ended);
  if (a === null) return "Start unknown";
  if (b === null) return "End not recorded";
  if (b < a) return "Duration unavailable";
  const seconds = Math.round((b - a) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes - hours * 60} min`;
}

function startedLabel(value: string): string {
  const t = ms(value);
  if (t === null) return "Unknown start";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(t) + " UTC";
}

function visible(value: string | null, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

/**
 * Every session across every provider, newest first, findable by name.
 * Identifiers never appear in this view; they live in detail routes only.
 */
export function SessionsPage({
  transport,
  navigate,
  runtimeMode = "synthetic_demo",
}: {
  transport: Pick<PromptEnhancerTransport, "listCodexSessions">;
  navigate: (route: AppRoute) => void;
  runtimeMode?: RuntimeDataMode;
}) {
  const [rows, setRows] = useState<CodexSession[] | null>(null);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [retry, setRetry] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState("");
  const moreRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setRows(null);
    setError("");
    setComplete(false);
    setLoadingMore(false);
    setMoreError("");
    (async () => {
      const collected: CodexSession[] = [];
      try {
        for (let page = 0; page < MAX_PAGES; page += 1) {
          const response = await transport.listCodexSessions(PAGE, page * PAGE, controller.signal);
          if (controller.signal.aborted) return;
          if (!isRecord(response) || !Array.isArray(response.sessions) || response.sessions.length > PAGE || !response.sessions.every(safeSessionRow)
            || new Set([...collected, ...response.sessions].map((row) => row.session_id)).size !== collected.length + response.sessions.length) {
            setError("The stored session catalog response was invalid and was not shown.");
            return;
          }
          collected.push(...response.sessions);
          if (response.sessions.length < PAGE) {
            setComplete(true);
            break;
          }
          if (page === MAX_PAGES - 1) setComplete(false);
        }
        setRows(collected);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof TransportError && caught.status === 401
          ? "Sign in to the local service to list sessions."
          : "The stored session catalog could not be loaded.");
      }
    })();
    return () => { controller.abort(); moreRequest.current?.abort(); moreRequest.current = null; };
  }, [transport, retry]);

  async function loadMore() {
    if (rows === null || complete || moreRequest.current) return;
    const controller = new AbortController();
    moreRequest.current = controller;
    const owns = () => moreRequest.current === controller && !controller.signal.aborted;
    setLoadingMore(true);
    setMoreError("");
    try {
      const response = await transport.listCodexSessions(PAGE, rows.length, controller.signal);
      if (!owns()) return;
      if (!isRecord(response) || !Array.isArray(response.sessions) || response.sessions.length > PAGE || !response.sessions.every(safeSessionRow)
        || new Set([...rows, ...response.sessions].map((row) => row.session_id)).size !== rows.length + response.sessions.length) {
        setMoreError("The catalog changed or the next page could not be verified. Reload the catalog before continuing.");
        return;
      }
      setRows([...rows, ...response.sessions]);
      setComplete(response.sessions.length < PAGE);
    } catch {
      if (owns()) setMoreError("More sessions could not be loaded. The loaded sessions are unchanged; try again or reload the catalog.");
    } finally {
      if (owns()) { moreRequest.current = null; setLoadingMore(false); }
    }
  }

  const providers = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows ?? []) seen.add(row.provider);
    return ["codex", "claude_code", "synthetic"].filter((p) => seen.has(p)) as LocalProvider[];
  }, [rows]);

  const filtered = useMemo(() => {
    if (rows === null) return [];
    const needle = query.trim().toLowerCase();
    return [...rows]
      .filter((row) => filter === "all" || row.provider === filter)
      .filter((row) => {
        if (!needle) return true;
        const hay = `${row.project_display_name ?? ""} ${row.session_display_name ?? ""}`.toLowerCase();
        return hay.includes(needle);
      })
      .sort((a, b) => (ms(b.started_at) ?? 0) - (ms(a.started_at) ?? 0));
  }, [rows, query, filter]);

  const unnamed = useMemo(() => filtered.filter((row) => !row.session_display_name?.trim()).length, [filtered]);
  const renderPage = useBoundedListPage({
    itemCount: filtered.length,
    pageSize: RENDER_PAGE,
    resetKey: `${query.trim().toLocaleLowerCase()}:${filter}:${retry}`,
  });

  return (
    <section className="sessions-page" aria-labelledby="sessions-title">
      <header className="page-header route-header">
        <div>
          <p className="eyebrow">Personal workspace</p>
          <h1 id="sessions-title">Sessions</h1>
          <p>Captured sessions across your sources, newest first. Search the loaded catalog by project or title.</p>
        </div>
        <div className="page-header__meta">
          <span className="privacy-chip"><Icon name="lock" /> Local only</span>
        </div>
      </header>

      <div className="sessions-toolbar" role="search">
        <label className="sessions-search">
          <Icon name="search" />
          <input
            aria-label="Search sessions by project or title"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="Search by project or title"
            type="search"
            value={query}
          />
        </label>
        <div aria-label="Filter by source" className="segmented-control sessions-filter" role="group">
          <button
            aria-pressed={filter === "all"}
            className={filter === "all" ? "segmented-control__item--active" : ""}
            onClick={() => setFilter("all")}
            type="button"
          >
            All sources
          </button>
          {providers.map((provider) => (
            <button
              aria-pressed={filter === provider}
              className={filter === provider ? "segmented-control__item--active" : ""}
              key={provider}
              onClick={() => setFilter(provider)}
              type="button"
            >
              {providerLabel(provider)}
            </button>
          ))}
        </div>
      </div>

      {rows !== null && !error && (
        <p className="sessions-count" aria-live="polite">
          {filtered.length} of {rows.length} session{rows.length === 1 ? "" : "s"}
          {unnamed > 0 ? ` · ${unnamed} without a title` : ""}
          {!complete && <> · Partial catalog: search covers only the {rows.length} loaded sessions. Load more to search beyond this batch.</>}
        </p>
      )}
      {error !== "" ? (
        <ErrorState message={error} onRetry={() => setRetry((value) => value + 1)} />
      ) : rows === null ? (
        <LoadingState label="Loading sessions…" />
      ) : filtered.length === 0 ? (
        <div className="sessions-empty" role="note">
          <strong>{rows.length === 0 ? "No sessions captured yet" : "No sessions match"}</strong>
          <p>
            {rows.length === 0
              ? runtimeMode === "local_real"
                ? "Grant a source on the Data sources page and index it; sessions appear here with their project and title."
                : "This synthetic preview has no session fixtures to show. Local-source access is available only in the local application."
              : complete ? "Try a different search or source filter." : "No matches in the loaded batch. Load more sessions or change the search or source filter."}
          </p>
          {rows.length === 0 && runtimeMode === "local_real" && <button className="button button--ghost" onClick={() => navigate({ name: "local_sources" })} type="button">Open Data sources</button>}
        </div>
      ) : (
        <>
          <ul className="sessions-list">
            {filtered.slice(renderPage.start, renderPage.end).map((row) => (
              <li key={row.session_id}>
                <button
                  aria-label={`Open ${visible(row.session_display_name, "untitled session")} in ${visible(row.project_display_name, "unnamed project")}`}
                  className="session-row"
                  onClick={() => navigate({
                    name: "session_metrics",
                    projectId: row.project_id,
                    sessionId: row.session_id,
                    category: "readiness",
                  })}
                  type="button"
                >
                  <span className="session-row__title">
                    <strong>{visible(row.session_display_name, "Untitled session")}</strong>
                    <small>{visible(row.project_display_name, "Unnamed project")}</small>
                  </span>
                  <span className="session-row__meta">
                    <ProviderBadge compact provider={row.provider} />
                    <time dateTime={row.started_at}>{startedLabel(row.started_at)}</time>
                    <span className="session-row__duration">{durationLabel(row.started_at, row.ended_at)}</span>
                  </span>
                  <Icon className="session-row__arrow" name="arrow" />
                </button>
                <button
                  aria-label={`Open a live window for ${visible(row.session_display_name, "this session")}`}
                  className="session-row__live"
                  onClick={() => { openLiveWindow({ name: "live", projectId: row.project_id, sessionId: row.session_id }); }}
                  title="Open a small self-refreshing window for this session"
                  type="button"
                >
                  <Icon name="layers" />
                </button>
              </li>
            ))}
          </ul>
          <BoundedListPager label="Stored session pages" page={renderPage} />
        </>
      )}
      {rows !== null && !error && !complete && (
        <div className="sessions-pagination">
          <button className="button button--secondary" disabled={loadingMore} onClick={() => void loadMore()} type="button">{loadingMore ? "Loading more…" : `Load next ${PAGE} sessions`}</button>
          {moreError && <ErrorState message={moreError} actionLabel="Reload catalog" onRetry={() => setRetry((value) => value + 1)} />}
        </div>
      )}
    </section>
  );
}
