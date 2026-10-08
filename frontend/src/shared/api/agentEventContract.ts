import type {
  AgentEvent,
  AgentEvents,
  AgentMcpToolDescriptor,
  AgentMcpToolResultReceipt,
  AgentSessionView,
} from "./contracts";
import { parseAgentMessageAttachment } from "./agentAttachmentContract";
import { isAgentToolExecutionReceipt, isAgentToolState, isAgentTurnSummary, isAgentWriteReceipt } from "./agentTurnContract";

const CONTRACT_VERSION = "local-agent.v9";
const MAX_EVENT_PAGE = 500;
const MAX_DELTA_CHARS = 192;
const MAX_APPROVAL_PREVIEW_CHARS = 260_000;
const ID = /^[0-9a-f]{32}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;
const MCP_ALIAS = /^[A-Za-z0-9_-]+$/u;
const MCP_ERROR = /^[a-z][a-z0-9_]{2,95}$/u;
const KINDS = new Set<AgentEvent["kind"]>([
  "user",
  "assistant",
  "assistant_delta",
  "tool_call",
  "tool_result",
  "approval_required",
  "approval_resolved",
  "status",
  "error",
  "done",
]);
const EVENT_KEYS = new Set([
  "approval_id",
  "arguments",
  "attachments",
  "at",
  "call_id",
  "kind",
  "ok",
  "preview",
  "reasoning",
  "seq",
  "stream_id",
  "stream_phase",
  "stream_status",
  "text",
  "tool",
  "turn_id",
  "turn_summary",
  "tool_state",
  "write_receipt",
  "execution_receipt",
  "mcp_tool",
  "mcp_result",
]);

export class AgentEventPayloadError extends Error {
  constructor() {
    super("Local agent event payload was invalid");
    this.name = "AgentEventPayloadError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nullableString(value: unknown, maxLength: number): value is string | null | undefined {
  return value === null || value === undefined || (typeof value === "string" && Array.from(value).length <= maxLength);
}

function safeMcpDisplayText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && value === value.trim()
    && Array.from(value).length <= maximum
    && !/[\p{Cc}\p{Cf}]/u.test(value);
}

const KIND_FIELDS: Record<AgentEvent["kind"], ReadonlySet<string>> = {
  user: new Set(["text"]),
  assistant: new Set(["text", "reasoning", "stream_id", "stream_status"]),
  assistant_delta: new Set(["text", "stream_id", "stream_phase"]),
  tool_call: new Set(["tool", "arguments", "call_id"]),
  tool_result: new Set(["text", "tool", "call_id", "ok", "tool_state", "write_receipt", "execution_receipt", "mcp_tool", "mcp_result"]),
  approval_required: new Set(["tool", "arguments", "call_id", "approval_id", "preview", "mcp_tool"]),
  approval_resolved: new Set(["text", "tool", "call_id", "approval_id", "ok", "mcp_tool"]),
  status: new Set(["text"]),
  error: new Set(["text"]),
  done: new Set(["turn_summary"]),
};

const OPTIONAL_EVENT_FIELDS = [
  "text",
  "reasoning",
  "stream_id",
  "stream_phase",
  "stream_status",
  "tool",
  "arguments",
  "call_id",
  "approval_id",
  "ok",
  "preview",
  "turn_summary",
  "tool_state",
  "write_receipt",
  "execution_receipt",
  "mcp_tool",
  "mcp_result",
] as const;

function isAgentMcpToolDescriptor(value: unknown): value is AgentMcpToolDescriptor {
  if (!isRecord(value) || Object.keys(value).sort().join(",") !==
    "contract_version,every_call_requires_native_approval,model_alias,server_title,source,tool_name,tool_title") return false;
  return value.contract_version === "agent-mcp-tool.v1"
    && value.source === "managed_mcp"
    && safeMcpDisplayText(value.server_title, 100)
    && safeMcpDisplayText(value.tool_name, 128)
    && (value.tool_title === null || safeMcpDisplayText(value.tool_title, 256))
    && typeof value.model_alias === "string"
    && Array.from(value.model_alias).length <= 64
    && MCP_ALIAS.test(value.model_alias)
    && value.every_call_requires_native_approval === true;
}

function isAgentMcpToolResultReceipt(value: unknown): value is AgentMcpToolResultReceipt {
  if (!isRecord(value) || Object.keys(value).sort().join(",") !==
    "arguments_persisted,cleanup_verified,content_mode,contract_version,error_code,managed_call_id,outcome,result_bytes,result_digest,result_text_persisted,reusable_approval_persisted") return false;
  const completed = value.outcome === "succeeded" || value.outcome === "tool_error";
  const failed = value.outcome === "failed" || value.outcome === "cancelled" || value.outcome === "timed_out";
  const notInvoked = value.outcome === "not_invoked";
  const digestPresent = typeof value.result_digest === "string" && DIGEST.test(value.result_digest);
  const errorPresent = typeof value.error_code === "string" && MCP_ERROR.test(value.error_code);
  return value.contract_version === "agent-mcp-tool-result.v1"
    && typeof value.managed_call_id === "string"
    && ID.test(value.managed_call_id)
    && (completed || failed || notInvoked)
    && (value.content_mode === "text" || value.content_mode === "structured_json"
      || value.content_mode === "text_and_structured_json" || value.content_mode === "none")
    && Number.isSafeInteger(value.result_bytes)
    && (value.result_bytes as number) >= 0
    && (value.result_bytes as number) <= 128 * 1024
    && (value.result_digest === null || digestPresent)
    && (value.error_code === null || errorPresent)
    && completed === digestPresent
    && failed === errorPresent
    && typeof value.cleanup_verified === "boolean"
    && value.arguments_persisted === false
    && value.result_text_persisted === false
    && value.reusable_approval_persisted === false
    && (!notInvoked || value.content_mode === "none"
      && value.result_bytes === 0
      && value.result_digest === null
      && value.error_code === null
      && value.cleanup_verified === true);
}

export function parseAgentEvent(value: unknown): AgentEvent {
  if (!isRecord(value) || Object.keys(value).some((key) => !EVENT_KEYS.has(key))) {
    throw new AgentEventPayloadError();
  }
  const kind = value.kind;
  const rawAttachments = value.attachments ?? [];
  if (
    typeof kind !== "string" ||
    !KINDS.has(kind as AgentEvent["kind"]) ||
    !Number.isSafeInteger(value.seq) ||
    (value.seq as number) <= 0 ||
    typeof value.at !== "string" ||
    !Number.isFinite(Date.parse(value.at)) ||
    !nullableString(value.text, 120_000) ||
    !nullableString(value.reasoning, 120_000) ||
    !nullableString(value.tool, 256) ||
    !nullableString(value.call_id, 256) ||
    !nullableString(value.approval_id, 64) ||
    !nullableString(value.preview, MAX_APPROVAL_PREVIEW_CHARS) ||
    !(value.ok === null || value.ok === undefined || typeof value.ok === "boolean") ||
    !(value.arguments === null || value.arguments === undefined || isRecord(value.arguments))
    || !Array.isArray(rawAttachments)
    || rawAttachments.length > 4
  ) {
    throw new AgentEventPayloadError();
  }
  let attachments;
  try {
    attachments = rawAttachments.map(parseAgentMessageAttachment);
  } catch {
    throw new AgentEventPayloadError();
  }
  if (
    (kind === "user" && !(typeof value.text === "string" && value.text.length > 0) && attachments.length === 0)
    || (kind !== "user" && attachments.length > 0)
    || new Set(attachments.map((attachment) => attachment.attachment_id)).size !== attachments.length
  ) throw new AgentEventPayloadError();
  const allowedFields = KIND_FIELDS[kind as AgentEvent["kind"]];
  if (OPTIONAL_EVENT_FIELDS.some((field) => value[field] != null && !allowedFields.has(field))) {
    throw new AgentEventPayloadError();
  }
  if (
    ((kind === "status" || kind === "error") && !(typeof value.text === "string" && value.text.length > 0))
    || ((kind === "tool_call" || kind === "tool_result")
      && !(typeof value.tool === "string" && value.tool.length > 0 && typeof value.call_id === "string" && value.call_id.length > 0))
    || (kind === "approval_required" && !(
      typeof value.tool === "string" && value.tool.length > 0
      && isRecord(value.arguments)
      && typeof value.approval_id === "string" && ID.test(value.approval_id)
    ))
    || (kind === "approval_resolved" && !(
      typeof value.tool === "string" && value.tool.length > 0
      && typeof value.approval_id === "string" && ID.test(value.approval_id)
      && typeof value.ok === "boolean"
    ))
    || (kind === "tool_result" && typeof value.ok !== "boolean")
  ) throw new AgentEventPayloadError();
  const streamId = value.stream_id;
  if ((value.turn_id != null && (typeof value.turn_id !== "string" || !ID.test(value.turn_id)))
    || (value.turn_summary != null && (kind !== "done" || typeof value.turn_id !== "string" || !isAgentTurnSummary(value.turn_summary, value.turn_id)))
    || (value.tool_state != null && (kind !== "tool_result" || !isAgentToolState(value.tool_state) || value.ok !== (value.tool_state === "succeeded")))
    || (value.write_receipt != null && (kind !== "tool_result" || value.tool !== "write_file" || !isAgentWriteReceipt(value.write_receipt)
      || value.tool_state !== (value.write_receipt.state === "verified" ? "succeeded" : "unverified")))
    || (value.execution_receipt != null && (kind !== "tool_result" || !isAgentToolExecutionReceipt(value.execution_receipt)))) {
    throw new AgentEventPayloadError();
  }
  if (
    (value.mcp_tool != null && (
      !isAgentMcpToolDescriptor(value.mcp_tool)
      || (kind !== "approval_required" && kind !== "approval_resolved" && kind !== "tool_result")
      || value.tool !== value.mcp_tool.model_alias
      || typeof value.call_id !== "string"
      || value.call_id.length === 0
    ))
    || (value.mcp_result != null && (
      kind !== "tool_result"
      || value.mcp_tool == null
      || !isAgentMcpToolResultReceipt(value.mcp_result)
    ))
  ) throw new AgentEventPayloadError();
  const streamPhase = value.stream_phase;
  const streamStatus = value.stream_status;
  if (kind === "assistant_delta") {
    if (
      typeof streamId !== "string" ||
      !ID.test(streamId) ||
      (streamPhase !== "content" && streamPhase !== "reasoning") ||
      streamStatus != null ||
      typeof value.text !== "string" ||
      value.text.length === 0 ||
      Array.from(value.text).length > MAX_DELTA_CHARS ||
      value.reasoning != null
    ) {
      throw new AgentEventPayloadError();
    }
  } else if (kind === "assistant") {
    const hasStream = typeof streamId === "string" && ID.test(streamId);
    const hasStatus = streamStatus === "complete" || streamStatus === "stopped" || streamStatus === "failed";
    if (streamPhase != null || hasStream !== hasStatus || (streamId != null && !hasStream) || (streamStatus != null && !hasStatus)) {
      throw new AgentEventPayloadError();
    }
  } else if (streamId != null || streamPhase != null || streamStatus != null || value.reasoning != null) {
    throw new AgentEventPayloadError();
  }
  return { ...value, attachments } as AgentEvent;
}

export function parseAgentEvents(
  value: unknown,
  expectedSessionId?: string,
  after = 0,
): AgentEvents {
  if (
    !isRecord(value) ||
    Object.keys(value).sort().join(",") !==
      "cleanup_unconfirmed,closing,contract_version,events,first_seq,last_seq,pending_approval_id,running,session_id,stopping" ||
    value.contract_version !== CONTRACT_VERSION ||
    typeof value.session_id !== "string" ||
    !ID.test(value.session_id) ||
    (expectedSessionId !== undefined && value.session_id !== expectedSessionId) ||
    !Array.isArray(value.events) ||
    value.events.length > MAX_EVENT_PAGE ||
    typeof value.running !== "boolean" ||
    typeof value.closing !== "boolean" ||
    typeof value.stopping !== "boolean" ||
    typeof value.cleanup_unconfirmed !== "boolean" ||
    (value.cleanup_unconfirmed && (!value.closing || value.pending_approval_id !== null)) ||
    (value.stopping && !value.running) ||
    !(value.pending_approval_id === null || (typeof value.pending_approval_id === "string" && ID.test(value.pending_approval_id))) ||
    !Number.isSafeInteger(value.last_seq) ||
    (value.last_seq as number) < 0 ||
    !Number.isSafeInteger(value.first_seq) ||
    (value.first_seq as number) < 0 ||
    ((value.last_seq as number) === 0) !== ((value.first_seq as number) === 0)
  ) {
    throw new AgentEventPayloadError();
  }
  const events = value.events.map(parseAgentEvent);
  let cursor = after;
  for (const event of events) {
    if (event.seq <= cursor || event.seq > (value.last_seq as number)) {
      throw new AgentEventPayloadError();
    }
    cursor = event.seq;
  }
  if (
    events.length > 0 &&
    ((value.first_seq as number) > events[0].seq || events.at(-1)?.seq !== cursor)
  ) {
    throw new AgentEventPayloadError();
  }
  return { ...value, events } as AgentEvents;
}

export function parseAgentSession(value: unknown, expectedSessionId?: string): AgentSessionView {
  if (!isRecord(value) || Object.keys(value).sort().join(",") !==
      "authority_revalidated,cleanup_unconfirmed,closing,contract_version,created_at,history_revision,history_write_failed,last_seq,model_alias,pending_approval_id,recovered,recovery_state,running,session_id,settings,stopping,turns"
    || value.contract_version !== CONTRACT_VERSION
    || typeof value.session_id !== "string" || !ID.test(value.session_id)
    || (expectedSessionId !== undefined && value.session_id !== expectedSessionId)
    || typeof value.running !== "boolean" || typeof value.closing !== "boolean"
    || typeof value.stopping !== "boolean" || (value.stopping && !value.running)
    || typeof value.cleanup_unconfirmed !== "boolean"
    || (value.cleanup_unconfirmed && (!value.closing || value.pending_approval_id !== null))
    || !(value.pending_approval_id === null || typeof value.pending_approval_id === "string" && ID.test(value.pending_approval_id))
    || !(value.model_alias === null || typeof value.model_alias === "string" && value.model_alias.length > 0 && value.model_alias.length <= 64)
    || typeof value.created_at !== "string" || !Number.isFinite(Date.parse(value.created_at))
    || !Number.isSafeInteger(value.last_seq) || (value.last_seq as number) < 0
    || !Number.isSafeInteger(value.turns) || (value.turns as number) < 0
    || !Number.isSafeInteger(value.history_revision) || (value.history_revision as number) < 0
    || typeof value.recovered !== "boolean"
    || typeof value.authority_revalidated !== "boolean"
    || typeof value.history_write_failed !== "boolean"
    || (value.recovery_state !== "current" && value.recovery_state !== "recovered" && value.recovery_state !== "interrupted")
    || (value.recovered !== (value.recovery_state !== "current"))
    || !isRecord(value.settings)) throw new AgentEventPayloadError();
  const settings = value.settings;
  const parameters = settings.parameters;
  const numberWithin = (candidate: unknown, min: number, max: number, integer = false) =>
    typeof candidate === "number" && Number.isFinite(candidate) && candidate >= min && candidate <= max
      && (!integer || Number.isInteger(candidate));
  if (Object.keys(settings).sort().join(",") !==
      "allow_commands,allow_web,allow_writes,command_timeout_seconds,instructions,max_steps,model_alias,parameters,project_id,retention_policy,title,workspace"
    || typeof settings.workspace !== "string" || settings.workspace.length < 1 || Array.from(settings.workspace).length > 1024
    || !(settings.project_id === null || typeof settings.project_id === "string" && ID.test(settings.project_id))
    || !(settings.model_alias === null || typeof settings.model_alias === "string" && Array.from(settings.model_alias).length <= 64)
    || !(settings.title === null || typeof settings.title === "string" && Array.from(settings.title).length <= 120)
    || !(settings.instructions === null || typeof settings.instructions === "string" && Array.from(settings.instructions).length <= 4000)
    || typeof settings.allow_commands !== "boolean" || typeof settings.allow_writes !== "boolean" || typeof settings.allow_web !== "boolean"
    || (settings.retention_policy !== "metadata_only" && settings.retention_policy !== "local_history")
    || (value.history_write_failed === true && settings.retention_policy !== "local_history")
    || !numberWithin(settings.command_timeout_seconds, 5, 600, true) || !numberWithin(settings.max_steps, 1, 16, true)
    || !isRecord(parameters) || Object.keys(parameters).sort().join(",") !== "enable_thinking,max_tokens,temperature,top_p"
    || !numberWithin(parameters.temperature, 0, 2) || !numberWithin(parameters.top_p, Number.MIN_VALUE, 1)
    || !numberWithin(parameters.max_tokens, 64, 8192, true) || typeof parameters.enable_thinking !== "boolean") {
    throw new AgentEventPayloadError();
  }
  return value as AgentSessionView;
}
