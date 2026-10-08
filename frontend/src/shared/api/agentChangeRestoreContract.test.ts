import { describe, expect, it } from "vitest";
import {
  parseAgentChangeRestorePreview,
  parseAgentChangeRestoreResult,
} from "./agentChangeRestoreContract";

const SESSION = "a".repeat(32);
const PATH = "src/example.ts";
const CURRENT = "b".repeat(64);
const BASELINE = "c".repeat(64);

function editPreview(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-change-restore.v1",
    session_id: SESSION,
    preview_id: "d".repeat(32),
    path: PATH,
    operation: "edit",
    baseline_state: "present",
    expected_revision: CURRENT,
    restored_revision: BASELINE,
    restored_byte_size: 12,
    line_ending: "lf",
    diff_state: "available",
    diff: `--- a/${PATH}\n+++ b/${PATH}\n@@ -1 +1 @@\n-current\n+baseline`,
    added_lines: 1,
    removed_lines: 1,
    recovery: "revision_bound_write",
    permanent: false,
    expires_at: "2030-01-02T03:04:05Z",
    requires_native_confirmation: true,
    ...overrides,
  };
}

function result(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-change-restore.v1",
    session_id: SESSION,
    path: PATH,
    operation: "edit",
    baseline_state: "present",
    current_revision: BASELINE,
    current_byte_size: 12,
    recovery: "revision_bound_write",
    permanent: false,
    net_effect: "reverted",
    filesystem_verification: "verified",
    change_set_verification: "verified",
    change_set_reason: null,
    applied: true,
    ...overrides,
  };
}

describe("Agent reviewed-path restore transport contract", () => {
  it("accepts exact edit, recreate, and recoverable-trash previews", () => {
    expect(parseAgentChangeRestorePreview(editPreview(), SESSION, PATH)).toMatchObject({
      operation: "edit",
      recovery: "revision_bound_write",
    });

    expect(parseAgentChangeRestorePreview(editPreview({
      operation: "recreate",
      expected_revision: null,
      diff: `--- /dev/null\n+++ b/${PATH}\n@@ -0,0 +1 @@\n+baseline`,
      added_lines: 1,
      removed_lines: 0,
    }), SESSION, PATH)).toMatchObject({ operation: "recreate", expected_revision: null });

    expect(parseAgentChangeRestorePreview(editPreview({
      operation: "trash_created",
      baseline_state: "absent",
      restored_revision: null,
      restored_byte_size: null,
      line_ending: null,
      recovery: "windows_recycle_bin",
      diff: `--- a/${PATH}\n+++ /dev/null\n@@ -1 +0,0 @@\n-current`,
      added_lines: 0,
      removed_lines: 1,
    }), SESSION, PATH)).toMatchObject({
      operation: "trash_created",
      recovery: "windows_recycle_bin",
      permanent: false,
    });
  });

  it("accepts content-free line-ending and oversized previews", () => {
    expect(parseAgentChangeRestorePreview(editPreview({
      diff_state: "line_ending_only",
      diff: null,
      added_lines: 0,
      removed_lines: 0,
      line_ending: "crlf",
    }), SESSION, PATH)).toMatchObject({ diff_state: "line_ending_only", diff: null });
    expect(parseAgentChangeRestorePreview(editPreview({
      diff_state: "too_large",
      diff: null,
      added_lines: 50_001,
      removed_lines: 50_001,
    }), SESSION, PATH)).toMatchObject({ diff_state: "too_large", diff: null });
  });

  it.each([
    ["extra field", { extra: true }],
    ["wrong session", { session_id: "e".repeat(32) }],
    ["wrong path", { path: "src/other.ts" }],
    ["escaping path", { path: "../private.txt" }],
    ["invalid expiry", { expires_at: "2030-01-02" }],
    ["wrong diff header", { diff: `--- a/other.ts\n+++ b/${PATH}\n@@ -1 +1 @@\n-old\n+new` }],
    ["missing edit authority", { expected_revision: null }],
    ["permanent trash", { permanent: true }],
  ])("rejects a preview with %s", (_name, override) => {
    expect(() => parseAgentChangeRestorePreview(editPreview(override), SESSION, PATH)).toThrow();
  });

  it("rejects contradictory recreate, trash, and line-ending envelopes", () => {
    expect(() => parseAgentChangeRestorePreview(editPreview({
      operation: "recreate",
      diff: `--- /dev/null\n+++ b/${PATH}\n@@ -0,0 +1 @@\n+baseline`,
    }), SESSION, PATH)).toThrow();
    expect(() => parseAgentChangeRestorePreview(editPreview({
      operation: "trash_created",
      baseline_state: "absent",
      recovery: "windows_recycle_bin",
    }), SESSION, PATH)).toThrow();
    expect(() => parseAgentChangeRestorePreview(editPreview({
      operation: "recreate",
      expected_revision: null,
      diff_state: "line_ending_only",
      diff: null,
      added_lines: 0,
      removed_lines: 0,
    }), SESSION, PATH)).toThrow();
  });

  it("accepts objectively verified, partial, and tracking-unavailable results", () => {
    expect(parseAgentChangeRestoreResult(result(), SESSION, PATH, "edit")).toMatchObject({
      filesystem_verification: "verified",
      change_set_verification: "verified",
    });
    expect(parseAgentChangeRestoreResult(result({
      change_set_verification: "partial",
      change_set_reason: "review_chain_gap",
    }), SESSION, PATH, "edit")).toMatchObject({ change_set_reason: "review_chain_gap" });
    expect(parseAgentChangeRestoreResult(result({
      change_set_verification: "tracking_unavailable",
      change_set_reason: "tracking_failed",
    }), SESSION, PATH, "edit")).toMatchObject({ change_set_reason: "tracking_failed" });
    expect(parseAgentChangeRestoreResult(result({
      operation: "trash_created",
      baseline_state: "absent",
      current_revision: null,
      current_byte_size: null,
      recovery: "windows_recycle_bin",
    }), SESSION, PATH, "trash_created")).toMatchObject({
      operation: "trash_created",
      current_revision: null,
    });
  });

  it.each([
    ["extra field", { extra: true }],
    ["wrong path", { path: "src/other.ts" }],
    ["unverified filesystem", { filesystem_verification: "unverified" }],
    ["false application", { applied: false }],
    ["verified result reason", { change_set_reason: "review_chain_gap" }],
    ["missing partial reason", { change_set_verification: "partial" }],
    ["wrong tracking reason", { change_set_verification: "tracking_unavailable", change_set_reason: "review_chain_gap" }],
  ])("rejects a result with %s", (_name, override) => {
    expect(() => parseAgentChangeRestoreResult(result(override), SESSION, PATH, "edit")).toThrow();
  });

  it("rejects an operation different from the authority that was previewed", () => {
    expect(() => parseAgentChangeRestoreResult(result(), SESSION, PATH, "recreate")).toThrow();
  });
});
