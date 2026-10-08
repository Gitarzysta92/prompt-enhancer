import type { AgentHistoryExport } from "./contracts";
import { AgentEventPayloadError, parseAgentEvent } from "./agentEventContract";

const ID = /^[0-9a-f]{32}$/u;
const EXPORT_KEYS = new Set([
  "contract_version",
  "events",
  "exported_at",
  "history_revision",
  "interrupted",
  "model_alias",
  "project_id",
  "session_id",
  "title",
  "turn_count",
  "workspace",
]);
const FORBIDDEN_DURABLE_EVENT_KEYS = new Set([
  "approval_id",
  "arguments",
  "preview",
  "stream_phase",
]);

export class AgentHistoryPayloadError extends Error {
  constructor() {
    super("Agent history payload was invalid");
    this.name = "AgentHistoryPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && Array.from(value).length >= 1
    && Array.from(value).length <= maximum;
}

function integer(value: unknown, minimum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
}

export function parseAgentHistoryExport(
  value: unknown,
  expectedProjectId?: string,
  expectedSessionId?: string,
): AgentHistoryExport {
  if (
    !record(value)
    || !exact(value, EXPORT_KEYS)
    || value.contract_version !== "agent-history.v1"
    || typeof value.project_id !== "string" || !ID.test(value.project_id)
    || (expectedProjectId !== undefined && value.project_id !== expectedProjectId)
    || typeof value.session_id !== "string" || !ID.test(value.session_id)
    || (expectedSessionId !== undefined && value.session_id !== expectedSessionId)
    || !boundedText(value.title, 120)
    || !boundedText(value.workspace, 1024)
    || !(value.model_alias === null || boundedText(value.model_alias, 64))
    || typeof value.exported_at !== "string" || !Number.isFinite(Date.parse(value.exported_at))
    || !integer(value.history_revision, 0)
    || !integer(value.turn_count, 0)
    || typeof value.interrupted !== "boolean"
    || !Array.isArray(value.events)
    || value.events.length > 4_000
    || value.events.length !== value.history_revision
  ) throw new AgentHistoryPayloadError();

  let events;
  try {
    events = value.events.map((candidate) => {
      if (
        !record(candidate)
        || Object.keys(candidate).some((key) => FORBIDDEN_DURABLE_EVENT_KEYS.has(key))
      ) throw new AgentHistoryPayloadError();
      const event = parseAgentEvent(candidate);
      if (event.kind === "assistant_delta" || event.kind.startsWith("approval_")) {
        throw new AgentHistoryPayloadError();
      }
      if (event.kind === "tool_result" && event.text != null) {
        throw new AgentHistoryPayloadError();
      }
      return event;
    });
  } catch (error) {
    if (error instanceof AgentEventPayloadError || error instanceof AgentHistoryPayloadError) {
      throw new AgentHistoryPayloadError();
    }
    throw error;
  }
  let cursor = 0;
  for (const event of events) {
    if (event.seq <= cursor) throw new AgentHistoryPayloadError();
    cursor = event.seq;
  }
  const done = events.filter((event) => event.kind === "done");
  if (done.length !== value.turn_count) throw new AgentHistoryPayloadError();
  let lastUser = 0;
  for (const event of events) {
    if (event.kind === "user") lastUser = event.seq;
  }
  const lastDone = done.at(-1)?.seq ?? 0;
  if (value.interrupted !== (lastUser > lastDone)) throw new AgentHistoryPayloadError();
  return { ...value, events } as AgentHistoryExport;
}
