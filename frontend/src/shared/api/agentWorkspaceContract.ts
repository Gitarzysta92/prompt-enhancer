import type {
  AgentWorkspaceApplyResult,
  AgentWorkspaceEditPreview,
  AgentWorkspaceEntry,
  AgentWorkspaceFile,
  AgentWorkspaceTree,
} from "./contracts";

const CONTRACT_VERSION = "local-agent-workspace.v1";
const ID = /^[0-9a-f]{32}$/u;
const REVISION = /^[0-9a-f]{64}$/u;
export const AGENT_WORKSPACE_MAX_FILE_BYTES = 256_000;
const MAX_FILE_BYTES = AGENT_WORKSPACE_MAX_FILE_BYTES;
const MAX_DIFF_CHARS = 60_000;
const ENTRY_KINDS = new Set(["directory", "file", "unavailable"]);
const LINE_ENDINGS = new Set(["lf", "crlf", "none"]);

export class AgentWorkspacePayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentWorkspacePayloadError("workspace payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentWorkspacePayloadError("workspace payload fields were invalid");
  }
}

function text(value: unknown, min: number, max: number): string {
  if (typeof value !== "string" || value.length < min || value.length > max) {
    throw new AgentWorkspacePayloadError("workspace text field was invalid");
  }
  return value;
}

function integer(value: unknown, max?: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (max !== undefined && (value as number) > max)) {
    throw new AgentWorkspacePayloadError("workspace integer field was invalid");
  }
  return value as number;
}

function relativePath(value: unknown, allowRoot = false): string {
  const path = text(value, 1, 1024);
  if (allowRoot && path === ".") return path;
  if (
    path === "." ||
    path.includes("\\") ||
    path.includes("\0") ||
    path.startsWith("/") ||
    /^[A-Za-z]:/u.test(path) ||
    path.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new AgentWorkspacePayloadError("workspace path was not relative");
  }
  return path;
}

function parentPath(path: string): string {
  const separator = path.lastIndexOf("/");
  return separator < 0 ? "." : path.slice(0, separator);
}

function sessionId(value: unknown, expected: string): string {
  const candidate = text(value, 32, 32);
  if (!ID.test(candidate) || candidate !== expected) {
    throw new AgentWorkspacePayloadError("workspace session identity was invalid");
  }
  return candidate;
}

function revision(value: unknown, expected?: string): string {
  const candidate = text(value, 64, 64);
  if (!REVISION.test(candidate) || (expected !== undefined && candidate !== expected)) {
    throw new AgentWorkspacePayloadError("workspace revision was invalid");
  }
  return candidate;
}

function lineEnding(value: unknown, expected?: string): "lf" | "crlf" | "none" {
  if (typeof value !== "string" || !LINE_ENDINGS.has(value) || (expected !== undefined && value !== expected)) {
    throw new AgentWorkspacePayloadError("workspace line ending was invalid");
  }
  return value as "lf" | "crlf" | "none";
}

function entry(value: unknown, requestedPath: string): AgentWorkspaceEntry {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "editable_candidate", "kind", "name", "path"]);
  const path = relativePath(raw.path);
  const name = text(raw.name, 1, 255);
  const kind = raw.kind;
  if (typeof kind !== "string" || !ENTRY_KINDS.has(kind)) {
    throw new AgentWorkspacePayloadError("workspace entry kind was invalid");
  }
  if (parentPath(path) !== requestedPath || path.split("/").at(-1) !== name) {
    throw new AgentWorkspacePayloadError("workspace entry escaped its requested folder");
  }
  if (typeof raw.editable_candidate !== "boolean") {
    throw new AgentWorkspacePayloadError("workspace editability was invalid");
  }
  let byteSize: number | null;
  if (raw.byte_size === null) byteSize = null;
  else byteSize = integer(raw.byte_size);
  if (
    (kind === "file" && byteSize === null) ||
    (kind !== "file" && byteSize !== null) ||
    (raw.editable_candidate && (kind !== "file" || byteSize === null || byteSize > MAX_FILE_BYTES))
  ) {
    throw new AgentWorkspacePayloadError("workspace entry fields were incoherent");
  }
  return {
    path,
    name,
    kind: kind as AgentWorkspaceEntry["kind"],
    byte_size: byteSize,
    editable_candidate: raw.editable_candidate,
  };
}

export function parseAgentWorkspaceTree(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
): AgentWorkspaceTree {
  const raw = record(value);
  exactKeys(raw, ["complete", "contract_version", "entries", "path", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || typeof raw.complete !== "boolean" || !Array.isArray(raw.entries) || raw.entries.length > 400) {
    throw new AgentWorkspacePayloadError("workspace tree envelope was invalid");
  }
  const path = relativePath(raw.path, true);
  if (path !== expectedPath) throw new AgentWorkspacePayloadError("workspace tree path changed");
  const entries = raw.entries.map((item) => entry(item, path));
  const paths = new Set(entries.map((item) => item.path));
  const names = new Set(entries.map((item) => item.name));
  if (paths.size !== entries.length || names.size !== entries.length) {
    throw new AgentWorkspacePayloadError("workspace tree contained duplicates");
  }
  const order = { directory: 0, file: 1, unavailable: 2 } as const;
  for (let index = 1; index < entries.length; index += 1) {
    const previous = entries[index - 1];
    const current = entries[index];
    if (order[previous.kind] > order[current.kind]) {
      throw new AgentWorkspacePayloadError("workspace tree ordering was invalid");
    }
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    path,
    entries,
    complete: raw.complete,
  };
}

export function parseAgentWorkspaceFile(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
): AgentWorkspaceFile {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "content", "contract_version", "editable", "line_ending", "path", "revision", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.editable !== true) {
    throw new AgentWorkspacePayloadError("workspace file envelope was invalid");
  }
  const path = relativePath(raw.path);
  if (path !== expectedPath) throw new AgentWorkspacePayloadError("workspace file path changed");
  const content = text(raw.content, 0, MAX_FILE_BYTES);
  if (content.includes("\r") || content.includes("\0")) {
    throw new AgentWorkspacePayloadError("workspace file was not normalized text");
  }
  const ending = lineEnding(raw.line_ending);
  if ((ending === "none") !== !content.includes("\n")) {
    throw new AgentWorkspacePayloadError("workspace file line ending was incoherent");
  }
  const diskText = ending === "crlf" ? content.replaceAll("\n", "\r\n") : content;
  const byteSize = integer(raw.byte_size, MAX_FILE_BYTES);
  if (new TextEncoder().encode(diskText).byteLength !== byteSize) {
    throw new AgentWorkspacePayloadError("workspace file byte size was incoherent");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    path,
    content,
    revision: revision(raw.revision),
    byte_size: byteSize,
    line_ending: ending,
    editable: true,
  };
}

export function parseAgentWorkspacePreview(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
  expectedRevision: string,
  expectedLineEnding: string,
): AgentWorkspaceEditPreview {
  const raw = record(value);
  exactKeys(raw, ["contract_version", "diff", "expected_revision", "expires_at", "line_ending", "path", "preview_id", "proposed_revision", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION) throw new AgentWorkspacePayloadError("workspace preview contract changed");
  const path = relativePath(raw.path);
  if (path !== expectedPath) throw new AgentWorkspacePayloadError("workspace preview path changed");
  const expected = revision(raw.expected_revision, expectedRevision);
  const proposed = revision(raw.proposed_revision);
  if (proposed === expected) throw new AgentWorkspacePayloadError("workspace preview had no change");
  const previewId = text(raw.preview_id, 32, 32);
  if (!ID.test(previewId)) throw new AgentWorkspacePayloadError("workspace preview identity was invalid");
  const diff = text(raw.diff, 1, MAX_DIFF_CHARS);
  const diffLines = diff.split("\n");
  if (
    diff === "(no change)"
    || diffLines[0] !== `--- a/${path}`
    || diffLines[1] !== `+++ b/${path}`
    || !diffLines.slice(2).some((line) => line.startsWith("@@"))
    || !diffLines.slice(2).some((line) => line.startsWith("+") || line.startsWith("-"))
  ) {
    throw new AgentWorkspacePayloadError("workspace preview diff was invalid");
  }
  const expiresAt = text(raw.expires_at, 1, 64);
  if (!Number.isFinite(Date.parse(expiresAt))) throw new AgentWorkspacePayloadError("workspace preview expiry was invalid");
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    preview_id: previewId,
    path,
    expected_revision: expected,
    proposed_revision: proposed,
    line_ending: lineEnding(raw.line_ending, expectedLineEnding),
    diff,
    expires_at: expiresAt,
  };
}

export function parseAgentWorkspaceApplyResult(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
  expectedRevision: string,
): AgentWorkspaceApplyResult {
  const raw = record(value);
  exactKeys(raw, ["applied", "byte_size", "contract_version", "path", "revision", "session_id"]);
  if (raw.contract_version !== CONTRACT_VERSION || raw.applied !== true) {
    throw new AgentWorkspacePayloadError("workspace apply envelope was invalid");
  }
  const path = relativePath(raw.path);
  if (path !== expectedPath) throw new AgentWorkspacePayloadError("workspace apply path changed");
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    path,
    revision: revision(raw.revision, expectedRevision),
    byte_size: integer(raw.byte_size, MAX_FILE_BYTES),
    applied: true,
  };
}
