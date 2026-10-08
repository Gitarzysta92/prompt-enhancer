import type {
  AgentWorkspaceCreateApplyResult,
  AgentWorkspaceCreatePreview,
  AgentWorkspaceDirectoryCreateApplyResult,
  AgentWorkspaceDirectoryCreatePreview,
  AgentWorkspaceDirectoryMoveApplyResult,
  AgentWorkspaceDirectoryMovePreview,
  AgentWorkspaceFileTrashApplyResult,
  AgentWorkspaceFileTrashPreview,
  AgentWorkspaceMoveApplyResult,
  AgentWorkspaceMovePreview,
} from "./contracts";

const CONTRACT_VERSION = "local-agent-workspace-lifecycle.v1";
const ID = /^[0-9a-f]{32}$/u;
const REVISION = /^[0-9a-f]{64}$/u;
const MAX_FILE_BYTES = 256_000;
const MAX_DIFF_CHARS = 60_000;
const LINE_ENDINGS = new Set(["lf", "crlf", "none"]);

export class AgentWorkspaceLifecyclePayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle payload fields were invalid");
  }
}

function text(value: unknown, min: number, max: number): string {
  if (typeof value !== "string" || value.length < min || value.length > max) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle text was invalid");
  }
  return value;
}

function relativePath(value: unknown, expected?: string): string {
  const path = text(value, 1, 1024);
  if (
    path === "."
    || path.startsWith("/")
    || path.includes("\\")
    || path.includes("\0")
    || /^[A-Za-z]:/u.test(path)
    || path.split("/").some((part) => part === "" || part === "." || part === "..")
    || (expected !== undefined && path !== expected)
  ) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle path was invalid");
  }
  return path;
}

function session(value: unknown, expected: string): string {
  const candidate = text(value, 32, 32);
  if (!ID.test(candidate) || candidate !== expected) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle session was invalid");
  }
  return candidate;
}

function identifier(value: unknown): string {
  const candidate = text(value, 32, 32);
  if (!ID.test(candidate)) throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle preview was invalid");
  return candidate;
}

function revision(value: unknown, expected?: string): string {
  const candidate = text(value, 64, 64);
  if (!REVISION.test(candidate) || (expected !== undefined && candidate !== expected)) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle revision was invalid");
  }
  return candidate;
}

function byteSize(value: unknown, expected?: number): number {
  if (
    !Number.isSafeInteger(value)
    || (value as number) < 0
    || (value as number) > MAX_FILE_BYTES
    || (expected !== undefined && value !== expected)
  ) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle byte size was invalid");
  }
  return value as number;
}

function expiry(value: unknown): string {
  const candidate = text(value, 1, 64);
  if (!Number.isFinite(Date.parse(candidate))) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace lifecycle expiry was invalid");
  }
  return candidate;
}

export function parseAgentWorkspaceCreatePreview(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
  expectedLineEnding: string,
  expectedByteSize?: number,
): AgentWorkspaceCreatePreview {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "contract_version", "diff", "expires_at", "line_ending", "path", "preview_id", "proposed_revision", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.line_ending !== expectedLineEnding || !LINE_ENDINGS.has(String(raw.line_ending))) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace create envelope was invalid");
  }
  const path = relativePath(raw.path, expectedPath);
  const diff = text(raw.diff, 1, MAX_DIFF_CHARS);
  const lines = diff.split("\n");
  if (lines[0] !== "--- /dev/null" || lines[1] !== `+++ b/${path}` || !lines.slice(2).some((line) => line.startsWith("@@"))) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace create diff was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    preview_id: identifier(raw.preview_id),
    path,
    proposed_revision: revision(raw.proposed_revision),
    line_ending: raw.line_ending as AgentWorkspaceCreatePreview["line_ending"],
    byte_size: byteSize(raw.byte_size, expectedByteSize),
    diff,
    expires_at: expiry(raw.expires_at),
  };
}

export function parseAgentWorkspaceCreateResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceCreatePreview,
): AgentWorkspaceCreateApplyResult {
  const raw = record(value);
  exactKeys(raw, ["applied", "byte_size", "contract_version", "operation", "path", "revision", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.operation !== "created" || raw.applied !== true) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace create result was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    path: relativePath(raw.path, preview.path),
    revision: revision(raw.revision, preview.proposed_revision),
    byte_size: byteSize(raw.byte_size, preview.byte_size),
    operation: "created",
    applied: true,
  };
}

export function parseAgentWorkspaceDirectoryCreatePreview(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
): AgentWorkspaceDirectoryCreatePreview {
  const raw = record(value);
  exactKeys(raw, ["contract_version", "expires_at", "path", "preview_id", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace directory create envelope was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    preview_id: identifier(raw.preview_id),
    path: relativePath(raw.path, expectedPath),
    expires_at: expiry(raw.expires_at),
  };
}

export function parseAgentWorkspaceDirectoryCreateResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceDirectoryCreatePreview,
): AgentWorkspaceDirectoryCreateApplyResult {
  const raw = record(value);
  exactKeys(raw, ["applied", "contract_version", "operation", "path", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.operation !== "directory_created" || raw.applied !== true) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace directory create result was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    path: relativePath(raw.path, preview.path),
    operation: "directory_created",
    applied: true,
  };
}

export function parseAgentWorkspaceDirectoryMovePreview(
  value: unknown,
  expectedSessionId: string,
  expectedSourcePath: string,
  expectedTargetPath: string,
): AgentWorkspaceDirectoryMovePreview {
  const raw = record(value);
  exactKeys(raw, ["contents_reviewed", "contract_version", "expires_at", "preview_id", "session_id", "source_path", "target_path"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.contents_reviewed !== false) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace directory move envelope was invalid");
  }
  const source = relativePath(raw.source_path, expectedSourcePath);
  const target = relativePath(raw.target_path, expectedTargetPath);
  if (source === target) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace directory move paths were identical");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    preview_id: identifier(raw.preview_id),
    source_path: source,
    target_path: target,
    contents_reviewed: false,
    expires_at: expiry(raw.expires_at),
  };
}

export function parseAgentWorkspaceDirectoryMoveResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceDirectoryMovePreview,
): AgentWorkspaceDirectoryMoveApplyResult {
  const raw = record(value);
  exactKeys(raw, ["applied", "contents_reviewed", "contract_version", "operation", "session_id", "source_path", "target_path"]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.operation !== "directory_moved"
    || raw.applied !== true
    || raw.contents_reviewed !== false
  ) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace directory move result was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    source_path: relativePath(raw.source_path, preview.source_path),
    target_path: relativePath(raw.target_path, preview.target_path),
    contents_reviewed: false,
    operation: "directory_moved",
    applied: true,
  };
}

export function parseAgentWorkspaceFileTrashPreview(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
  expectedRevision: string,
): AgentWorkspaceFileTrashPreview {
  const raw = record(value);
  exactKeys(raw, [
    "byte_size",
    "contract_version",
    "expected_revision",
    "expires_at",
    "path",
    "permanent",
    "preview_id",
    "recovery",
    "session_id",
  ]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.recovery !== "windows_recycle_bin"
    || raw.permanent !== false
  ) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace file trash envelope was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    preview_id: identifier(raw.preview_id),
    path: relativePath(raw.path, expectedPath),
    expected_revision: revision(raw.expected_revision, expectedRevision),
    byte_size: byteSize(raw.byte_size),
    recovery: "windows_recycle_bin",
    permanent: false,
    expires_at: expiry(raw.expires_at),
  };
}

export function parseAgentWorkspaceFileTrashResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceFileTrashPreview,
): AgentWorkspaceFileTrashApplyResult {
  const raw = record(value);
  exactKeys(raw, [
    "applied",
    "byte_size",
    "contract_version",
    "operation",
    "path",
    "permanent",
    "recovery",
    "revision",
    "session_id",
  ]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.operation !== "trashed"
    || raw.applied !== true
    || raw.recovery !== "windows_recycle_bin"
    || raw.permanent !== false
  ) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace file trash result was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    path: relativePath(raw.path, preview.path),
    revision: revision(raw.revision, preview.expected_revision),
    byte_size: byteSize(raw.byte_size, preview.byte_size),
    recovery: "windows_recycle_bin",
    permanent: false,
    operation: "trashed",
    applied: true,
  };
}

export function parseAgentWorkspaceMovePreview(
  value: unknown,
  expectedSessionId: string,
  expectedSourcePath: string,
  expectedTargetPath: string,
  expectedRevision: string,
): AgentWorkspaceMovePreview {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "contract_version", "expected_revision", "expires_at", "preview_id", "session_id", "source_path", "target_path"]);
  if (raw.contract_version !== CONTRACT_VERSION) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace move envelope was invalid");
  }
  const source = relativePath(raw.source_path, expectedSourcePath);
  const target = relativePath(raw.target_path, expectedTargetPath);
  if (source === target) throw new AgentWorkspaceLifecyclePayloadError("workspace move paths were identical");
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    preview_id: identifier(raw.preview_id),
    source_path: source,
    target_path: target,
    expected_revision: revision(raw.expected_revision, expectedRevision),
    byte_size: byteSize(raw.byte_size),
    expires_at: expiry(raw.expires_at),
  };
}

export function parseAgentWorkspaceMoveResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceMovePreview,
): AgentWorkspaceMoveApplyResult {
  const raw = record(value);
  exactKeys(raw, ["applied", "byte_size", "contract_version", "operation", "revision", "session_id", "source_path", "target_path"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.operation !== "moved" || raw.applied !== true) {
    throw new AgentWorkspaceLifecyclePayloadError("workspace move result was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: session(raw.session_id, expectedSessionId),
    source_path: relativePath(raw.source_path, preview.source_path),
    target_path: relativePath(raw.target_path, preview.target_path),
    revision: revision(raw.revision, preview.expected_revision),
    byte_size: byteSize(raw.byte_size, preview.byte_size),
    operation: "moved",
    applied: true,
  };
}
