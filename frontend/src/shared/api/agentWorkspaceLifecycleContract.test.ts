import { describe, expect, it } from "vitest";
import {
  AgentWorkspaceLifecyclePayloadError,
  parseAgentWorkspaceCreateResult,
  parseAgentWorkspaceCreatePreview,
  parseAgentWorkspaceDirectoryCreatePreview,
  parseAgentWorkspaceDirectoryCreateResult,
  parseAgentWorkspaceDirectoryMovePreview,
  parseAgentWorkspaceDirectoryMoveResult,
  parseAgentWorkspaceFileTrashPreview,
  parseAgentWorkspaceFileTrashResult,
  parseAgentWorkspaceMoveResult,
  parseAgentWorkspaceMovePreview,
} from "./agentWorkspaceLifecycleContract";

const SESSION = "a".repeat(32);
const PREVIEW = "b".repeat(32);
const REVISION = "c".repeat(64);

describe("agent workspace lifecycle response contract", () => {
  it("binds a reviewed create preview and receipt to exact authority", () => {
    const preview = parseAgentWorkspaceCreatePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/example.txt",
      proposed_revision: REVISION,
      line_ending: "lf",
      byte_size: 8,
      diff: "--- /dev/null\n+++ b/notes/example.txt\n@@ -0,0 +1 @@\n+example",
      expires_at: "2026-08-27T08:02:00Z",
    }, SESSION, "notes/example.txt", "lf");
    expect(preview.proposed_revision).toBe(REVISION);

    const result = parseAgentWorkspaceCreateResult({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      path: "notes/example.txt",
      revision: REVISION,
      byte_size: 8,
      operation: "created",
      applied: true,
    }, SESSION, preview);
    expect(result.operation).toBe("created");
  });

  it("binds a reviewed move preview and receipt to source, target, and revision", () => {
    const preview = parseAgentWorkspaceMovePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "notes/example.txt",
      target_path: "archive/example.txt",
      expected_revision: REVISION,
      byte_size: 8,
      expires_at: "2026-08-27T08:02:00Z",
    }, SESSION, "notes/example.txt", "archive/example.txt", REVISION);
    expect(preview.target_path).toBe("archive/example.txt");

    const result = parseAgentWorkspaceMoveResult({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      source_path: "notes/example.txt",
      target_path: "archive/example.txt",
      revision: REVISION,
      byte_size: 8,
      operation: "moved",
      applied: true,
    }, SESSION, preview);
    expect(result.operation).toBe("moved");
  });

  it("binds recoverable file removal to one path, revision, and non-permanent receipt", () => {
    const preview = parseAgentWorkspaceFileTrashPreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/example.txt",
      expected_revision: REVISION,
      byte_size: 8,
      recovery: "windows_recycle_bin",
      permanent: false,
      expires_at: "2026-08-27T08:02:00Z",
    }, SESSION, "notes/example.txt", REVISION);
    expect(preview.permanent).toBe(false);

    const result = parseAgentWorkspaceFileTrashResult({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      path: "notes/example.txt",
      revision: REVISION,
      byte_size: 8,
      recovery: "windows_recycle_bin",
      permanent: false,
      operation: "trashed",
      applied: true,
    }, SESSION, preview);
    expect(result).toMatchObject({ operation: "trashed", permanent: false });
  });

  it.each([
    ["permanent authority", { permanent: true }],
    ["non-Windows recovery", { recovery: "private_vault" }],
    ["extra deletion scope", { recursive: true }],
    ["changed revision", { expected_revision: "d".repeat(64) }],
  ])("rejects a file trash preview with %s", (_name, override) => {
    expect(() => parseAgentWorkspaceFileTrashPreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/example.txt",
      expected_revision: REVISION,
      byte_size: 8,
      recovery: "windows_recycle_bin",
      permanent: false,
      expires_at: "2026-08-27T08:02:00Z",
      ...override,
    }, SESSION, "notes/example.txt", REVISION)).toThrow(AgentWorkspaceLifecyclePayloadError);
  });

  it("binds a reviewed directory create to one exact absent path", () => {
    const preview = parseAgentWorkspaceDirectoryCreatePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/guides",
      expires_at: "2026-08-27T08:02:00Z",
    }, SESSION, "notes/guides");
    expect(preview.path).toBe("notes/guides");

    const result = parseAgentWorkspaceDirectoryCreateResult({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      path: "notes/guides",
      operation: "directory_created",
      applied: true,
    }, SESSION, preview);
    expect(result.operation).toBe("directory_created");
  });

  it("binds a directory move to exact paths without inventing content review", () => {
    const preview = parseAgentWorkspaceDirectoryMovePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "notes/guides",
      target_path: "archive/guides",
      contents_reviewed: false,
      expires_at: "2026-08-27T08:02:00Z",
    }, SESSION, "notes/guides", "archive/guides");
    expect(preview.contents_reviewed).toBe(false);

    const result = parseAgentWorkspaceDirectoryMoveResult({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      source_path: "notes/guides",
      target_path: "archive/guides",
      contents_reviewed: false,
      operation: "directory_moved",
      applied: true,
    }, SESSION, preview);
    expect(result.operation).toBe("directory_moved");
    expect(result.contents_reviewed).toBe(false);
  });

  it.each([
    ["changed target", { target_path: "archive/private" }],
    ["invented content review", { contents_reviewed: true }],
    ["extra recursive authority", { recursive: true }],
  ])("rejects a directory move with %s", (_name, override) => {
    expect(() => parseAgentWorkspaceDirectoryMovePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "notes/guides",
      target_path: "archive/guides",
      contents_reviewed: false,
      expires_at: "2026-08-27T08:02:00Z",
      ...override,
    }, SESSION, "notes/guides", "archive/guides")).toThrow(AgentWorkspaceLifecyclePayloadError);
  });

  it.each([
    ["changed directory path", { path: "notes/private" }],
    ["extra directory authority", { recursive: true }],
    ["invalid directory expiry", { expires_at: "later" }],
  ])("rejects a directory preview with %s", (_name, override) => {
    expect(() => parseAgentWorkspaceDirectoryCreatePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/guides",
      expires_at: "2026-08-27T08:02:00Z",
      ...override,
    }, SESSION, "notes/guides")).toThrow(AgentWorkspaceLifecyclePayloadError);
  });

  it.each([
    ["extra create authority", { private_path: "example" }],
    ["wrong create diff path", { diff: "--- /dev/null\n+++ b/other.txt\n@@ -0,0 +1 @@\n+example" }],
    ["wrong session", { session_id: "d".repeat(32) }],
    ["absolute path", { path: "C:/private.txt" }],
    ["invalid expiry", { expires_at: "soon" }],
  ])("rejects %s", (_name, override) => {
    expect(() => parseAgentWorkspaceCreatePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      path: "notes/example.txt",
      proposed_revision: REVISION,
      line_ending: "lf",
      byte_size: 8,
      diff: "--- /dev/null\n+++ b/notes/example.txt\n@@ -0,0 +1 @@\n+example",
      expires_at: "2026-08-27T08:02:00Z",
      ...override,
    }, SESSION, "notes/example.txt", "lf")).toThrow(AgentWorkspaceLifecyclePayloadError);
  });

  it.each([
    ["same paths", { target_path: "notes/example.txt" }],
    ["changed source", { source_path: "notes/other.txt" }],
    ["changed revision", { expected_revision: "d".repeat(64) }],
    ["private extra", { source_identity: [1, 2] }],
  ])("rejects a move with %s", (_name, override) => {
    expect(() => parseAgentWorkspaceMovePreview({
      contract_version: "local-agent-workspace-lifecycle.v1",
      session_id: SESSION,
      preview_id: PREVIEW,
      source_path: "notes/example.txt",
      target_path: "archive/example.txt",
      expected_revision: REVISION,
      byte_size: 8,
      expires_at: "2026-08-27T08:02:00Z",
      ...override,
    }, SESSION, "notes/example.txt", "archive/example.txt", REVISION)).toThrow(AgentWorkspaceLifecyclePayloadError);
  });
});
