import type { AgentTokenUsage, AgentTurnSummary, AgentWriteReceipt } from "../../shared/api/contracts";

export function exampleWriteReceipt(overrides: Partial<AgentWriteReceipt> = {}): AgentWriteReceipt {
  return { contract_version: "agent-write.v1", source: "reviewed_write_file", path: "example.txt", state: "verified", operation: "modified", before_sha256: "c".repeat(64), after_sha256: "d".repeat(64), added_lines: 2, removed_lines: 1, byte_size: 24, line_count_version: "line-sequence-diff.v1", ...overrides };
}
export function exampleTokenUsage(overrides: Partial<AgentTokenUsage> = {}): AgentTokenUsage {
  return { contract_version: "agent-token-usage.v1", source: "runtime_reported", state: "reported", model_requests: 1, reported_requests: 1, prompt_tokens: 11, completion_tokens: 7, total_tokens: 18, cached_prompt_tokens: null, reasoning_tokens: null, ...overrides };
}
export function exampleAgentTurn(overrides: Partial<AgentTurnSummary> = {}): AgentTurnSummary {
  return { contract_version: "agent-turn.v1", turn_id: "e".repeat(32), turn_number: 1, model_alias: "example-model", status: "completed", reason: "answer_complete", started_at: "2026-08-26T10:00:00Z", finished_at: "2026-08-26T10:00:02Z", duration_ms: 2000, model_wait_ms: 1500, time_to_first_text_ms: 200, timing_source: "server_monotonic.v1", usage: exampleTokenUsage(), tools_requested: 1, tools_succeeded: 1, tools_failed: 0, tools_not_approved: 0, tools_cancelled: 0, tools_unverified: 0, untracked_command_calls: 0, writes: [exampleWriteReceipt()], ...overrides };
}
