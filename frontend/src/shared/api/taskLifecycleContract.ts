import type {
  TaskLifecycleEvent,
  TaskLifecycleListResponse,
  TaskLifecycleMutationResponse,
  TaskLifecycleSnapshot,
  TaskLifecycleState,
} from "./contracts";

const PSEUDONYM = /^[0-9a-f]{64}$/u;
const STATES = new Set<TaskLifecycleState>(["backlog", "in_progress", "done"]);
const EVENT_KEYS = [
  "actor_scope",
  "command_schema_version",
  "created_at",
  "event_id",
  "event_kind",
  "previous_event_id",
  "prior_state",
  "request_fingerprint",
  "resulting_state",
  "sequence",
  "source",
  "supersedes_event_id",
  "task_id",
  "task_input_fingerprint",
  "task_revision",
] as const;
const SNAPSHOT_KEYS = [
  "current_state",
  "current_task_revision",
  "event_count",
  "events",
  "events_complete",
  "events_limit",
  "events_offset",
  "head_event_id",
  "is_current_revision",
  "prior_revision_event_count",
  "task_id",
  "task_revision",
] as const;

export class TaskLifecyclePayloadError extends Error {
  constructor() {
    super("Task lifecycle response was invalid");
    this.name = "TaskLifecyclePayloadError";
  }
}

function invalid(): never {
  throw new TaskLifecyclePayloadError();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length
    && actual.every((key, index) => key === sortedExpected[index]);
}

function safeInteger(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && value <= maximum;
}

function pseudonym(value: unknown): value is string {
  return typeof value === "string" && PSEUDONYM.test(value);
}

function optionalPseudonym(value: unknown): value is string | null {
  return value === null || pseudonym(value);
}

function state(value: unknown): value is TaskLifecycleState {
  return typeof value === "string" && STATES.has(value as TaskLifecycleState);
}

function optionalState(value: unknown): value is TaskLifecycleState | null {
  return value === null || state(value);
}

function utcTimestamp(value: unknown): value is string {
  if (
    typeof value !== "string"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/u.test(value)
  ) return false;
  return Number.isFinite(new Date(value).getTime());
}

function legalTransition(prior: TaskLifecycleState | null, result: TaskLifecycleState): boolean {
  return (prior === null && result === "backlog")
    || (prior === "backlog" && result === "in_progress")
    || (prior === "in_progress" && result === "done");
}

function parseEvent(value: unknown): TaskLifecycleEvent {
  if (!isRecord(value) || !exactKeys(value, EVENT_KEYS)) invalid();
  if (
    !pseudonym(value.event_id)
    || !pseudonym(value.task_id)
    || !pseudonym(value.task_input_fingerprint)
    || !pseudonym(value.request_fingerprint)
    || !safeInteger(value.task_revision, 1)
    || !safeInteger(value.sequence, 1)
    || !optionalState(value.prior_state)
    || !optionalState(value.resulting_state)
    || !optionalPseudonym(value.previous_event_id)
    || !optionalPseudonym(value.supersedes_event_id)
    || value.command_schema_version !== "task-lifecycle-command-v1"
    || value.source !== "explicit_local_user"
    || value.actor_scope !== "local_user"
    || !utcTimestamp(value.created_at)
    || !["transition", "correction"].includes(String(value.event_kind))
  ) invalid();

  if (
    (value.sequence === 1) !== (value.previous_event_id === null)
    || (value.event_kind === "transition" && (
      value.supersedes_event_id !== null
      || !state(value.resulting_state)
      || !legalTransition(value.prior_state as TaskLifecycleState | null, value.resulting_state)
    ))
    || (value.event_kind === "correction" && (
      value.previous_event_id === null
      || value.supersedes_event_id !== value.previous_event_id
    ))
  ) invalid();
  return value as unknown as TaskLifecycleEvent;
}

export function parseTaskLifecycleSnapshot(
  value: unknown,
  expected: { taskId?: string; revision?: number; currentOnly?: boolean } = {},
): TaskLifecycleSnapshot {
  if (!isRecord(value) || !exactKeys(value, SNAPSHOT_KEYS)) invalid();
  if (
    !pseudonym(value.task_id)
    || (expected.taskId !== undefined && value.task_id !== expected.taskId)
    || !safeInteger(value.task_revision, 1)
    || (expected.revision !== undefined && value.task_revision !== expected.revision)
    || !safeInteger(value.current_task_revision, 1)
    || typeof value.is_current_revision !== "boolean"
    || value.is_current_revision !== (value.task_revision === value.current_task_revision)
    || (expected.currentOnly === true && value.is_current_revision !== true)
    || !optionalState(value.current_state)
    || !optionalPseudonym(value.head_event_id)
    || !safeInteger(value.event_count)
    || !safeInteger(value.prior_revision_event_count)
    || !safeInteger(value.events_limit, 1, 100)
    || !safeInteger(value.events_offset)
    || typeof value.events_complete !== "boolean"
    || !Array.isArray(value.events)
    || value.events.length > value.events_limit
    || value.events_complete !== (value.events_offset + value.events.length >= value.event_count)
  ) invalid();

  if (
    (value.event_count === 0 && (
      value.current_state !== null
      || value.head_event_id !== null
      || value.events.length !== 0
    ))
    || (value.event_count > 0 && value.head_event_id === null)
  ) invalid();

  const events = value.events.map(parseEvent);
  const eventIds = new Set<string>();
  let fingerprint: string | null = null;
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    const predecessor = index > 0 ? events[index - 1] : null;
    if (
      event.task_id !== value.task_id
      || event.task_revision !== value.task_revision
      || event.sequence !== value.events_offset + index + 1
      || eventIds.has(event.event_id)
      || (predecessor !== null && event.previous_event_id !== predecessor.event_id)
      || (predecessor !== null && event.prior_state !== predecessor.resulting_state)
      || (predecessor !== null && event.event_kind === "correction" && (
        event.supersedes_event_id !== predecessor.event_id
        || event.resulting_state !== predecessor.prior_state
      ))
      || (fingerprint !== null && event.task_input_fingerprint !== fingerprint)
    ) invalid();
    eventIds.add(event.event_id);
    fingerprint ??= event.task_input_fingerprint;
  }

  const last = events.at(-1);
  if (
    last !== undefined
    && value.events_complete
    && value.events_offset + events.length === value.event_count
    && (last.event_id !== value.head_event_id || last.resulting_state !== value.current_state)
  ) invalid();

  return { ...value, events } as unknown as TaskLifecycleSnapshot;
}

export function parseTaskLifecycleListResponse(
  value: unknown,
  expected: { limit: number; offset: number },
): TaskLifecycleListResponse {
  if (
    !isRecord(value)
    || !exactKeys(value, ["lifecycles", "limit", "offset"])
    || value.limit !== expected.limit
    || value.offset !== expected.offset
    || !Array.isArray(value.lifecycles)
    || value.lifecycles.length > expected.limit
  ) invalid();
  const lifecycles = value.lifecycles.map((item) =>
    parseTaskLifecycleSnapshot(item, { currentOnly: true }));
  if (
    lifecycles.some((item) => item.events_offset !== 0)
    || new Set(lifecycles.map((item) => item.task_id)).size !== lifecycles.length
  ) invalid();
  return { lifecycles, limit: expected.limit, offset: expected.offset };
}

export function parseTaskLifecycleMutationResponse(
  value: unknown,
  expected: {
    taskId: string;
    revision: number;
    eventKind: "transition" | "correction";
    expectedHeadEventId: string | null;
    requestedState?: TaskLifecycleState;
    correctionPriorState?: TaskLifecycleState | null;
    correctionResultingState?: TaskLifecycleState | null;
  },
): TaskLifecycleMutationResponse {
  if (
    !isRecord(value)
    || !exactKeys(value, ["event", "head_event_id", "state"])
    || !pseudonym(value.head_event_id)
    || !optionalState(value.state)
  ) invalid();
  const event = parseEvent(value.event);
  if (
    event.task_id !== expected.taskId
    || event.task_revision !== expected.revision
    || event.event_kind !== expected.eventKind
    || event.event_id !== value.head_event_id
    || event.previous_event_id !== expected.expectedHeadEventId
    || event.resulting_state !== value.state
    || (expected.eventKind === "transition" && event.resulting_state !== expected.requestedState)
    || (expected.eventKind === "correction" && (
      expected.expectedHeadEventId === null
      || expected.correctionPriorState === undefined
      || expected.correctionResultingState === undefined
      || event.supersedes_event_id !== expected.expectedHeadEventId
      || event.prior_state !== expected.correctionPriorState
      || event.resulting_state !== expected.correctionResultingState
    ))
  ) invalid();
  return { event, head_event_id: value.head_event_id, state: value.state };
}
