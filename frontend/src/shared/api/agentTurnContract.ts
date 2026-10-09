import type { AgentTokenUsage, AgentToolExecutionReceipt, AgentTurnSummary, AgentWriteReceipt } from "./contracts";

const ID = /^[a-f0-9]{32}$/;
const HASH = /^[a-f0-9]{64}$/;
const TOOL_STATES = new Set(["succeeded", "failed", "not_approved", "cancelled", "unverified"]);
const TOOL_APPROVAL_STATES = new Set(["not_required", "not_requested", "approved", "denied", "timed_out", "cancelled_before_decision"]);
const TOOL_EVIDENCE_STATES = new Set(["read_only_observation", "verified_workspace_effect", "unverified_workspace_effect", "untracked_external_effect", "no_effect", "unknown"]);
const REASONS = new Set(["answer_complete", "stop_requested", "step_limit", "model_response_limit", "model_response_filtered", "model_completion_unrecognized", "model_stream_incomplete", "model_stream_failed", "model_reply_unusable", "model_reply_too_large", "model_answer_missing", "runtime_unreachable", "runtime_http_error", "turn_failed", "command_cleanup_unconfirmed", "context_window_exceeded", "inference_not_authorized"]);
const WRITE_KEYS = new Set(["contract_version", "source", "path", "state", "operation", "before_sha256", "after_sha256", "added_lines", "removed_lines", "byte_size", "line_count_version"]);
const EXECUTION_KEYS = new Set(["contract_version", "elapsed_ms", "timing_source", "approval_state", "evidence_state"]);
const USAGE_KEYS = new Set(["contract_version", "source", "state", "model_requests", "reported_requests", "prompt_tokens", "completion_tokens", "total_tokens", "cached_prompt_tokens", "reasoning_tokens"]);
const TURN_KEYS = new Set(["contract_version", "turn_id", "turn_number", "model_alias", "status", "reason", "started_at", "finished_at", "duration_ms", "model_wait_ms", "time_to_first_text_ms", "timing_source", "usage", "tools_requested", "tools_succeeded", "tools_failed", "tools_not_approved", "tools_cancelled", "tools_unverified", "untracked_command_calls", "writes"]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
}
function nullableInteger(value: unknown, max = Number.MAX_SAFE_INTEGER) {
  return value == null || integer(value, max);
}
function duration(value: unknown): boolean {
  return value == null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
}
export function isAgentToolState(value: unknown): boolean {
  return typeof value === "string" && TOOL_STATES.has(value);
}

export function isAgentToolExecutionReceipt(value: unknown): value is AgentToolExecutionReceipt {
  if (!record(value)
    || Object.keys(value).length !== EXECUTION_KEYS.size
    || Object.keys(value).some((key) => !EXECUTION_KEYS.has(key))
    || value.contract_version !== "agent-tool-execution.v1"
    || value.timing_source !== "server_monotonic.v1"
    || !duration(value.elapsed_ms)
    || typeof value.approval_state !== "string" || !TOOL_APPROVAL_STATES.has(value.approval_state)
    || typeof value.evidence_state !== "string" || !TOOL_EVIDENCE_STATES.has(value.evidence_state)) return false;
  const noExecution = new Set(["not_requested", "denied", "timed_out", "cancelled_before_decision"]);
  const protectedEffects = new Set(["verified_workspace_effect", "unverified_workspace_effect", "untracked_external_effect"]);
  if (noExecution.has(value.approval_state) && value.evidence_state !== "no_effect") return false;
  if (protectedEffects.has(value.evidence_state) && value.approval_state !== "approved") return false;
  if (value.evidence_state === "read_only_observation" && value.approval_state !== "not_required") return false;
  return value.approval_state !== "not_required"
    || value.evidence_state === "read_only_observation"
    || value.evidence_state === "no_effect";
}

export function isAgentWriteReceipt(value: unknown): value is AgentWriteReceipt {
  if (!record(value) || Object.keys(value).some((key) => !WRITE_KEYS.has(key))
    || value.contract_version !== "agent-write.v1" || value.source !== "reviewed_write_file"
    || value.line_count_version !== "line-sequence-diff.v1" || typeof value.path !== "string"
    || value.path.length === 0 || Array.from(value.path).length > 1024 || /[\\:\u0000-\u001f\u007f]/.test(value.path)
    || value.path.split("/").some((part) => part === "" || part === "." || part === "..")
    || !(value.before_sha256 == null || typeof value.before_sha256 === "string" && HASH.test(value.before_sha256))) return false;
  const facts = [value.operation, value.after_sha256, value.added_lines, value.removed_lines, value.byte_size];
  if (value.state === "unverified") return facts.every((field) => field == null);
  if (value.state !== "verified" || !["created", "modified", "unchanged"].includes(String(value.operation))
    || typeof value.after_sha256 !== "string" || !HASH.test(value.after_sha256)
    || !integer(value.added_lines, 256001) || !integer(value.removed_lines, 256001) || !integer(value.byte_size, 256000)) return false;
  return (value.operation === "created") === (value.before_sha256 == null)
    && (value.operation === "unchanged") === (value.before_sha256 === value.after_sha256)
    && (value.operation !== "unchanged" || value.added_lines === 0 && value.removed_lines === 0);
}

function isUsage(value: unknown): value is AgentTokenUsage {
  if (!record(value) || Object.keys(value).some((key) => !USAGE_KEYS.has(key))
    || value.contract_version !== "agent-token-usage.v1" || value.source !== "runtime_reported"
    || !["reported", "partial", "unavailable", "invalid"].includes(String(value.state))
    || !integer(value.model_requests, 16) || !integer(value.reported_requests, value.model_requests)) return false;
  const counts = [value.prompt_tokens, value.completion_tokens, value.total_tokens, value.cached_prompt_tokens, value.reasoning_tokens];
  if (!counts.every((count) => nullableInteger(count))) return false;
  if (["invalid", "unavailable"].includes(String(value.state)) && counts.some((count) => count != null)) return false;
  if (value.state === "unavailable" && value.reported_requests !== 0) return false;
  if (value.state === "reported" && (value.model_requests === 0 || value.reported_requests !== value.model_requests || counts.slice(0, 3).some((count) => count == null))) return false;
  if (value.state === "partial" && (value.model_requests === 0 || value.reported_requests === value.model_requests || counts.slice(0, 3).every((count) => count != null))) return false;
  const { prompt_tokens: prompt, completion_tokens: completion, total_tokens: total, cached_prompt_tokens: cached, reasoning_tokens: reasoning } = value;
  if (typeof total === "number" && ((typeof prompt === "number" && total < prompt) || (typeof completion === "number" && total < completion))) return false;
  if (typeof prompt === "number" && typeof completion === "number" && typeof total === "number" && prompt + completion !== total) return false;
  if (typeof cached === "number" && typeof prompt === "number" && cached > prompt) return false;
  return !(typeof reasoning === "number" && typeof completion === "number" && reasoning > completion);
}

export function isAgentTurnSummary(value: unknown, turnId?: string | null): value is AgentTurnSummary {
  if (!record(value) || Object.keys(value).some((key) => !TURN_KEYS.has(key))
    || value.contract_version !== "agent-turn.v1" || typeof value.turn_id !== "string" || !ID.test(value.turn_id)
    || (turnId !== undefined && value.turn_id !== turnId) || !integer(value.turn_number) || value.turn_number === 0
    || typeof value.model_alias !== "string" || value.model_alias.length === 0 || value.model_alias.length > 64
    || typeof value.reason !== "string" || !REASONS.has(value.reason)
    || typeof value.started_at !== "string" || !Number.isFinite(Date.parse(value.started_at))
    || typeof value.finished_at !== "string" || !Number.isFinite(Date.parse(value.finished_at))
    || value.timing_source !== "server_monotonic.v1" || !isUsage(value.usage)
    || ![value.duration_ms, value.model_wait_ms, value.time_to_first_text_ms].every(duration)
    || !Array.isArray(value.writes) || value.writes.length > 128 || !value.writes.every(isAgentWriteReceipt)) return false;
  const expected = value.reason === "answer_complete" ? "completed" : value.reason === "stop_requested" ? "stopped" : value.reason === "step_limit" ? "step_limit" : "failed";
  if (value.status !== expected) return false;
  const tools = [value.tools_succeeded, value.tools_failed, value.tools_not_approved, value.tools_cancelled, value.tools_unverified];
  if (!tools.every((count) => integer(count, 128)) || !integer(value.tools_requested, 128)
    || tools.reduce<number>((sum, count) => sum + (count as number), 0) !== value.tools_requested
    || !integer(value.untracked_command_calls, value.tools_requested)
    || value.writes.length + value.untracked_command_calls > value.tools_requested) return false;
  if (value.writes.filter((write) => write.state === "verified").length > (value.tools_succeeded as number)
    || value.writes.filter((write) => write.state === "unverified").length > (value.tools_unverified as number)) return false;
  return typeof value.duration_ms !== "number" || [value.model_wait_ms, value.time_to_first_text_ms].every((part) => part == null || (part as number) <= (value.duration_ms as number) + 0.001);
}
