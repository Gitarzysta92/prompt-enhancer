import { describe, expect, it } from "vitest";
import type {
  AgentWorkspaceTransactionPreview,
  AgentWorkspaceTransactionPreviewCommand,
} from "./contracts";
import {
  AgentWorkspaceTransactionPayloadError,
  parseAgentWorkspaceTransactionPreview,
  parseAgentWorkspaceTransactionResult,
} from "./agentWorkspaceTransactionContract";

const SESSION = "a".repeat(32);
const PLAN = "b".repeat(32);
const ALPHA_OLD = "1".repeat(64);
const ALPHA_NEW = "2".repeat(64);
const BETA_OLD = "3".repeat(64);
const BETA_NEW = "4".repeat(64);

const command: AgentWorkspaceTransactionPreviewCommand = {
  changes: [
    { operation: "edit", path: "beta.txt", content: "beta new\n", expected_revision: BETA_OLD, line_ending: "lf" },
    { operation: "edit", path: "alpha.txt", content: "alpha new\n", expected_revision: ALPHA_OLD, line_ending: "lf" },
  ],
};

function previewPayload(): Record<string, unknown> {
  return {
    contract_version: "local-agent-workspace-transaction.v2",
    session_id: SESSION,
    plan_id: PLAN,
    file_count: 2,
    total_byte_size: 19,
    added_lines: 2,
    removed_lines: 2,
    files: [
      {
        operation: "edit",
        path: "alpha.txt",
        expected_revision: ALPHA_OLD,
        proposed_revision: ALPHA_NEW,
        line_ending: "lf",
        proposed_byte_size: 10,
        added_lines: 1,
        removed_lines: 1,
        diff: "--- a/alpha.txt\n+++ b/alpha.txt\n@@ -1 +1 @@\n-alpha old\n+alpha new",
      },
      {
        operation: "edit",
        path: "beta.txt",
        expected_revision: BETA_OLD,
        proposed_revision: BETA_NEW,
        line_ending: "lf",
        proposed_byte_size: 9,
        added_lines: 1,
        removed_lines: 1,
        diff: "--- a/beta.txt\n+++ b/beta.txt\n@@ -1 +1 @@\n-beta old\n+beta new",
      },
    ],
    expires_at: "2026-08-27T12:00:00Z",
  };
}

function parsedPreview(): AgentWorkspaceTransactionPreview {
  return parseAgentWorkspaceTransactionPreview(previewPayload(), SESSION, command);
}

function committedPayload(): Record<string, unknown> {
  return {
    contract_version: "local-agent-workspace-transaction.v2",
    session_id: SESSION,
    plan_id: PLAN,
    state: "committed",
    reason: null,
    file_count: 2,
    files: [
      { path: "alpha.txt", state: "committed", revision: ALPHA_NEW, byte_size: 10 },
      { path: "beta.txt", state: "committed", revision: BETA_NEW, byte_size: 9 },
    ],
  };
}

describe("agent workspace transaction contract", () => {
  it("accepts an exact byte-sorted preview and committed result", () => {
    const preview = parsedPreview();
    expect(preview.files.map((item) => item.path)).toEqual(["alpha.txt", "beta.txt"]);
    expect(preview.total_byte_size).toBe(19);
    const result = parseAgentWorkspaceTransactionResult(committedPayload(), SESSION, preview);
    expect(result.state).toBe("committed");
    expect(result.files.every((item) => item.state === "committed")).toBe(true);
  });

  it.each([
    ["wrong session", (value: any) => { value.session_id = "c".repeat(32); }],
    ["foreign revision", (value: any) => { value.files[0].expected_revision = "f".repeat(64); }],
    ["wrong byte total", (value: any) => { value.total_byte_size = 18; }],
    ["wrong diff count", (value: any) => { value.files[0].added_lines = 2; }],
    ["unsorted files", (value: any) => { value.files.reverse(); }],
    ["extra field", (value: any) => { value.private_content = "forbidden"; }],
  ])("rejects %s", (_label, mutate) => {
    const value = previewPayload();
    mutate(value);
    expect(() => parseAgentWorkspaceTransactionPreview(value, SESSION, command)).toThrow(
      AgentWorkspaceTransactionPayloadError,
    );
  });

  it("rejects a response for a case-fold duplicate request", () => {
    const duplicated: AgentWorkspaceTransactionPreviewCommand = {
      changes: [
        command.changes[0],
        { ...command.changes[0], path: "BETA.TXT" },
      ],
    };
    expect(() => parseAgentWorkspaceTransactionPreview(previewPayload(), SESSION, duplicated)).toThrow(
      AgentWorkspaceTransactionPayloadError,
    );
  });

  it("accepts explicit unverified state without revision claims", () => {
    const preview = parsedPreview();
    const value = committedPayload();
    value.state = "unverified";
    value.reason = "workspace_transaction_unverified";
    value.files = [
      { path: "alpha.txt", state: "unverified", revision: null, byte_size: null },
      { path: "beta.txt", state: "not_applied", revision: null, byte_size: null },
    ];
    expect(parseAgentWorkspaceTransactionResult(value, SESSION, preview).state).toBe("unverified");
  });

  it("accepts an absence-bound create and its exact rollback removal", () => {
    const createCommand: AgentWorkspaceTransactionPreviewCommand = {
      changes: [
        command.changes[1],
        {
          operation: "create",
          path: "new.txt",
          content: "new\n",
          expected_revision: null,
          line_ending: "lf",
        },
      ],
    };
    const value = previewPayload();
    value.total_byte_size = 14;
    value.added_lines = 2;
    value.removed_lines = 1;
    (value.files as Array<Record<string, unknown>>)[1] = {
      operation: "create",
      path: "new.txt",
      expected_revision: null,
      proposed_revision: BETA_NEW,
      line_ending: "lf",
      proposed_byte_size: 4,
      added_lines: 1,
      removed_lines: 0,
      diff: "--- a/new.txt\n+++ b/new.txt\n@@ -0,0 +1 @@\n+new",
    };
    const preview = parseAgentWorkspaceTransactionPreview(value, SESSION, createCommand);
    const result = committedPayload();
    result.state = "rolled_back";
    result.reason = "workspace_write_failed";
    result.files = [
      { path: "alpha.txt", state: "restored", revision: ALPHA_OLD, byte_size: 10 },
      { path: "new.txt", state: "removed", revision: null, byte_size: null },
    ];
    expect(parseAgentWorkspaceTransactionResult(result, SESSION, preview).state).toBe("rolled_back");
  });

  it("rejects the unverified-only reason on a claimed rollback", () => {
    const preview = parsedPreview();
    const value = committedPayload();
    value.state = "rolled_back";
    value.reason = "workspace_transaction_unverified";
    value.files = [
      { path: "alpha.txt", state: "restored", revision: ALPHA_OLD, byte_size: 10 },
      { path: "beta.txt", state: "not_applied", revision: null, byte_size: null },
    ];
    expect(() => parseAgentWorkspaceTransactionResult(value, SESSION, preview)).toThrow(
      AgentWorkspaceTransactionPayloadError,
    );
  });

  it("rejects committed or restored claims that do not match reviewed revisions", () => {
    const preview = parsedPreview();
    const value = committedPayload();
    (value.files as Array<Record<string, unknown>>)[0].revision = ALPHA_OLD;
    expect(() => parseAgentWorkspaceTransactionResult(value, SESSION, preview)).toThrow(
      AgentWorkspaceTransactionPayloadError,
    );
  });
});
