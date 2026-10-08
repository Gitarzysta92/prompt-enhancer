import { useEffect, useMemo, useState } from "react";
import type { PromptEnhancerTransport, SessionCatalogItem } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import type { AppRoute } from "../../shared/platform/platform";
import { routePath } from "../../shared/platform/platform";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import { ProjectTimelinePane } from "../project-timeline/ProjectTimelinePane";
import { SessionTimelinePane } from "../session-timeline/SessionTimelinePane";
import "./LiveMiniWindow.css";

export const LIVE_REFRESH_SECONDS = 20;

type LiveTransport = Pick<
  PromptEnhancerTransport,
  "getProjectTimeline" | "getSessionTimeline" | "listProjectSessions" | "getLatestSessionQualityAnalysis" | "getLatestSessionAnalysisJob"
>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Opens (or focuses) a small browser window for one project or session; several can be open at once. */
export function openLiveWindow(route: Extract<AppRoute, { name: "live" }>): Window | null {
  const name = `pe-live-${route.projectId.slice(0, 12)}-${route.sessionId ? route.sessionId.slice(0, 12) : "project"}`;
  const features = "popup=yes,width=480,height=760,resizable=yes,scrollbars=yes";
  try {
    return window.open(routePath(route), name, features);
  } catch {
    return null;
  }
}

function summarizeRun(value: unknown): { status: string; known: number; total: number; firstPass: string | null } | null {
  if (!isRecord(value) || !isRecord(value.run) || !Array.isArray(value.results)) return null;
  const results = value.results.filter(isRecord);
  const known = results.filter((row) => row.value_state === "known").length;
  const fp = results.find((row) => row.key === "outcome.first_pass_verification");
  let firstPass: string | null = null;
  if (fp) {
    const fraction = isRecord(fp.fraction) ? fp.fraction : null;
    const numerator = fraction && typeof fraction.numerator === "number" && Number.isFinite(fraction.numerator) ? fraction.numerator : null;
    const denominator = fraction && typeof fraction.denominator === "number" && Number.isFinite(fraction.denominator) ? fraction.denominator : null;
    if (fp.value_state === "known") {
      // A known metric with a missing or invalid fraction stays unknown; never print "undefined/undefined".
      firstPass = numerator !== null && denominator !== null
        && Number.isSafeInteger(numerator) && Number.isSafeInteger(denominator)
        && denominator > 0 && numerator >= 0 && numerator <= denominator
        ? `${numerator}/${denominator}` : "unknown";
    } else {
      firstPass = String(fp.value_state ?? "unknown").replace("_", " ");
    }
  }
  return { status: String(value.run.status ?? "unknown"), known, total: results.length, firstPass };
}

type MetaState = "loading" | "known" | "none" | "unavailable";

/**
 * Compact live view of one project or session: name, provider, the
 * deterministic timeline, the latest automatic analysis and job state.
 * Refreshes itself; meant to live in its own small window next to your work.
 */
export function LiveMiniWindow({
  projectId,
  sessionId,
  transport,
}: {
  projectId: string;
  sessionId?: string;
  transport: LiveTransport;
}) {
  const [tick, setTick] = useState(0);
  const [session, setSession] = useState<SessionCatalogItem | null>(null);
  const [projectName, setProjectName] = useState<string>("");
  const [run, setRun] = useState<ReturnType<typeof summarizeRun>>(null);
  const [runState, setRunState] = useState<MetaState>("loading");
  const [job, setJob] = useState<string>("");
  const [jobState, setJobState] = useState<MetaState>("loading");
  const [paused, setPaused] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  // A new owner must never see the previous owner's data, even for one render.
  const ownerKey = `${projectId}::${sessionId ?? ""}`;
  const [lastOwner, setLastOwner] = useState({ key: ownerKey, transport });
  if (lastOwner.key !== ownerKey || lastOwner.transport !== transport) {
    setLastOwner({ key: ownerKey, transport });
    setSession(null);
    setProjectName("");
    setRun(null);
    setRunState("loading");
    setJob("");
    setJobState("loading");
    setUpdatedAt(null);
    setLoadFailed(false);
  }

  useEffect(() => {
    if (paused) return;
    const handle = window.setInterval(() => setTick((value) => value + 1), LIVE_REFRESH_SECONDS * 1000);
    return () => window.clearInterval(handle);
  }, [paused]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const page = await transport.listProjectSessions(projectId, 100, 0, controller.signal);
        if (controller.signal.aborted) return;
        const sessions = isRecord(page) && Array.isArray(page.sessions) ? (page.sessions as SessionCatalogItem[]) : [];
        const current = sessionId ? sessions.find((item) => item.session_id === sessionId) ?? null : null;
        setSession(current);
        const named = sessions.find((item) => item.project_display_name);
        setProjectName(named?.project_display_name ?? "");
        if (sessionId) {
          const [latestRun, latestJob] = await Promise.allSettled([
            transport.getLatestSessionQualityAnalysis(sessionId, controller.signal),
            transport.getLatestSessionAnalysisJob(sessionId, controller.signal),
          ]);
          if (controller.signal.aborted) return;
          if (latestRun.status === "fulfilled") {
            const summary = summarizeRun(latestRun.value);
            if (summary) { setRun(summary); setRunState("known"); } else { setRunState("unavailable"); }
          } else if (latestRun.reason instanceof TransportError && latestRun.reason.status === 404) {
            setRun(null);
            setRunState("none");
          } else {
            if (latestRun.reason instanceof TransportError && latestRun.reason.status === 403) setRun(null);
            setRunState("unavailable"); // keep the last good summary, marked stale
          }
          if (latestJob.status === "fulfilled" && isRecord(latestJob.value)) {
            setJob(String(latestJob.value.state ?? ""));
            setJobState("known");
          } else if (latestJob.status === "rejected" && latestJob.reason instanceof TransportError && latestJob.reason.status === 404) {
            setJob("");
            setJobState("none");
          } else {
            if (latestJob.status === "rejected" && latestJob.reason instanceof TransportError && latestJob.reason.status === 403) setJob("");
            setJobState("unavailable"); // keep the last good state, marked stale
          }
        }
        setLoadFailed(false);
        setUpdatedAt(new Date());
      } catch (caught) {
        if (controller.signal.aborted) return;
        if (caught instanceof TransportError && [403, 404, 410].includes(caught.status)) {
          setSession(null);
          setProjectName("");
          setRun(null);
          setJob("");
          setRunState("unavailable");
          setJobState("unavailable");
        }
        setLoadFailed(true); // temporary failure keeps the last good view, marked stale
      }
    })();
    return () => controller.abort();
  }, [projectId, sessionId, tick, transport]);

  const title = useMemo(() => {
    if (sessionId) return session?.session_display_name?.trim() || `Session ${sessionId.slice(0, 8)}`;
    return projectName || `Project ${projectId.slice(0, 8)}`;
  }, [projectId, projectName, session, sessionId]);

  const dashboardRoute: AppRoute = sessionId
    ? { name: "session_metrics", projectId, sessionId, category: "prompt-quality" }
    : { name: "project_overview", projectId };

  return (
    <section aria-labelledby="live-window-title" className="live-window" data-kind={sessionId ? "session" : "project"}>
      <header className="live-window__head route-header route-header--window">
        <div className="live-window__title">
          <p className="eyebrow">Live · {sessionId ? "session" : "project"}</p>
          <h1 id="live-window-title">{title}</h1>
          <p className="live-window__sub">
            {session ? <ProviderBadge provider={session.provider} /> : null}
            {sessionId && projectName ? <span>{projectName}</span> : null}
          </p>
        </div>
        <div className="live-window__controls">
          <button className="button button--ghost" onClick={() => setPaused((value) => !value)} type="button">
            {paused ? "Resume" : "Pause"}
          </button>
          <button className="button button--ghost" onClick={() => setTick((value) => value + 1)} type="button">Refresh</button>
          <a className="button button--ghost" href={routePath(dashboardRoute)} rel="opener" target="_blank">Open in dashboard</a>
        </div>
      </header>

      {sessionId && (
        <dl className="live-window__facts">
          <div>
            <dt>Latest analysis</dt>
            <dd>
              {runState === "loading" && "—"}
              {runState === "none" && "none yet"}
              {(runState === "known" || runState === "unavailable") && (run
                ? `${run.status} · ${run.known}/${run.total} known${runState === "unavailable" ? " (stale)" : ""}`
                : "unavailable")}
            </dd>
          </div>
          <div><dt>First-pass verification</dt><dd>{run?.firstPass ?? "—"}{run && (runState === "unavailable" || loadFailed) ? " (stale)" : ""}</dd></div>
          <div>
            <dt>Analysis job</dt>
            <dd>
              {jobState === "loading" && "—"}
              {jobState === "none" && "none"}
              {(jobState === "known" || jobState === "unavailable") && (job
                ? `${job}${jobState === "unavailable" ? " (stale)" : ""}`
                : "unavailable")}
            </dd>
          </div>
        </dl>
      )}

      <div className="live-window__body">
        {sessionId
          ? <SessionTimelinePane refreshToken={tick} sessionId={sessionId} transport={transport} />
          : <ProjectTimelinePane projectId={projectId} refreshToken={tick} transport={transport} />}
      </div>

      <footer className="live-window__foot">
        <span aria-live="polite">
          {updatedAt
            ? `Updated ${updatedAt.toLocaleTimeString()}${loadFailed ? " · stale" : ""}`
            : loadFailed ? "Could not load · use Refresh to retry" : "Loading…"}
          {paused ? " · paused" : ` · every ${LIVE_REFRESH_SECONDS}s`}
        </span>
        <span>Local only</span>
      </footer>
    </section>
  );
}
