import type { AgentSessionView } from "./contracts";

export function exampleAgentSession(overrides: Partial<AgentSessionView> = {}): AgentSessionView {
  return {
    contract_version: "local-agent.v9", session_id: "a".repeat(32),
    closing: false, stopping: false, cleanup_unconfirmed: false, running: false,
    created_at: "2026-08-20T01:00:00Z", last_seq: 0, pending_approval_id: null,
    model_alias: "example-model", turns: 0, history_revision: 0,
    recovered: false, authority_revalidated: true, history_write_failed: false,
    recovery_state: "current",
    settings: {
      workspace: "D:\\example\\workspace", project_id: "b".repeat(32),
      model_alias: "example-model", title: "Example workspace",
      instructions: null, allow_commands: true, allow_writes: true, allow_web: false,
      retention_policy: "metadata_only",
      max_steps: 10, command_timeout_seconds: 120,
      parameters: { temperature: 0.2, top_p: 0.95, max_tokens: 1400, enable_thinking: false },
    },
    ...overrides,
  };
}
