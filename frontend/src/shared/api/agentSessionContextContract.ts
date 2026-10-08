import type { AgentSessionContextStatus } from "./contracts";
import { LocalRuntimePayloadError, parseRuntimeContextStatus } from "./localRuntimeContract";

const SESSION_ID = /^[0-9a-f]{32}$/u;
const MODEL_ALIAS = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const KEYS = new Set([
  "contract_version",
  "session_id",
  "revision",
  "binding_state",
  "source",
  "unknown_reason",
  "turn_id",
  "turn_number",
  "model_alias",
  "observed_at",
  "context",
]);
const UNKNOWN_REASONS = new Set([
  "no_request_measured",
  "recovered_without_context_receipt",
  "turn_pending_preflight",
  "turn_ended_before_preflight",
  "turn_start_failed",
  "preflight_unavailable",
  "preflight_failed",
  "request_body_too_large",
  "model_changed",
]);

export class AgentSessionContextPayloadError extends Error {
  constructor() {
    super("Agent session context payload was invalid");
    this.name = "AgentSessionContextPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>): boolean {
  const actual = Object.keys(value);
  return actual.length === KEYS.size && actual.every((key) => KEYS.has(key));
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function validTurnBinding(value: Record<string, unknown>): boolean {
  return typeof value.turn_id === "string"
    && SESSION_ID.test(value.turn_id)
    && typeof value.turn_number === "number"
    && Number.isSafeInteger(value.turn_number)
    && value.turn_number >= 1
    && typeof value.model_alias === "string"
    && MODEL_ALIAS.test(value.model_alias);
}

export function parseAgentSessionContext(
  value: unknown,
  expectedSessionId?: string,
): AgentSessionContextStatus {
  if (
    !record(value)
    || !exact(value)
    || value.contract_version !== "agent-session-context.v1"
    || typeof value.session_id !== "string"
    || !SESSION_ID.test(value.session_id)
    || expectedSessionId !== undefined && value.session_id !== expectedSessionId
    || typeof value.revision !== "number"
    || !Number.isSafeInteger(value.revision)
    || value.revision < 0
    || !["unmeasured", "bound"].includes(String(value.binding_state))
    || value.source !== "runtime_chat_template_preflight"
  ) throw new AgentSessionContextPayloadError();

  const completeTurn = validTurnBinding(value);
  if (value.binding_state === "unmeasured") {
    const noTurn = value.turn_id === null
      && value.turn_number === null
      && value.model_alias === null;
    if (
      typeof value.unknown_reason !== "string"
      || !UNKNOWN_REASONS.has(value.unknown_reason)
      || (!noTurn && !completeTurn)
      || value.observed_at !== null
      || value.context !== null
    ) throw new AgentSessionContextPayloadError();
  } else {
    if (
      value.unknown_reason !== null
      || !completeTurn
      || !timestamp(value.observed_at)
      || value.context === null
    ) throw new AgentSessionContextPayloadError();
    try {
      parseRuntimeContextStatus(value.context);
    } catch (error) {
      if (error instanceof LocalRuntimePayloadError) {
        throw new AgentSessionContextPayloadError();
      }
      throw error;
    }
  }
  return value as unknown as AgentSessionContextStatus;
}
