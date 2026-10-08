import { useEffect, useMemo, useRef, useState } from "react";
import type { ProjectTimeline, PromptEnhancerTransport } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { packRows } from "../session-timeline/SessionTimelinePane";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import "./ProjectTimelinePane.css";

const DAY = 86_400_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeProjectTimeline(value: unknown): value is ProjectTimeline {
  if (!isRecord(value) || value.contract_version !== "project-timeline.v1") return false;
  return typeof value.project_id === "string"
    && Array.isArray(value.sessions) && Array.isArray(value.tasks) && Array.isArray(value.activity) && Array.isArray(value.providers);
}

function formatSpan(ms: number): string {
  const days = ms / DAY;
  if (days < 1) return `${Math.max(1, Math.round(ms / 3_600_000))}h`;
  if (days < 60) return `${Math.round(days)} days`;
  return `${Math.round(days / 30)} months`;
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Project timeline: reviewed task windows (start → stop) and sessions on one
 * calendar axis, plus activity by day. Everything is from indexed metadata;
 * a click on a session opens it in the session view.
 */
export function ProjectTimelinePane({
  projectId,
  refreshToken,
  transport,
  onOpenSession,
}: {
  projectId: string;
  refreshToken?: number;
  transport: Pick<PromptEnhancerTransport, "getProjectTimeline">;
  onOpenSession?: (sessionId: string) => void;
}) {
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [timeline, setTimeline] = useState<ProjectTimeline | null>(null);
  const [range, setRange] = useState<"all" | "90d" | "30d">("all");
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const timelineRef = useRef<ProjectTimeline | null>(null);

  // A new owner (project or transport) must never see the previous owner's
  // data or range, even for one render: reset synchronously.
  const [scope, setScope] = useState<{ projectId: string; transport: unknown }>({ projectId, transport });
  if (scope.projectId !== projectId || scope.transport !== transport) {
    setScope({ projectId, transport });
    timelineRef.current = null;
    setState("loading");
    setTimeline(null);
    setRange("all");
    setRefreshFailed(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    const isRefresh = timelineRef.current !== null;
    if (!isRefresh) setState("loading");
    transport.getProjectTimeline(projectId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        if (!safeProjectTimeline(value) || value.project_id !== projectId) {
          // Reject stale or unverifiable completions; a refresh keeps the last good view.
          if (isRefresh) setRefreshFailed(true); else setState("error");
          return;
        }
        timelineRef.current = value;
        setTimeline(value);
        setRefreshFailed(false);
        setState("ready");
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        if (caught instanceof TransportError && [403, 404, 410].includes(caught.status)) {
          timelineRef.current = null;
          setTimeline(null);
          setRefreshFailed(false);
          setState(caught.status === 403 ? "error" : "missing");
          return;
        }
        if (isRefresh) { setRefreshFailed(true); return; } // keep the last good view
        setState(caught instanceof TransportError && caught.status === 404 ? "missing" : "error");
      });
    return () => controller.abort();
  }, [projectId, refreshToken, retryNonce, transport]);

  const model = useMemo(() => {
    if (!timeline || timeline.sessions.length === 0) return "empty" as const;
    const ends = timeline.sessions.map((s) => Date.parse(s.ended_at ?? s.started_at));
    const starts = timeline.sessions.map((s) => Date.parse(s.started_at));
    const fullEnd = Math.max(...ends, ...starts);
    const fullStart = Math.min(...starts);
    const windowStart = range === "all" ? fullStart : Math.max(fullStart, fullEnd - (range === "90d" ? 90 : 30) * DAY);
    const start = windowStart;
    const end = Math.max(fullEnd, start + DAY);
    const span = end - start;
    const x = (iso: string) => Math.min(1, Math.max(0, (Date.parse(iso) - start) / span));
    const visibleSessions = timeline.sessions.filter((s) => {
      const startedAt = Date.parse(s.started_at);
      return Number.isFinite(startedAt) && Date.parse(s.ended_at ?? s.started_at) >= start;
    });
    // Open tasks (no ended_at yet) stay visible: they run to the right edge.
    const visibleTasks = timeline.tasks.filter((t) => {
      const taskEnd = t.ended_at ? Date.parse(t.ended_at) : end;
      const taskStart = t.started_at ? Date.parse(t.started_at) : NaN;
      return Number.isFinite(taskStart) && taskEnd >= start;
    });
    const windowedActivity = timeline.activity.filter((d) => Date.parse(`${d.day}T00:00:00Z`) >= start - DAY);
    const maxActivity = Math.max(1, ...windowedActivity.map((d) => d.sessions));
    return { start, end, span, x, visibleSessions, visibleTasks, maxActivity, windowedActivity };
  }, [timeline, range]);

  if (state === "loading") return <section className="project-timeline" aria-busy="true"><p className="project-timeline__note">Drawing the project timeline…</p></section>;
  if (state === "missing") return null;
  if (state === "error" || !timeline || model === null) {
    return <section className="project-timeline"><p className="project-timeline__note" role="alert">The project timeline could not be verified.</p><button onClick={() => setRetryNonce((value) => value + 1)} type="button">Retry timeline</button></section>;
  }
  const refreshNote = refreshFailed ? (
    <p className="project-timeline__note" role="alert">
      The last refresh failed; showing the last verified timeline.{" "}
      <button onClick={() => setRetryNonce((value) => value + 1)} type="button">Retry</button>
    </p>
  ) : null;
  if (model === "empty") {
    return (
      <section className="project-timeline">
        <header className="project-timeline__head">
          <div>
            <p className="eyebrow">Project timeline</p>
            <h2>Sessions and reviewed tasks over time</h2>
          </div>
        </header>
        {refreshNote}
        <p className="project-timeline__note">No indexed sessions in this project yet; the timeline appears with the first one.</p>
      </section>
    );
  }

  const { x, span, visibleSessions, visibleTasks, maxActivity, windowedActivity } = model;
  const width = 1000;
  const rowHeight = 14;
  const taskRows = visibleTasks.slice(0, 60);
  const sessionRows = visibleSessions.slice(-120);
  const packedSessions = sessionRows
    .map((session) => ({ session, start: Date.parse(session.started_at), end: Math.max(Date.parse(session.ended_at ?? session.started_at), Date.parse(session.started_at) + 60_000) }))
    .sort((a, b) => a.start - b.start);
  const sessionRowIndex = packRows(packedSessions, 6);
  const sessionRowCount = packedSessions.length ? Math.max(...sessionRowIndex) + 1 : 1;
  const taskTop = 8;
  const sessionTop = taskTop + taskRows.length * (rowHeight + 4) + 14;
  const activityTop = sessionTop + sessionRowCount * (rowHeight + 3) + 12;
  const activityHeight = 28;
  const height = activityTop + activityHeight + 8;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <section aria-labelledby="project-timeline-title" className="project-timeline">
      <header className="project-timeline__head">
        <div>
          <p className="eyebrow">Timeline · start and stop of reviewed work</p>
          <h2 id="project-timeline-title">Tasks and sessions over time</h2>
          <p className="project-timeline__lede">
            Each task bar spans its sessions from first start to last stop; sessions are the thin bars beneath;
            the strip at the bottom is sessions per day. Multi-session groupings appear once you accept them.
          </p>
        </div>
        <div className="project-timeline__controls">
          <div className="project-timeline__badges">
            {timeline.providers.map((provider) => <ProviderBadge key={provider} provider={provider} />)}
          </div>
          <div className="project-timeline__range" role="group" aria-label="Time range">
            {(["all", "90d", "30d"] as const).map((value) => (
              <button
                key={value}
                aria-pressed={range === value}
                className={range === value ? "is-active" : ""}
                onClick={() => setRange(value)}
                type="button"
              >
                {value === "all" ? "All" : value === "90d" ? "90 days" : "30 days"}
              </button>
            ))}
          </div>
        </div>
      </header>
      {refreshNote}
      <dl className="project-timeline__stats">
        <div><dt>Span</dt><dd>{formatSpan(span)}</dd></div>
        <div><dt>Tasks</dt><dd>{visibleTasks.length}{timeline.tasks.length !== visibleTasks.length ? ` of ${timeline.tasks.length}` : ""}</dd></div>
        <div><dt>Sessions</dt><dd>{visibleSessions.length}{timeline.truncated ? "+" : ""}</dd></div>
        <div><dt>Active days</dt><dd>{windowedActivity.length}</dd></div>
      </dl>
      <div className="project-timeline__chart" role="img" aria-label={`${visibleTasks.length} task windows and ${visibleSessions.length} sessions over ${formatSpan(span)}`}>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" width="100%" height={height}>
          {ticks.map((tick) => (
            <line key={tick} className="project-timeline__grid" x1={tick * width} x2={tick * width} y1={4} y2={height - 4} />
          ))}
          {taskRows.map((task, index) => {
            const startMs = task.started_at ? Date.parse(task.started_at) : NaN;
            if (!Number.isFinite(startMs)) return null;
            const open = !task.ended_at;
            const endMs = open ? model.end : Date.parse(task.ended_at as string);
            const x1 = x(new Date(Math.max(startMs, model.start)).toISOString()) * width;
            const x2 = x(new Date(endMs).toISOString()) * width;
            return (
              <g key={task.task_id} className={`project-timeline__task project-timeline__task--${task.lifecycle_state}${open ? " project-timeline__task--open" : ""}`}>
                <rect x={x1} y={taskTop + index * (rowHeight + 4)} width={Math.max(4, x2 - x1)} height={rowHeight} rx={3} />
                <title>{`${task.display_name ?? "Task"} · ${task.task_type ?? "task"} · ${task.session_ids.length} session${task.session_ids.length === 1 ? "" : "s"} · ${task.lifecycle_state}${open ? " · still open" : ""}`}</title>
              </g>
            );
          })}
          {packedSessions.map((item, index) => {
            const session = item.session;
            const x1 = x(new Date(Math.max(item.start, model.start)).toISOString()) * width;
            const x2 = x(new Date(item.end).toISOString()) * width;
            return (
              <g
                key={session.session_id}
                className={`project-timeline__session project-timeline__session--${session.provider}${onOpenSession ? " is-clickable" : ""}${session.events_complete === false ? " project-timeline__session--partial" : ""}`}
                onClick={onOpenSession ? () => onOpenSession(session.session_id) : undefined}
                role={onOpenSession ? "button" : undefined}
                tabIndex={onOpenSession ? 0 : undefined}
                aria-label={onOpenSession ? `${session.display_name ?? "Session"} · ${shortDate(session.started_at)}` : undefined}
                onKeyDown={onOpenSession ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpenSession(session.session_id); } } : undefined}
              >
                <rect x={x1} y={sessionTop + sessionRowIndex[index] * (rowHeight + 3)} width={Math.max(3, x2 - x1)} height={rowHeight} rx={2} />
                <title>{`${session.display_name ?? "Session"} · ${shortDate(session.started_at)}${session.terminal_state && session.terminal_state !== "unknown" ? ` · ${session.terminal_state}` : ""}`}</title>
              </g>
            );
          })}
          {timeline.activity.map((day) => {
            const dayStart = Date.parse(`${day.day}T00:00:00Z`);
            if (dayStart + DAY < model.start) return null;
            const x1 = x(new Date(dayStart).toISOString()) * width;
            const x2 = x(new Date(dayStart + DAY).toISOString()) * width;
            const h = Math.max(2, (day.sessions / maxActivity) * activityHeight);
            return (
              <rect key={day.day} className="project-timeline__activity" x={x1} y={activityTop + activityHeight - h} width={Math.max(2, x2 - x1)} height={h}>
                <title>{`${day.day} · ${day.sessions} session${day.sessions === 1 ? "" : "s"}`}</title>
              </rect>
            );
          })}
        </svg>
      </div>
      <p className="project-timeline__axis" aria-hidden="true">
        <span>{shortDate(new Date(model.start).toISOString())}</span>
        <span>{formatSpan(span)}</span>
        <span>{shortDate(new Date(model.end).toISOString())}</span>
      </p>
      {(timeline.truncated || visibleTasks.length > taskRows.length) && (
        <p className="project-timeline__note">
          {timeline.truncated ? "Large project: the newest 500 sessions are drawn." : `Showing the first ${taskRows.length} task windows.`}
        </p>
      )}
    </section>
  );
}
