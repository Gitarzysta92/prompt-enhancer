import { describe, expect, it } from "vitest";
import {
  AgentWorkspacePayloadError,
  parseAgentWorkspaceApplyResult,
  parseAgentWorkspaceFile,
  parseAgentWorkspacePreview,
  parseAgentWorkspaceTree,
} from "./agentWorkspaceContract";

const SESSION = "a".repeat(32);
const BASE = "b".repeat(64);
const PROPOSED = "c".repeat(64);

function tree() {
  return {
    contract_version: "local-agent-workspace.v1",
    session_id: SESSION,
    path: ".",
    entries: [
      { path: "src", name: "src", kind: "directory", byte_size: null, editable_candidate: false },
      { path: "README.md", name: "README.md", kind: "file", byte_size: 8, editable_candidate: true },
      { path: "node_modules", name: "node_modules", kind: "unavailable", byte_size: null, editable_candidate: false },
    ],
    complete: true,
  };
}

describe("agent workspace response contract", () => {
  it("accepts a bounded, ordered, relative tree", () => {
    const parsed = parseAgentWorkspaceTree(tree(), SESSION, ".");
    expect(parsed.entries.map((entry) => entry.path)).toEqual(["src", "README.md", "node_modules"]);
  });

  it.each([
    ["foreign session", (value: ReturnType<typeof tree>) => { value.session_id = "d".repeat(32); }],
    ["absolute path", (value: ReturnType<typeof tree>) => { value.entries[1].path = "C:/private.txt"; }],
    ["traversal", (value: ReturnType<typeof tree>) => { value.entries[1].path = "../private.txt"; }],
    ["duplicate", (value: ReturnType<typeof tree>) => { value.entries[1] = { ...value.entries[0] }; }],
    ["wrong parent", (value: ReturnType<typeof tree>) => { value.entries[1].path = "docs/README.md"; }],
    ["incoherent size", (value: ReturnType<typeof tree>) => { value.entries[0].byte_size = 10; }],
    ["incoherent editability", (value: ReturnType<typeof tree>) => { value.entries[2].editable_candidate = true; }],
    ["wrong order", (value: ReturnType<typeof tree>) => { value.entries.reverse(); }],
    ["private extra", (value: ReturnType<typeof tree> & { root?: string }) => { value.root = "example"; }],
  ])("rejects %s tree responses", (_name, mutate) => {
    const value = tree();
    mutate(value);
    expect(() => parseAgentWorkspaceTree(value, SESSION, ".")).toThrow(AgentWorkspacePayloadError);
  });

  it("accepts normalized CRLF text with exact byte size", () => {
    const parsed = parseAgentWorkspaceFile({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      path: "src/app.py",
      content: "one\ntwo\n",
      revision: BASE,
      byte_size: 10,
      line_ending: "crlf",
      editable: true,
    }, SESSION, "src/app.py");
    expect(parsed.line_ending).toBe("crlf");
    expect(parsed.content).toBe("one\ntwo\n");
  });

  it.each([
    ["wrong bytes", { byte_size: 7 }],
    ["raw carriage return", { content: "one\r\ntwo\n", byte_size: 10 }],
    ["newline marked as none", { line_ending: "none" }],
    ["missing newline marked as lf", { content: "one", byte_size: 3, line_ending: "lf" }],
    ["absolute file", { path: "/private.txt" }],
    ["not editable", { editable: false }],
  ])("rejects %s file responses", (_name, override) => {
    expect(() => parseAgentWorkspaceFile({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      path: "src/app.py",
      content: "one\ntwo\n",
      revision: BASE,
      byte_size: 8,
      line_ending: "lf",
      editable: true,
      ...override,
    }, SESSION, "src/app.py")).toThrow(AgentWorkspacePayloadError);
  });

  it("binds previews and apply receipts to session, path, revisions, and line style", () => {
    const preview = parseAgentWorkspacePreview({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      preview_id: "d".repeat(32),
      path: "src/app.py",
      expected_revision: BASE,
      proposed_revision: PROPOSED,
      line_ending: "lf",
      diff: "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new",
      expires_at: "2026-08-20T20:00:00Z",
    }, SESSION, "src/app.py", BASE, "lf");
    expect(preview.proposed_revision).toBe(PROPOSED);
    const applied = parseAgentWorkspaceApplyResult({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      path: "src/app.py",
      revision: PROPOSED,
      byte_size: 12,
      applied: true,
    }, SESSION, "src/app.py", PROPOSED);
    expect(applied.applied).toBe(true);
  });

  it("rejects forged preview and apply authority", () => {
    const preview = {
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      preview_id: "d".repeat(32),
      path: "src/app.py",
      expected_revision: BASE,
      proposed_revision: BASE,
      line_ending: "lf",
      diff: "diff",
      expires_at: "2026-08-20T20:00:00Z",
    };
    expect(() => parseAgentWorkspacePreview(preview, SESSION, "src/app.py", BASE, "lf")).toThrow(AgentWorkspacePayloadError);
    expect(() => parseAgentWorkspaceApplyResult({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      path: "src/app.py",
      revision: BASE,
      byte_size: 1,
      applied: true,
    }, SESSION, "src/app.py", PROPOSED)).toThrow(AgentWorkspacePayloadError);
  });

  it("rejects a byte-changing preview that claims there is no visible change", () => {
    expect(() => parseAgentWorkspacePreview({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      preview_id: "d".repeat(32),
      path: "src/app.py",
      expected_revision: BASE,
      proposed_revision: PROPOSED,
      line_ending: "lf",
      diff: "(no change)",
      expires_at: "2026-08-20T20:00:00Z",
    }, SESSION, "src/app.py", BASE, "lf")).toThrow(AgentWorkspacePayloadError);
  });

  it.each([
    ["wrong path header", "--- a/other.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new"],
    ["missing hunk", "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new"],
    ["missing changed body", "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n context"],
  ])("rejects a malformed preview diff with %s", (_name, diff) => {
    expect(() => parseAgentWorkspacePreview({
      contract_version: "local-agent-workspace.v1",
      session_id: SESSION,
      preview_id: "d".repeat(32),
      path: "src/app.py",
      expected_revision: BASE,
      proposed_revision: PROPOSED,
      line_ending: "lf",
      diff,
      expires_at: "2026-08-20T20:00:00Z",
    }, SESSION, "src/app.py", BASE, "lf")).toThrow(AgentWorkspacePayloadError);
  });
});
