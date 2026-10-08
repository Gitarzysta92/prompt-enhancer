import { describe, expect, it } from "vitest";

import {
  AgentOrchestrationPayloadError,
  parseAgentOrchestrationManifest,
} from "./agentOrchestrationContract";
import { exampleAgentOrchestrationManifest } from "./agentOrchestrationFixtures.test-support";

describe("agent controller manifest contract", () => {
  it("accepts the complete provider-neutral v21 shape", () => {
    const fixture = exampleAgentOrchestrationManifest();

    const parsed = parseAgentOrchestrationManifest(fixture);

    expect(parsed.contract_version).toBe("local-agent-orchestration.v22");
    expect(parsed.endpoints).toHaveLength(77);
    expect(parsed.endpoints.filter((item) => item.access === "native_user_presence_only"))
      .toHaveLength(12);
  });

  it("rejects incomplete, duplicate, remote, and downgraded manifests", () => {
    const incomplete = structuredClone(exampleAgentOrchestrationManifest()) as unknown as Record<string, unknown>;
    (incomplete.endpoints as unknown[]).pop();
    expect(() => parseAgentOrchestrationManifest(incomplete))
      .toThrow(AgentOrchestrationPayloadError);

    const duplicate = structuredClone(exampleAgentOrchestrationManifest());
    duplicate.endpoints[1].operation = duplicate.endpoints[0].operation;
    expect(() => parseAgentOrchestrationManifest(duplicate))
      .toThrow(AgentOrchestrationPayloadError);

    const remote = structuredClone(exampleAgentOrchestrationManifest());
    remote.endpoints[0].path_template = "https://example.invalid/v1/agent/orchestration";
    expect(() => parseAgentOrchestrationManifest(remote))
      .toThrow(AgentOrchestrationPayloadError);

    const downgraded = structuredClone(exampleAgentOrchestrationManifest()) as unknown as Record<string, unknown>;
    downgraded.contract_version = "local-agent-orchestration.v3";
    expect(() => parseAgentOrchestrationManifest(downgraded))
      .toThrow(AgentOrchestrationPayloadError);
  });

  it("rejects token disclosure and falsely token-approved native effects", () => {
    const token = structuredClone(exampleAgentOrchestrationManifest()) as unknown as Record<string, unknown>;
    (token.authentication as Record<string, unknown>).token = "synthetic-secret";
    expect(() => parseAgentOrchestrationManifest(token))
      .toThrow(AgentOrchestrationPayloadError);

    const unsafe = structuredClone(exampleAgentOrchestrationManifest());
    unsafe.boundaries!.token_controller_may_approve = true as false;
    expect(() => parseAgentOrchestrationManifest(unsafe))
      .toThrow(AgentOrchestrationPayloadError);
  });
});
