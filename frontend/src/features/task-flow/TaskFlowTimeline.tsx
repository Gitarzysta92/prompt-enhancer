import { useMemo } from "react";
import type { TaskDecision } from "../../shared/api/contracts";
import { formatTimestamp, titleFromKey } from "../../shared/lib/format";
import { taskFlowTimelineScale, timelinePosition } from "./taskFlowAdapter";
import type { TaskFlowItem } from "./taskFlowModel";

type TimelineLane = "proposal" | "revision" | "lifecycle" | "analysis";

interface TaskFlowTimelineEvent {
  id: string;
  lane: TimelineLane;
  occurredAt: string;
  title: string;
  detail: string;
  item: TaskFlowItem;
}

const LANES: readonly { lane: TimelineLane; label: string }[] = [
  { lane: "proposal", label: "Proposal & explicit review records" },
  { lane: "revision", label: "Confirmed revision records" },
  { lane: "lifecycle", label: "Explicit task lifecycle receipts" },
  { lane: "analysis", label: "Analysis events (not task lifecycle)" },
];

function timelineEvents(
  items: readonly TaskFlowItem[],
  decisionAudits: ReadonlyMap<string, readonly TaskDecision[]>,
): TaskFlowTimelineEvent[] {
  const events: TaskFlowTimelineEvent[] = [];
  const candidateById = new Map(
    items.filter((item) => item.kind === "candidate").map((item) => [item.sourceId, item]),
  );
  const seenDecisions = new Set<string>();

  for (const item of items) {
    if (item.kind === "candidate") {
      events.push({
        id: `${item.id}:created`,
        lane: "proposal",
        occurredAt: item.occurredAt,
        title: `${item.title} detected`,
        detail: "Discovery proposal created",
        item,
      });
      continue;
    }
    events.push({
      id: `${item.id}:revision-created`,
      lane: "revision",
      occurredAt: item.occurredAt,
      title: `${item.title} confirmed`,
      detail: `Raw revision state ${titleFromKey(item.lifecycle.status)}`,
      item,
    });
    for (const receipt of item.workLifecycle?.events ?? []) {
      events.push({
        id: `${item.id}:lifecycle:${receipt.event_id}`,
        lane: "lifecycle",
        occurredAt: receipt.created_at,
        title: `${item.title} · ${receipt.event_kind === "correction" ? "work-state correction" : titleFromKey(receipt.resulting_state ?? "unknown")}`,
        detail: `${receipt.prior_state === null ? "Unknown" : titleFromKey(receipt.prior_state)} → ${receipt.resulting_state === null ? "Unknown" : titleFromKey(receipt.resulting_state)} · explicit local-user server receipt`,
        item,
      });
    }
    for (const run of item.analysis.runs) {
      events.push({
        id: `${item.id}:run:${run.runId}:started`,
        lane: "analysis",
        occurredAt: run.startedAt,
        title: `${item.title} · analysis started`,
        detail: `${run.provenance.origin} · ${run.provenance.version}`,
        item,
      });
      if (run.finishedAt !== null) {
        events.push({
          id: `${item.id}:run:${run.runId}:finished`,
          lane: "analysis",
          occurredAt: run.finishedAt,
          title: `${item.title} · analysis ${run.status}`,
          detail: "Analysis event only; task finish remains unknown",
          item,
        });
      }
    }
  }

  for (const decisions of decisionAudits.values()) {
    for (const decision of decisions) {
      if (seenDecisions.has(decision.decision_id)) continue;
      seenDecisions.add(decision.decision_id);
      const item = decision.candidate_ids
        .map((candidateId) => candidateById.get(candidateId))
        .find((value): value is TaskFlowItem => value !== undefined);
      if (item === undefined) continue;
      events.push({
        id: `decision:${decision.decision_id}`,
        lane: "proposal",
        occurredAt: decision.decided_at,
        title: `${item.title} · ${titleFromKey(decision.action)}`,
        detail: "Immutable human review decision",
        item,
      });
    }
  }

  return events.sort((left, right) => {
    const byTime = left.occurredAt.localeCompare(right.occurredAt);
    return byTime !== 0 ? byTime : left.id.localeCompare(right.id);
  });
}

/**
 * Chronology of exact record/event times. It never draws a task-duration bar:
 * points use server receipt time and are never stretched into inferred duration.
 */
export function TaskFlowTimeline({
  items,
  decisionAudits,
  onOpen,
}: {
  items: readonly TaskFlowItem[];
  decisionAudits: ReadonlyMap<string, readonly TaskDecision[]>;
  onOpen: (item: TaskFlowItem) => void;
}) {
  const events = useMemo(() => timelineEvents(items, decisionAudits), [decisionAudits, items]);
  const scale = useMemo(() => taskFlowTimelineScale(events), [events]);
  const undated = events.filter((event) => !Number.isFinite(new Date(event.occurredAt).getTime())).length;
  if (scale === null) {
    return <p className="task-flow-timeline__empty" role="status">No valid record or event time matches the current filters, so chronology cannot be plotted.</p>;
  }
  return (
    <div className="task-flow-timeline">
      <div aria-hidden="true" className="task-flow-timeline__axis">
        {scale.ticks.map((tick, index) => (
          <span key={tick.at} style={{ left: `${(index / (scale.ticks.length - 1)) * 100}%` }}>{tick.label}</span>
        ))}
      </div>
      {LANES.map((lane) => {
        const laneEvents = events.filter((event) => event.lane === lane.lane);
        return (
          <section aria-label={lane.label} className="task-flow-lane" data-lane={lane.lane} key={lane.lane}>
            <header><strong>{lane.label}</strong><small>{laneEvents.length} event{laneEvents.length === 1 ? "" : "s"}</small></header>
            <ol className="task-flow-lane__track">
              {laneEvents.map((event) => {
                const position = timelinePosition(scale, event.occurredAt);
                if (position === null) return null;
                return (
                  <li key={event.id} style={{ left: `${position * 100}%` }}>
                    <button
                      aria-label={`${event.title} · ${formatTimestamp(event.occurredAt)} · ${event.detail}`}
                      data-event={event.lane}
                      onClick={() => onOpen(event.item)}
                      type="button"
                    >
                      <i aria-hidden="true" />
                      <span>{event.title}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
      <p className="task-flow-timeline__legend">
        Points use exact proposal creation, review decision, revision creation, explicit lifecycle receipt, and analysis event times. Lifecycle points are server receipt times, not inferred real-world start or finish; missing values remain Unknown.{undated > 0 ? ` ${undated} invalid event time${undated === 1 ? " was" : "s were"} omitted.` : ""}
      </p>
    </div>
  );
}
