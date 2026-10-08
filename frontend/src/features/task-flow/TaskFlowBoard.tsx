import type { PromptEnhancerTransport, TaskDecision } from "../../shared/api/contracts";
import { formatTimestamp, shortId } from "../../shared/lib/format";
import { FactList } from "../../shared/ui/FactList";
import { ProviderBadge } from "../../shared/ui/ProviderBadge";
import { Icon } from "../../shared/ui/Icon";
import { StatusPill, type PillTone } from "../../shared/ui/StatusPill";
import { TaskFlowAudit } from "./TaskFlowAudit";
import { TaskLifecycleControls } from "./TaskLifecycleControls";
import {
  TASK_FLOW_ANALYSIS_LABELS,
  TASK_FLOW_COLUMN_GROUPS,
  TASK_FLOW_COLUMNS,
  TASK_FLOW_KIND_LABELS,
  TASK_FLOW_SOURCE_LABELS,
  type TaskFlowItem,
} from "./taskFlowModel";

const ANALYSIS_TONE: Readonly<Record<TaskFlowItem["analysis"]["state"], PillTone>> = {
  running: "warning",
  completed: "neutral",
  failed: "danger",
  not_observed: "unknown",
  unknown: "unknown",
  not_applicable: "neutral",
};

type TaskFlowCardTransport = Pick<
  PromptEnhancerTransport,
  "getCandidateDecisions" | "transitionTaskLifecycle" | "correctTaskLifecycle"
>;

export function TaskFlowCard({
  item,
  allItems,
  decisionAudits,
  transport,
  onOpen,
  onDecisionsLoaded,
  onLifecycleChanged,
}: {
  item: TaskFlowItem;
  allItems: readonly TaskFlowItem[];
  decisionAudits: ReadonlyMap<string, readonly TaskDecision[]>;
  transport: TaskFlowCardTransport;
  onOpen: (item: TaskFlowItem) => void;
  onDecisionsLoaded: (candidateId: string, values: readonly TaskDecision[]) => void;
  onLifecycleChanged: (message: string) => void;
}) {
  const titleId = `task-flow-card-${item.kind}-${shortId(item.sourceId)}-${item.provenance.version.replaceAll(/[^a-z0-9]/giu, "-").slice(0, 18)}`;
  const taskHistory = item.kind === "confirmed"
    ? allItems.filter((candidate) => candidate.kind === "confirmed" && candidate.sourceId === item.sourceId)
    : [];
  return (
    <li className="task-flow-card" data-analysis={item.analysis.state} data-kind={item.kind}>
      <article aria-labelledby={titleId}>
        <header>
          <StatusPill tone={item.kind === "candidate" ? "warning" : "neutral"}>
            {TASK_FLOW_KIND_LABELS[item.kind]}
          </StatusPill>
          <small>Record created {formatTimestamp(item.occurredAt)}</small>
        </header>
        <h4 id={titleId}>{item.title}</h4>
        <p className="task-flow-card__subtitle">{item.subtitle}</p>
        <FactList
          className="task-flow-card__facts"
          compact
          facts={[
            {
              term: "Record state",
              detail: (
                <>
                  <span className="task-flow-card__source">{TASK_FLOW_SOURCE_LABELS[item.lifecycle.source]}</span>
                  {" · "}
                  {item.lifecycle.label}
                </>
              ),
            },
            {
              term: "Provenance",
              detail: (
                <>
                  {item.provenance.origin} · {item.provenance.version} · fingerprint <span className="mono">{shortId(item.provenance.fingerprint)}</span>
                  {item.provenance.dataTier === null ? "" : ` · ${item.provenance.dataTier.replaceAll("_", " ")} tier`}
                </>
              ),
            },
            item.kind === "candidate"
              ? {
                term: "Discovery evidence",
                detail: <>{item.evidence.label}<span className="task-flow-card__detail">{item.evidence.detail}</span></>,
              }
              : {
                term: "Work state",
                detail: (
                  <>
                    <strong>{item.workLifecycle?.label ?? "State not reconciled"}</strong>
                    <span className="task-flow-card__detail">
                      {item.workLifecycle?.authority === "authoritative"
                        ? `${item.workLifecycle.eventCount ?? 0} immutable lifecycle receipt${item.workLifecycle.eventCount === 1 ? "" : "s"}; only explicit commands mutate this state.`
                        : "No backlog, in-progress, or done state is fabricated from analysis or revision metadata."}
                    </span>
                  </>
                ),
              },
            item.kind === "confirmed"
              ? {
                term: "Analysis (not task state)",
                detail: (
                  <>
                    <StatusPill tone={ANALYSIS_TONE[item.analysis.state]}>{TASK_FLOW_ANALYSIS_LABELS[item.analysis.state]}</StatusPill>
                    <span className="task-flow-card__detail">{item.analysis.detail}</span>
                  </>
                ),
              }
              : {
                term: "Decision receipt",
                detail: !item.reviewDecisionRecorded
                  ? <>No review decision recorded · review in Discovery</>
                  : item.decisionId === null
                    ? <>Decision recorded · receipt identifier not exposed</>
                    : <>Decision receipt <span className="mono">{shortId(item.decisionId)}</span></>,
              },
            item.kind === "confirmed"
              ? {
                term: "Lifecycle receipt times",
                detail: <>
                  In-progress recorded <strong>{item.taskStartedAt === null ? "Unknown" : formatTimestamp(item.taskStartedAt)}</strong>
                  {" · "}done recorded <strong>{item.taskFinishedAt === null ? "Unknown" : formatTimestamp(item.taskFinishedAt)}</strong>
                  <span className="task-flow-card__detail">These are exact server receipt times, not inferred real-world start or finish times.</span>
                </>,
              }
              : {
                term: "Proposal authority",
                detail: <>A detected grouping remains a proposal until its explicit review receipt is loaded.</>,
              },
          ]}
          label={`${item.title} record facts`}
        />
        <TaskFlowAudit
          decisions={decisionAudits.get(item.sourceId)}
          item={item}
          navigate={(route) => {
            if (route.name === "task") onOpen({ ...item, route });
          }}
          onDecisionsLoaded={onDecisionsLoaded}
          taskHistory={taskHistory}
          transport={transport}
        />
        <TaskLifecycleControls
          item={item}
          onLifecycleChanged={onLifecycleChanged}
          transport={transport}
        />
        <footer>
          <span>
            {item.provider === null ? null : <ProviderBadge provider={item.provider} />}
            {item.provider === null ? "" : " "}
            {item.sessionCount} session{item.sessionCount === 1 ? "" : "s"}
          </span>
          <button
            className="button button--secondary button--compact"
            disabled={item.route === null}
            onClick={() => onOpen(item)}
            type="button"
          >
            {item.kind === "candidate" ? "Review in Discovery" : "Open revision"} <Icon name="arrow" />
          </button>
        </footer>
      </article>
    </li>
  );
}

/** Fixed evidence-neutral columns; empty columns stay visible. */
export function TaskFlowBoard({
  items,
  allItems,
  decisionAudits,
  transport,
  onOpen,
  onDecisionsLoaded,
  onLifecycleChanged,
}: {
  items: readonly TaskFlowItem[];
  allItems: readonly TaskFlowItem[];
  decisionAudits: ReadonlyMap<string, readonly TaskDecision[]>;
  transport: TaskFlowCardTransport;
  onOpen: (item: TaskFlowItem) => void;
  onDecisionsLoaded: (candidateId: string, values: readonly TaskDecision[]) => void;
  onLifecycleChanged: (message: string) => void;
}) {
  return (
    <div aria-label="Task flow board" className="task-flow-board" role="group">
      {TASK_FLOW_COLUMN_GROUPS.map((group) => (
        <section aria-labelledby={`task-flow-group-${group.id}`} className="task-flow-board__group" data-group={group.id} key={group.id}>
          <header className="task-flow-board__group-header">
            <h2 id={`task-flow-group-${group.id}`}>{group.label}</h2>
            <p>{group.description}</p>
          </header>
          <div className="task-flow-board__grid">
            {TASK_FLOW_COLUMNS.filter((column) => column.group === group.id).map((column) => {
              const columnItems = items.filter((item) => item.column === column.id);
              const headingId = `task-flow-column-${column.id}`;
              return (
                <section aria-labelledby={headingId} className="task-flow-column" data-column={column.id} data-kind={column.kind} key={column.id}>
                  <header>
                    <div>
                      <h3 id={headingId}>{column.label}</h3>
                      <small>{column.description}</small>
                    </div>
                    <span aria-label={`${columnItems.length} ${columnItems.length === 1 ? "item" : "items"}`} className="task-flow-column__count">{columnItems.length}</span>
                  </header>
                  <ul>
                    {columnItems.length === 0
                      ? <li className="task-flow-column__empty">Nothing in this column for the current filters.</li>
                      : columnItems.map((item) => (
                        <TaskFlowCard
                          allItems={allItems}
                          decisionAudits={decisionAudits}
                          item={item}
                          key={item.id}
                          onDecisionsLoaded={onDecisionsLoaded}
                          onLifecycleChanged={onLifecycleChanged}
                          onOpen={onOpen}
                          transport={transport}
                        />
                      ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
