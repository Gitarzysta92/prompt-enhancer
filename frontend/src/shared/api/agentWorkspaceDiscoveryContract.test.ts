import { describe, expect, it } from "vitest";
import {
  AgentWorkspaceDiscoveryPayloadError,
  parseAgentWorkspaceDiscovery,
} from "./agentWorkspaceDiscoveryContract";

const SESSION = "a".repeat(32);

function payload(): Record<string, unknown> {
  return {
    contract_version: "local-agent-workspace-discovery.v1",
    session_id: SESSION,
    scope: "selected_workspace",
    inventory_coverage: "partial",
    inventory_reasons: ["excluded_directories"],
    scanned_entry_count: 4,
    observed_file_count: 2,
    files: [
      { path: "notes.txt", byte_size: 20, editable_candidate: true },
      { path: "src/example.ts", byte_size: 40, editable_candidate: true },
    ],
    git_state: "available",
    git_coverage: "complete",
    git_reasons: [],
    git_change_count: 2,
    git_changes: [
      { path: "notes.txt", kind: "untracked", staged: false, unstaged: false },
      { path: "src/example.ts", kind: "modified", staged: false, unstaged: true },
    ],
  };
}

describe("parseAgentWorkspaceDiscovery", () => {
  it("accepts one exact content-free session-bound snapshot", () => {
    const parsed = parseAgentWorkspaceDiscovery(payload(), SESSION);
    expect(parsed.inventory_coverage).toBe("partial");
    expect(parsed.files.map((item) => item.path)).toEqual(["notes.txt", "src/example.ts"]);
    expect(parsed.git_change_count).toBe(2);
    expect(parsed.git_changes[1]).toEqual({
      path: "src/example.ts",
      kind: "modified",
      staged: false,
      unstaged: true,
    });
  });

  it("accepts a complete non-repository inventory", () => {
    const value = payload();
    value.inventory_coverage = "complete";
    value.inventory_reasons = [];
    value.scanned_entry_count = 2;
    value.git_state = "not_repository";
    value.git_coverage = "not_applicable";
    value.git_change_count = 0;
    value.git_changes = [];
    expect(parseAgentWorkspaceDiscovery(value, SESSION).git_state).toBe("not_repository");
  });

  it("uses the contract's UTF-8 byte ordering for non-BMP paths", () => {
    const value = payload();
    value.files = [
      { path: "\ue000.txt", byte_size: 1, editable_candidate: true },
      { path: "😀.txt", byte_size: 1, editable_candidate: true },
    ];
    expect(parseAgentWorkspaceDiscovery(value, SESSION).files.map((item) => item.path)).toEqual([
      "\ue000.txt",
      "😀.txt",
    ]);
  });

  it.each([
    ["extra field", (value: Record<string, unknown>) => { value.private_detail = "EXAMPLE_PRIVATE_CANARY"; }],
    ["wrong session", (value: Record<string, unknown>) => { value.session_id = "b".repeat(32); }],
    ["unsafe path", (value: Record<string, unknown>) => {
      (value.files as Record<string, unknown>[])[0].path = "../private.txt";
    }],
    ["unpaired surrogate path", (value: Record<string, unknown>) => {
      (value.files as Record<string, unknown>[])[0].path = "bad\ud800.txt";
    }],
    ["unsorted paths", (value: Record<string, unknown>) => {
      value.files = [...(value.files as unknown[])].reverse();
    }],
    ["duplicate reasons", (value: Record<string, unknown>) => {
      value.inventory_reasons = ["excluded_directories", "excluded_directories"];
    }],
    ["complete omission", (value: Record<string, unknown>) => {
      value.inventory_coverage = "complete";
    }],
    ["invalid editable size", (value: Record<string, unknown>) => {
      (value.files as Record<string, unknown>[])[0].byte_size = 256_001;
    }],
    ["incoherent Git count", (value: Record<string, unknown>) => {
      value.git_change_count = 1;
    }],
    ["untracked staging", (value: Record<string, unknown>) => {
      (value.git_changes as Record<string, unknown>[])[0].staged = true;
    }],
    ["unavailable with changes", (value: Record<string, unknown>) => {
      value.git_state = "unavailable";
      value.git_coverage = "unavailable";
      value.git_reasons = ["status_failed"];
      value.git_change_count = null;
    }],
  ])("rejects %s", (_label, mutate) => {
    const value = payload();
    mutate(value);
    expect(() => parseAgentWorkspaceDiscovery(value, SESSION)).toThrow(AgentWorkspaceDiscoveryPayloadError);
  });
});
