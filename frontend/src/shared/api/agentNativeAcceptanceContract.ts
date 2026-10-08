import type { AgentNativeAcceptanceStartReceipt } from "./contracts";

const KEYS = new Set([
  "contract_version",
  "owner_presence_confirmed",
  "model_execution_started",
  "process_spawn_requested",
  "workspace_access_requested",
  "content_persisted",
  "expires_on_reload",
]);

export class AgentNativeAcceptancePayloadError extends Error {
  constructor() {
    super("Agent native acceptance response was invalid");
    this.name = "AgentNativeAcceptancePayloadError";
  }
}

export function parseAgentNativeAcceptanceStartReceipt(
  value: unknown,
): AgentNativeAcceptanceStartReceipt {
  if (
    typeof value !== "object"
    || value === null
    || Array.isArray(value)
    || Object.keys(value).length !== KEYS.size
    || Object.keys(value).some((key) => !KEYS.has(key))
  ) throw new AgentNativeAcceptancePayloadError();
  const receipt = value as Record<string, unknown>;
  if (
    receipt.contract_version !== "agent-native-acceptance-start.v1"
    || receipt.owner_presence_confirmed !== true
    || receipt.model_execution_started !== false
    || receipt.process_spawn_requested !== false
    || receipt.workspace_access_requested !== false
    || receipt.content_persisted !== false
    || receipt.expires_on_reload !== true
  ) throw new AgentNativeAcceptancePayloadError();
  return receipt as unknown as AgentNativeAcceptanceStartReceipt;
}
