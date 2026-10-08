import { useEffect, useMemo, useRef, useState } from "react";
import type { PromptEnhancerTransport, SessionTimeline } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import "./SessionTimelinePane.css";

const CATEGORY_LABEL: Record<string, string> = {
  file_read: "Read",
  file_write: "Write",
  command: "Command",
  search: "Search",
  test: "Test",
  build: "Build",
  version_control: "Git",
  network: "Network",
  mcp: "MCP",
  subagent: "Subagent",
  other: "Other",
  unknown: "Unknown",
};
const MARKER_LABEL: Record<string, string> = {
  compaction: "compaction",
  plan: "plan",
  user_feedback: "user feedback",
  subagent_start: "subagent start",
  subagent_end: "subagent end",
  approval: "approval",
  permission_change: "permission change",
  session_end: "session end",
};
const MAX_DRAWN_TURNS = 300;
const MAX_DRAWN_GAPS = 300;
const MAX_DRAWN_TOOLS = 500;
const MAX_DRAWN_CHECKS = 200;
const MAX_DRAWN_MARKERS = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeTimeline(value: unknown): value is SessionTimeline {
  if (!isRecord(value) || value.contract_version !== "session-timeline.v1") return false;
  return typeof value.session_id === "string"
    && typeof value.started_at === "string"
    && Number.isFinite(Date.parse(value.started_at as string))
    && Array.isArray(value.turns) && Array.isArray(value.tools) && Array.isArray(value.markers)
    && isRecord(value.counts) && isRecord(value.usage);
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "–";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return "unknown";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

/** Preserve both ends and evenly sample the middle without changing source order. */
export function boundedTemporalSample<T>(items: readonly T[], limit: number): T[] {
  const safeLimit = Math.max(0, Math.floor(limit));
  if (safeLimit === 0 || items.length === 0) return [];
  if (items.length <= safeLimit) return [...items];
  if (safeLimit === 1) return [items[0]];
  const last = items.length - 1;
  return Array.from({ length: safeLimit }, (_, index) => (
    items[Math.round(index * last / (safeLimit - 1))]
  ));
}

function firstAtOrAfter(sorted: readonly number[], target: number): number | undefined {
  let low = 0;
  let high = sorted.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (sorted[middle] < target) low = middle + 1;
    else high = middle;
  }
  return sorted[low];
}

/** Greedy row packing so overlapping spans stack into rows instead of overplotting. */
export function packRows(items: { start: number; end: number }[], maxRows: number): number[] {
  const rowEnds: number[] = [];
  return items.map((item) => {
    for (let row = 0; row < rowEnds.length; row += 1) {
      if (item.start >= rowEnds[row]) {
        rowEnds[row] = item.end;
        return row;
      }
    }
    if (rowEnds.length < maxRows) {
      rowEnds.push(item.end);
      return rowEnds.length - 1;
    }
    // overflow: place on the last row (dense but never lost)
    rowEnds[rowEnds.length - 1] = Math.max(rowEnds[rowEnds.length - 1], item.end);
    return rowEnds.length - 1;
  });
}

/**
 * Deterministic session timeline v2: turns, waiting gaps (user prompt to first
 * action), tools packed into rows by category, checks, markers - with category
 * filters and drag-to-zoom. Everything drawn comes from indexed safe events -
 * no text, no paths.
 */
export function SessionTimelinePane({
  refreshToken,
  sessionId,
  transport,
}: {
  refreshToken?: number;
  sessionId: string;
  transport: Pick<PromptEnhancerTransport, "getSessionTimeline">;
}) {
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [timeline, setTimeline] = useState<SessionTimeline | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [view, setView] = useState<[number, number] | null>(null);
  const [brush, setBrush] = useState<[number, number] | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const timelineRef = useRef<SessionTimeline | null>(null);
  const chartRef = useRef<HTMLDivElement | null>(null);

  // A new owner (session or transport) must never see the previous owner's
  // data or view state, even for one render: reset synchronously.
  const [scope, setScope] = useState<{ sessionId: string; transport: unknown }>({ sessionId, transport });
  if (scope.sessionId !== sessionId || scope.transport !== transport) {
    setScope({ sessionId, transport });
    timelineRef.current = null;
    setState("loading");
    setTimeline(null);
    setView(null);
    setHidden(new Set());
    setBrush(null);
    setRefreshFailed(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    const isRefresh = timelineRef.current !== null;
    if (!isRefresh) setState("loading");
    transport.getSessionTimeline(sessionId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        if (!safeTimeline(value) || value.session_id !== sessionId) {
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
  }, [refreshToken, retryNonce, sessionId, transport]);

  const model = useMemo(() => {
    if (!timeline) return null;
    const start = Date.parse(timeline.started_at);
    const candidates = [
      timeline.ended_at ? Date.parse(timeline.ended_at) : NaN,
      ...timeline.turns.map((turn) => Date.parse(turn.ended_at ?? turn.started_at)),
      ...timeline.tools.map((tool) => Date.parse(tool.ended_at ?? tool.started_at)),
      ...timeline.markers.map((marker) => Date.parse(marker.at)),
    ].filter((value) => Number.isFinite(value));
    const end = Math.max(start + 1000, ...candidates);
    const span = Math.max(1, end - start);
    // waiting gaps: user turn start -> first tool at or after it (agent latency)
    const toolStarts = timeline.tools.map((tool) => Date.parse(tool.started_at)).filter(Number.isFinite).sort((a, b) => a - b);
    const gaps = timeline.turns.flatMap((turn) => {
      const at = Date.parse(turn.started_at);
      if (!Number.isFinite(at)) return [];
      const next = firstAtOrAfter(toolStarts, at);
      if (next === undefined || next <= at) return [];
      return [{ start: at, end: next, ms: next - at }];
    });
    return { start, end, span, gaps };
  }, [timeline]);

  if (state === "loading") return <section className="session-timeline" aria-busy="true"><p className="session-timeline__note">Drawing the timeline…</p></section>;
  if (state === "missing") return null;
  if (state === "error" || !timeline || !model) {
    return <section className="session-timeline"><p className="session-timeline__note" role="alert">The timeline could not be verified.</p><button onClick={() => setRetryNonce((value) => value + 1)} type="button">Retry timeline</button></section>;
  }
  const refreshNote = refreshFailed ? (
    <p className="session-timeline__note" role="alert">
      The last refresh failed; showing the last verified timeline.{" "}
      <button onClick={() => setRetryNonce((value) => value + 1)} type="button">Retry</button>
    </p>
  ) : null;
  if (timeline.turns.length === 0 && timeline.tools.length === 0 && timeline.markers.length === 0) {
    return (
      <section className="session-timeline">
        <header className="session-timeline__head">
          <div>
            <p className="eyebrow">Timeline · deterministic facts</p>
            <h2>What happened, when</h2>
          </div>
        </header>
        {refreshNote}
        <p className="session-timeline__note">No drawable events were indexed for this session (only usage or metadata records).</p>
      </section>
    );
  }

  const counts = timeline.counts;
  const [viewStart, viewEnd] = view ?? [model.start, model.end];
  const viewSpan = Math.max(1, viewEnd - viewStart);
  const x = (ms: number) => Math.min(1, Math.max(0, (ms - viewStart) / viewSpan));
  const inView = (startMs: number, endMs: number) => endMs >= viewStart && startMs <= viewEnd;
  const width = 1000;
  const laneHeight = 18;
  const toolRowHeight = 10;

  const categories = [...new Set(timeline.tools.filter((tool) => !tool.verification).map((tool) => tool.category))];
  const visibleTools = timeline.tools.filter((tool) => tool.verification || !hidden.has(tool.category));
  const turnCandidates = timeline.turns
    .map((turn) => ({
      end: turn.ended_at ? Date.parse(turn.ended_at) : Date.parse(turn.started_at) + 1,
      start: Date.parse(turn.started_at),
      turn,
    }))
    .filter((item) => Number.isFinite(item.start) && inView(item.start, item.end));
  const gapCandidates = model.gaps.filter((gap) => inView(gap.start, gap.end));
  const plainToolCandidates = visibleTools
    .filter((tool) => !tool.verification)
    .map((tool) => ({ tool, start: Date.parse(tool.started_at), end: Math.max(Date.parse(tool.ended_at ?? tool.started_at), Date.parse(tool.started_at) + 1) }))
    .filter((item) => Number.isFinite(item.start) && inView(item.start, item.end))
    .sort((a, b) => a.start - b.start);
  const verificationCandidates = visibleTools
    .filter((tool) => tool.verification)
    .map((tool) => ({
      end: Math.max(Date.parse(tool.ended_at ?? tool.started_at), Date.parse(tool.started_at) + 1),
      start: Date.parse(tool.started_at),
      tool,
    }))
    .filter((item) => Number.isFinite(item.start) && inView(item.start, item.end));
  const markerCandidates = timeline.markers
    .map((marker) => ({ at: Date.parse(marker.at), marker }))
    .filter((item) => Number.isFinite(item.at) && inView(item.at, item.at));
  const drawnTurns = boundedTemporalSample(turnCandidates, MAX_DRAWN_TURNS);
  const drawnGaps = boundedTemporalSample(gapCandidates, MAX_DRAWN_GAPS);
  const plainTools = boundedTemporalSample(plainToolCandidates, MAX_DRAWN_TOOLS);
  const verifications = boundedTemporalSample(verificationCandidates, MAX_DRAWN_CHECKS);
  const drawnMarkers = boundedTemporalSample(markerCandidates, MAX_DRAWN_MARKERS);
  const toolRowCount = Math.min(4, Math.max(1, plainTools.length ? 4 : 1));
  const rows = packRows(plainTools, toolRowCount);
  const usedRows = plainTools.length ? Math.max(...rows) + 1 : 1;
  const eligibleDrawCount = turnCandidates.length + gapCandidates.length + plainToolCandidates.length
    + verificationCandidates.length + markerCandidates.length;
  const drawnCount = drawnTurns.length + drawnGaps.length + plainTools.length
    + verifications.length + drawnMarkers.length;

  const lanes: { key: string; label: string; height: number }[] = [
    { key: "turns", label: "Turns", height: laneHeight },
    { key: "waiting", label: "Latency", height: 8 },
    { key: "tools", label: "Tools", height: usedRows * (toolRowHeight + 2) },
    { key: "checks", label: "Checks", height: laneHeight },
    { key: "markers", label: "Markers", height: laneHeight },
  ];
  const laneTop = (key: string) => {
    let y = 12;
    for (const lane of lanes) {
      if (lane.key === key) return y;
      y += lane.height + 10;
    }
    return y;
  };
  const height = 12 + lanes.reduce((sum, lane) => sum + lane.height + 10, 0) + 8;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  const beginBrush = (clientX: number) => {
    const node = chartRef.current?.querySelector("svg");
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    setBrush([fraction, fraction]);
  };
  const moveBrush = (clientX: number) => {
    if (!brush) return;
    const node = chartRef.current?.querySelector("svg");
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    setBrush([brush[0], fraction]);
  };
  const minimumViewSpan = Math.min(model.span, Math.max(1000, model.span / 64));
  const boundedView = (candidateStart: number, candidateSpan: number): [number, number] | null => {
    const span = Math.min(model.span, Math.max(minimumViewSpan, candidateSpan));
    if (span >= model.span) return null;
    const start = Math.min(model.end - span, Math.max(model.start, candidateStart));
    return [start, start + span];
  };
  const endBrush = () => {
    if (!brush) return;
    const [a, b] = [Math.min(...brush), Math.max(...brush)];
    setBrush(null);
    if (b - a < 0.02) return; // a click, not a drag
    const selectedStart = viewStart + a * viewSpan;
    const selectedSpan = (b - a) * viewSpan;
    const boundedStart = selectedStart - Math.max(0, minimumViewSpan - selectedSpan) / 2;
    setView(boundedView(boundedStart, selectedSpan));
  };
  const zoomBy = (factor: number) => {
    const nextSpan = viewSpan * factor;
    const center = viewStart + viewSpan / 2;
    setView(boundedView(center - nextSpan / 2, nextSpan));
  };
  const panBy = (direction: -1 | 1) => {
    if (!view) return;
    setView(boundedView(viewStart + direction * viewSpan * 0.25, viewSpan));
  };
  const canZoomIn = viewSpan > minimumViewSpan;
  const canZoomOut = view !== null;
  const canPanEarlier = view !== null && viewStart > model.start;
  const canPanLater = view !== null && viewEnd < model.end;
  const handleChartKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if ((event.key === "+" || event.key === "=") && canZoomIn) zoomBy(0.5);
    else if ((event.key === "-" || event.key === "_") && canZoomOut) zoomBy(2);
    else if (event.key === "ArrowLeft" && canPanEarlier) panBy(-1);
    else if (event.key === "ArrowRight" && canPanLater) panBy(1);
    else if (event.key === "Home" && view !== null) setView(null);
    else return;
    event.preventDefault();
  };
  const viewPosition = view
    ? `Showing ${formatDuration(viewSpan)} of ${formatDuration(model.span)}, from ${formatDuration(viewStart - model.start)} to ${formatDuration(viewEnd - model.start)}`
    : `Showing full timeline, from 0s to ${formatDuration(model.span)}`;

  return (
    <section aria-labelledby="session-timeline-title" className="session-timeline">
      <header className="session-timeline__head">
        <div>
          <p className="eyebrow">Timeline · deterministic facts</p>
          <h2 id="session-timeline-title">What happened, when</h2>
        </div>
        <dl className="session-timeline__stats">
          <div><dt>Duration</dt><dd>{formatDuration(model.span)}</dd></div>
          <div><dt>Turns</dt><dd>{counts.turns}</dd></div>
          <div><dt>Tool calls</dt><dd>{counts.tools}{counts.tool_errors > 0 ? ` · ${counts.tool_errors} failed` : ""}</dd></div>
          <div>
            <dt>Checks</dt>
            <dd>
              {counts.verifications_passed + counts.verifications_failed + counts.verifications_unknown === 0
                ? "none observed"
                : `${counts.verifications_passed} passed · ${counts.verifications_failed} failed${counts.verifications_unknown ? ` · ${counts.verifications_unknown} unknown` : ""}`}
            </dd>
          </div>
          {model.gaps.length > 0 && (
            <div><dt>Median wait</dt><dd>{formatDuration([...model.gaps.map((g) => g.ms)].sort((a, b) => a - b)[Math.floor(model.gaps.length / 2)])}</dd></div>
          )}
          <div><dt>Tokens</dt><dd>{timeline.usage.requests === 0 ? "not reported" : `${formatTokens(timeline.usage.input_tokens)} in · ${formatTokens(timeline.usage.output_tokens)} out`}</dd></div>
        </dl>
      </header>
      {refreshNote}
      <div className="session-timeline__toolbar">
        <div aria-label="Show or hide tool categories" className="session-timeline__filters" role="group">
          {categories.map((category) => (
            <button
              aria-pressed={!hidden.has(category)}
              className={hidden.has(category) ? "session-timeline__filter" : "session-timeline__filter session-timeline__filter--on"}
              data-category={category}
              key={category}
              onClick={() => setHidden((prev) => { const next = new Set(prev); if (next.has(category)) next.delete(category); else next.add(category); return next; })}
              type="button"
            >
              <i aria-hidden="true" /> {CATEGORY_LABEL[category] ?? category}
            </button>
          ))}
        </div>
        <div aria-label="Timeline view controls" className="session-timeline__view-controls" role="group">
          <button disabled={!canZoomIn} onClick={() => zoomBy(0.5)} type="button">Zoom in</button>
          <button disabled={!canZoomOut} onClick={() => zoomBy(2)} type="button">Zoom out</button>
          <button disabled={!canPanEarlier} onClick={() => panBy(-1)} type="button">Earlier</button>
          <button disabled={!canPanLater} onClick={() => panBy(1)} type="button">Later</button>
          <button disabled={view === null} onClick={() => setView(null)} type="button">Full timeline</button>
          <span className="session-timeline__view-status" role="status">
            {viewPosition}
          </span>
        </div>
      </div>
      <div
        className="session-timeline__chart"
        ref={chartRef}
        role="group"
        aria-label={`Timeline with ${counts.turns} turns, ${counts.tools} tool calls and ${verificationCandidates.length} checks in this view. Drag horizontally to zoom, or use plus and minus to zoom, Left and Right arrows to move, and Home to reset.`}
        tabIndex={0}
        onKeyDown={handleChartKeyDown}
        onPointerDown={(event) => { if (event.button === 0) { event.currentTarget.setPointerCapture(event.pointerId); beginBrush(event.clientX); } }}
        onPointerMove={(event) => moveBrush(event.clientX)}
        onPointerUp={endBrush}
        onPointerCancel={() => setBrush(null)}
        onDoubleClick={() => setView(null)}
      >
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" width="100%" height={height}>
          {ticks.map((tick) => (
            <line key={tick} className="session-timeline__grid" x1={tick * width} x2={tick * width} y1={6} y2={height - 10} />
          ))}
          {drawnTurns.map(({ end, start, turn }) => {
            const x1 = x(start) * width;
            const x2 = x(end) * width;
            return (
              <rect key={`turn-${turn.index}`} className="session-timeline__turn" x={x1} y={laneTop("turns")} width={Math.max(3, x2 - x1)} height={laneHeight} rx={3}>
                <title>{`Turn ${turn.index + 1}${turn.ended_at ? ` · ${formatDuration(end - start)}` : ""} · ${new Date(start).toLocaleTimeString()}`}</title>
              </rect>
            );
          })}
          {drawnGaps.map((gap, index) => {
            const x1 = x(gap.start) * width;
            const x2 = x(gap.end) * width;
            return (
              <rect key={`gap-${index}`} className="session-timeline__gap" x={x1} y={laneTop("waiting")} width={Math.max(1.5, x2 - x1)} height={8} rx={2}>
                <title>{`Waited ${formatDuration(gap.ms)} before the first action`}</title>
              </rect>
            );
          })}
          {plainTools.map((item, index) => {
            const x1 = x(item.start) * width;
            const x2 = x(item.end) * width;
            const failed = item.tool.success === false;
            return (
              <rect
                key={`tool-${index}`}
                className={`session-timeline__tool session-timeline__tool--${item.tool.category}${failed ? " session-timeline__tool--error" : ""}`}
                data-category={item.tool.category}
                x={x1}
                y={laneTop("tools") + rows[index] * (toolRowHeight + 2)}
                width={Math.max(2, x2 - x1)}
                height={toolRowHeight}
                rx={2}
              >
                <title>{`${CATEGORY_LABEL[item.tool.category] ?? item.tool.category}${failed ? " · failed" : ""}${item.tool.duration_ms != null ? ` · ${formatDuration(item.tool.duration_ms)}` : ""} · ${new Date(item.start).toLocaleTimeString()}`}</title>
              </rect>
            );
          })}
          {verifications.map(({ end, start, tool }, index) => {
            const tone = tool.success === false ? "failed" : tool.success === true ? "passed" : "unknown";
            return (
              <rect
                key={`check-${index}`}
                className={`session-timeline__check session-timeline__check--${tone}`}
                x={x(start) * width}
                y={laneTop("checks")}
                width={Math.max(3, (x(end) - x(start)) * width)}
                height={laneHeight}
                rx={3}
              >
                <title>{`${CATEGORY_LABEL[tool.category] ?? tool.category} check · ${tone}${tool.duration_ms != null ? ` · ${formatDuration(tool.duration_ms)}` : ""}`}</title>
              </rect>
            );
          })}
          {drawnMarkers.map(({ at, marker }, index) => {
            return (
              <g key={`marker-${index}`} className={`session-timeline__marker session-timeline__marker--${marker.kind}`}>
                <line x1={x(at) * width} x2={x(at) * width} y1={laneTop("markers")} y2={laneTop("markers") + laneHeight} />
                <title>{`${MARKER_LABEL[marker.kind] ?? marker.kind.replace(/_/g, " ")} · ${new Date(at).toLocaleTimeString()}`}</title>
              </g>
            );
          })}
          {brush && (
            <rect className="session-timeline__brush" x={Math.min(...brush) * width} y={4} width={Math.abs(brush[1] - brush[0]) * width} height={height - 12} />
          )}
        </svg>
        <ol className="session-timeline__lanes" aria-hidden="true">
          {lanes.map((lane) => <li key={lane.key} style={{ height: lane.height + 10 }}>{lane.label}</li>)}
        </ol>
      </div>
      <p className="session-timeline__note" data-bounded={drawnCount < eligibleDrawCount ? "true" : "false"}>
        {drawnCount < eligibleDrawCount
          ? `Drawing ${drawnCount.toLocaleString("en-US")} of ${eligibleDrawCount.toLocaleString("en-US")} timeline items in this view. Zoom in to reveal more local detail.`
          : `Drawing all ${drawnCount.toLocaleString("en-US")} timeline items in this view.`}
      </p>
      <p className="session-timeline__axis" aria-hidden="true">
        <span>{new Date(viewStart).toLocaleTimeString()}</span>
        <span>{formatDuration(viewSpan)}{view ? " (zoomed)" : ""}</span>
        <span>{new Date(viewEnd).toLocaleTimeString()}</span>
      </p>
      {(timeline.truncated || !timeline.events_complete) && (
        <p className="session-timeline__note">
          {timeline.truncated ? "Long session: the drawing is bounded; counts cover what was drawn." : "The provider did not confirm this session's event stream is complete."}
        </p>
      )}
    </section>
  );
}
