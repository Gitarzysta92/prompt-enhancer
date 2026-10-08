import { describe, expect, it } from "vitest";

import {
  AgentHardeningPayloadError,
  parseAgentHardeningSnapshot,
} from "./agentHardeningContract";

function exampleSnapshot() {
  return {
    contract_version: "agent-hardening.v1",
    generated_on_demand: true,
    contains_content: false,
    recovery_state: "attention_required",
    recovery_actions: ["resume_interrupted_read_only"],
    catalog: {
      state: "ready",
      reason_code: null,
      schema_version: 30,
      quick_check_passed: true,
      foreign_key_violations_observed: 0,
      foreign_key_scan_truncated: false,
      projection_violations: 0,
      counts: {
        projects: 1,
        archived_projects: 0,
        sessions: 2,
        archived_sessions: 0,
        metadata_only_sessions: 1,
        retained_sessions: 1,
        history_events: 4,
        interrupted_retained_sessions: 1,
        artifacts: 0,
        artifact_versions: 0,
        staged_attachments: 0,
        attached_attachments: 0,
      },
    },
    live: {
      state: "ready",
      reason_code: null,
      counts: {
        sessions: 0,
        running_turns: 0,
        closing_sessions: 0,
        pending_approvals: 0,
        cleanup_unconfirmed: 0,
        command_cleanup_quarantined: false,
        recovered_read_only: 0,
        history_write_failures: 0,
        shutting_down: false,
      },
    },
  };
}

describe("parseAgentHardeningSnapshot", () => {
  it("accepts only the closed content-free aggregate contract", () => {
    const parsed = parseAgentHardeningSnapshot(exampleSnapshot());

    expect(parsed.catalog.counts?.sessions).toBe(2);
    expect(parsed.catalog.schema_version).toBe(30);
    expect(parsed.recovery_actions).toEqual(["resume_interrupted_read_only"]);
    expect(JSON.stringify(parsed)).not.toContain("workspace");
  });

  it("accepts the fixed content-free migration-invalid diagnostic", () => {
    const value: any = exampleSnapshot();
    value.recovery_state = "unknown";
    value.recovery_actions = [];
    value.catalog = {
      state: "unavailable",
      reason_code: "catalog_migration_invalid",
      schema_version: null,
      quick_check_passed: null,
      foreign_key_violations_observed: null,
      foreign_key_scan_truncated: false,
      projection_violations: null,
      counts: null,
    };

    const parsed = parseAgentHardeningSnapshot(value);
    expect(parsed.catalog.reason_code).toBe("catalog_migration_invalid");
    expect(JSON.stringify(parsed)).not.toContain("checksum");
  });

  it.each([
    ["an extra content field", (value: any) => { value.prompt = "private"; }],
    ["an invalid retention subtotal", (value: any) => { value.catalog.counts.retained_sessions = 2; }],
    ["a ready integrity mismatch", (value: any) => { value.catalog.projection_violations = 1; }],
    ["a live subcount larger than sessions", (value: any) => { value.live.counts.running_turns = 1; }],
    ["a duplicate recovery action", (value: any) => { value.recovery_actions.push("resume_interrupted_read_only"); }],
    ["an invalid schema head", (value: any) => { value.catalog.schema_version = 0; }],
  ])("rejects %s", (_label, mutate) => {
    const value = exampleSnapshot();
    mutate(value);

    expect(() => parseAgentHardeningSnapshot(value)).toThrow(
      AgentHardeningPayloadError,
    );
  });
});
