import { describe, expect, it } from "vitest";
import { parseAgentChangeDiff, parseAgentChangeSet } from "./agentChangeSetContract";

const SESSION = "a".repeat(32);

function file(overrides: Record<string, unknown> = {}) {
  return {
    path: "src/example.ts",
    net_effect: "modified",
    verification: "verified",
    reason: null,
    reviewed_writes: 2,
    agent_writes: 1,
    manual_writes: 1,
    current_byte_size: 20,
    diff_available: true,
    ...overrides,
  };
}

function changeSet(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-change-set.v1",
    session_id: SESSION,
    scope: "reviewed_paths_only",
    coverage: "complete",
    settled: true,
    reviewed_writes: 2,
    verified_writes: 2,
    unverified_writes: 0,
    agent_writes: 1,
    manual_writes: 1,
    reviewed_noops: 0,
    command_attempts: 0,
    omitted_write_receipts: 0,
    tracking_failed: false,
    files: [file()],
    ...overrides,
  };
}

describe("Agent change-set transport contract", () => {
  it("accepts an exact, coherent reviewed-path inventory and net diff", () => {
    const parsed = parseAgentChangeSet(changeSet(), SESSION);
    expect(parsed.files[0].path).toBe("src/example.ts");
    expect(parsed.coverage).toBe("complete");

    const detail = parseAgentChangeDiff({
      contract_version: "agent-change-set.v1",
      session_id: SESSION,
      summary: file(),
      diff_state: "available",
      diff: "--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-old\n+new",
      added_lines: 1,
      removed_lines: 1,
    }, SESSION, "src/example.ts");
    expect(detail.diff_state).toBe("available");
  });

  it("accepts an explicit zero-line diff for an empty file creation", () => {
    const detail = parseAgentChangeDiff({
      contract_version: "agent-change-set.v1",
      session_id: SESSION,
      summary: file({
        path: "empty.txt",
        net_effect: "created",
        reviewed_writes: 1,
        agent_writes: 1,
        manual_writes: 0,
        current_byte_size: 0,
      }),
      diff_state: "available",
      diff: "--- /dev/null\n+++ b/empty.txt\n@@ -0,0 +0,0 @@",
      added_lines: 0,
      removed_lines: 0,
    }, SESSION, "empty.txt");
    expect(detail).toMatchObject({ diff_state: "available", added_lines: 0, removed_lines: 0 });
  });

  it.each([
    ["wrong session", { session_id: "b".repeat(32) }],
    ["wrong totals", { verified_writes: 1 }],
    ["unknown field", { extra: true }],
    ["false complete coverage", { command_attempts: 1 }],
  ])("rejects a %s", (_name, override) => {
    expect(() => parseAgentChangeSet(changeSet(override), SESSION)).toThrow();
  });

  it("rejects duplicated, escaping, and authority-incoherent file entries", () => {
    expect(() => parseAgentChangeSet(changeSet({ files: [file(), file()] }), SESSION)).toThrow();
    expect(() => parseAgentChangeSet(changeSet({ files: [file({ path: "../secret" })] }), SESSION)).toThrow();
    expect(() => parseAgentChangeSet(changeSet({
      coverage: "partial",
      files: [file({ verification: "partial", reason: null })],
    }), SESSION)).toThrow();
    expect(() => parseAgentChangeSet(changeSet({
      files: [file({ net_effect: "created", current_byte_size: null })],
    }), SESSION)).toThrow();
    expect(() => parseAgentChangeSet(changeSet({
      reviewed_writes: 1,
      verified_writes: 1,
      agent_writes: 1,
      manual_writes: 0,
      files: [file({ reviewed_writes: 2, agent_writes: 2, manual_writes: 0 })],
    }), SESSION)).toThrow();
  });

  it("accepts an explicitly partial unverified publication", () => {
    const parsed = parseAgentChangeSet(changeSet({
      coverage: "partial",
      reviewed_writes: 1,
      verified_writes: 0,
      unverified_writes: 1,
      agent_writes: 1,
      manual_writes: 0,
      files: [file({
        verification: "unverified",
        reason: "publication_unverified",
        reviewed_writes: 1,
        agent_writes: 1,
        manual_writes: 0,
      })],
    }), SESSION);
    expect(parsed.coverage).toBe("partial");
    expect(parsed.files[0].verification).toBe("unverified");
  });

  it.each([
    ["wrong path", { summary: file({ path: "src/other.ts" }) }],
    ["bad headers", { diff: "--- a/other.ts\n+++ b/other.ts\n@@ -1 +1 @@\n-old\n+new" }],
    ["text in no-change", { diff_state: "no_change", diff: "text", added_lines: 0, removed_lines: 0 }],
    ["missing counts", { added_lines: null }],
    ["missing oversized counts", { diff_state: "too_large", diff: null, added_lines: null, removed_lines: null }],
    ["wrong line-ending effect", {
      summary: file({ net_effect: "created" }),
      diff_state: "line_ending_only",
      diff: null,
      added_lines: 0,
      removed_lines: 0,
    }],
  ])("rejects a change diff with %s", (_name, override) => {
    const payload = {
      contract_version: "agent-change-set.v1",
      session_id: SESSION,
      summary: file(),
      diff_state: "available",
      diff: "--- a/src/example.ts\n+++ b/src/example.ts\n@@ -1 +1 @@\n-old\n+new",
      added_lines: 1,
      removed_lines: 1,
      ...override,
    };
    expect(() => parseAgentChangeDiff(payload, SESSION, "src/example.ts")).toThrow();
  });
});
