import { describe, expect, it } from "vitest";

import {
  AgentNativeAcceptancePayloadError,
  parseAgentNativeAcceptanceStartReceipt,
} from "./agentNativeAcceptanceContract";

const RECEIPT = {
  contract_version: "agent-native-acceptance-start.v1",
  owner_presence_confirmed: true,
  model_execution_started: false,
  process_spawn_requested: false,
  workspace_access_requested: false,
  content_persisted: false,
  expires_on_reload: true,
} as const;

describe("Agent native acceptance contract", () => {
  it("accepts the exact content-free non-spawning receipt", () => {
    expect(parseAgentNativeAcceptanceStartReceipt(RECEIPT)).toEqual(RECEIPT);
  });

  it.each([
    null,
    [],
    { ...RECEIPT, model_execution_started: true },
    { ...RECEIPT, process_spawn_requested: true },
    { ...RECEIPT, workspace_access_requested: true },
    { ...RECEIPT, content_persisted: true },
    { ...RECEIPT, model_alias: "synthetic-model" },
  ])("rejects malformed or broadened authority %#", (candidate) => {
    expect(() => parseAgentNativeAcceptanceStartReceipt(candidate)).toThrow(
      AgentNativeAcceptancePayloadError,
    );
  });
});
