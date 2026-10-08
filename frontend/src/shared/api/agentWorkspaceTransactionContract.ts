import type {
  AgentWorkspaceTransactionApplyResult,
  AgentWorkspaceTransactionFileResult,
  AgentWorkspaceTransactionPreview,
  AgentWorkspaceTransactionPreviewCommand,
  AgentWorkspaceTransactionPreviewFile,
} from "./contracts";

const CONTRACT_VERSION = "local-agent-workspace-transaction.v2";
const ID = /^[0-9a-f]{32}$/u;
const REVISION = /^[0-9a-f]{64}$/u;
const MAX_FILES = 8;
const MAX_FILE_BYTES = 256_000;
const MAX_TOTAL_BYTES = 1_024_000;
const MAX_DIFF_CHARS = 60_000;
const MAX_TOTAL_DIFF_CHARS = 240_000;
const FILE_STATES = new Set(["committed", "restored", "removed", "not_applied", "unverified"]);
const RESULT_STATES = new Set(["committed", "rejected", "rolled_back", "unverified"]);
const REASONS = new Set([
  "workspace_write_failed",
  "workspace_cleanup_failed",
  "workspace_verification_failed",
  "workspace_revision_changed",
  "workspace_file_unavailable",
  "workspace_transaction_unverified",
  "tool_cancelled",
]);
const ROLLBACK_REASONS = new Set([
  "workspace_write_failed",
  "workspace_cleanup_failed",
  "workspace_verification_failed",
  "workspace_revision_changed",
  "workspace_file_unavailable",
  "tool_cancelled",
]);

export class AgentWorkspaceTransactionPayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentWorkspaceTransactionPayloadError("transaction payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentWorkspaceTransactionPayloadError("transaction payload fields were invalid");
  }
}

function text(value: unknown, min: number, max: number): string {
  if (typeof value !== "string" || value.length < min || value.length > max) {
    throw new AgentWorkspaceTransactionPayloadError("transaction text field was invalid");
  }
  return value;
}

function integer(value: unknown, max: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new AgentWorkspaceTransactionPayloadError("transaction integer field was invalid");
  }
  return value as number;
}

function hasUnpairedSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return true;
  }
  return false;
}

function relativePath(value: unknown): string {
  const path = text(value, 1, 1024);
  if (
    hasUnpairedSurrogate(path)
    || path.includes("\\")
    || path.includes("\0")
    || path.startsWith("/")
    || /^[A-Za-z]:/u.test(path)
    || path.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction path was not relative");
  }
  return path;
}

function id(value: unknown, expected?: string): string {
  const candidate = text(value, 32, 32);
  if (!ID.test(candidate) || (expected !== undefined && candidate !== expected)) {
    throw new AgentWorkspaceTransactionPayloadError("transaction identity was invalid");
  }
  return candidate;
}

function revision(value: unknown, expected?: string): string {
  const candidate = text(value, 64, 64);
  if (!REVISION.test(candidate) || (expected !== undefined && candidate !== expected)) {
    throw new AgentWorkspaceTransactionPayloadError("transaction revision was invalid");
  }
  return candidate;
}

function lineEnding(value: unknown, expected?: string): "lf" | "crlf" | "none" {
  if (
    (value !== "lf" && value !== "crlf" && value !== "none")
    || (expected !== undefined && value !== expected)
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction line ending was invalid");
  }
  return value;
}

function operation(value: unknown, expected?: string): "create" | "edit" {
  if (
    (value !== "create" && value !== "edit")
    || (expected !== undefined && value !== expected)
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction operation was invalid");
  }
  return value;
}

function sourceRevision(
  value: unknown,
  fileOperation: "create" | "edit",
  expected: string | null | undefined,
): string | null {
  if (fileOperation === "edit") {
    return revision(value, expected ?? undefined);
  }
  if (value !== null || expected != null) {
    throw new AgentWorkspaceTransactionPayloadError("transaction create source was not absent");
  }
  return null;
}

function compareUtf8(left: string, right: string): number {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function assertSortedUnique(paths: string[]): void {
  if (
    paths.some((path, index) => index > 0 && compareUtf8(paths[index - 1], path) >= 0)
    || new Set(paths.map((path) => path.toLocaleLowerCase("en-US"))).size !== paths.length
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction paths were not unique and byte-sorted");
  }
}

function expectedChanges(command: AgentWorkspaceTransactionPreviewCommand): Map<string, AgentWorkspaceTransactionPreviewCommand["changes"][number]> {
  if (!Array.isArray(command.changes) || command.changes.length < 2 || command.changes.length > MAX_FILES) {
    throw new AgentWorkspaceTransactionPayloadError("transaction request size was invalid");
  }
  const result = new Map<string, AgentWorkspaceTransactionPreviewCommand["changes"][number]>();
  for (const change of command.changes) {
    const path = relativePath(change.path);
    const key = path.toLocaleLowerCase("en-US");
    if (result.has(key)) throw new AgentWorkspaceTransactionPayloadError("transaction request paths were duplicated");
    if (change.content.includes("\r") || change.content.includes("\0") || hasUnpairedSurrogate(change.content)) {
      throw new AgentWorkspaceTransactionPayloadError("transaction request content was invalid");
    }
    if (
      (change.operation === "edit" && typeof change.expected_revision !== "string")
      || (change.operation === "create" && change.expected_revision != null)
    ) {
      throw new AgentWorkspaceTransactionPayloadError("transaction request operation was incoherent");
    }
    result.set(key, change);
  }
  return result;
}

function previewFile(
  value: unknown,
  expected: Map<string, AgentWorkspaceTransactionPreviewCommand["changes"][number]>,
): AgentWorkspaceTransactionPreviewFile {
  const raw = record(value);
  exactKeys(raw, [
    "added_lines",
    "diff",
    "expected_revision",
    "line_ending",
    "operation",
    "path",
    "proposed_byte_size",
    "proposed_revision",
    "removed_lines",
  ]);
  const path = relativePath(raw.path);
  const requested = expected.get(path.toLocaleLowerCase("en-US"));
  if (!requested || requested.path !== path) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview path changed");
  }
  const fileOperation = operation(raw.operation, requested.operation);
  const expectedRevision = sourceRevision(
    raw.expected_revision,
    fileOperation,
    requested.expected_revision,
  );
  const proposedRevision = revision(raw.proposed_revision);
  if (expectedRevision !== null && expectedRevision === proposedRevision) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview had no change");
  }
  const ending = lineEnding(raw.line_ending, requested.line_ending);
  const diskContent = ending === "crlf" ? requested.content.replaceAll("\n", "\r\n") : requested.content;
  const byteSize = integer(raw.proposed_byte_size, MAX_FILE_BYTES);
  if (new TextEncoder().encode(diskContent).byteLength !== byteSize) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview byte size was incoherent");
  }
  const diff = text(raw.diff, 1, MAX_DIFF_CHARS);
  const lines = diff.split("\n");
  if (
    lines[0] !== `--- a/${path}`
    || lines[1] !== `+++ b/${path}`
    || !lines.slice(2).some((line) => line.startsWith("@@"))
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview diff was invalid");
  }
  const added = lines.slice(2).filter((line) => line.startsWith("+")).length;
  const removed = lines.slice(2).filter((line) => line.startsWith("-")).length;
  const addedLines = integer(raw.added_lines, MAX_FILE_BYTES + 1);
  const removedLines = integer(raw.removed_lines, MAX_FILE_BYTES + 1);
  if (added !== addedLines || removed !== removedLines) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview line counts were incoherent");
  }
  return {
    operation: fileOperation,
    path,
    expected_revision: expectedRevision,
    proposed_revision: proposedRevision,
    line_ending: ending,
    proposed_byte_size: byteSize,
    added_lines: addedLines,
    removed_lines: removedLines,
    diff,
  };
}

export function parseAgentWorkspaceTransactionPreview(
  value: unknown,
  expectedSessionId: string,
  command: AgentWorkspaceTransactionPreviewCommand,
): AgentWorkspaceTransactionPreview {
  const raw = record(value);
  exactKeys(raw, [
    "added_lines",
    "contract_version",
    "expires_at",
    "file_count",
    "files",
    "plan_id",
    "removed_lines",
    "session_id",
    "total_byte_size",
  ]);
  if (raw.contract_version !== CONTRACT_VERSION || !Array.isArray(raw.files)) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview envelope was invalid");
  }
  const expected = expectedChanges(command);
  if (raw.files.length !== expected.size) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview file count changed");
  }
  const files = raw.files.map((item) => previewFile(item, expected));
  const paths = files.map((item) => item.path);
  assertSortedUnique(paths);
  const fileCount = integer(raw.file_count, MAX_FILES);
  const totalByteSize = integer(raw.total_byte_size, MAX_TOTAL_BYTES);
  const addedLines = integer(raw.added_lines, MAX_TOTAL_BYTES + MAX_FILES);
  const removedLines = integer(raw.removed_lines, MAX_TOTAL_BYTES + MAX_FILES);
  if (
    fileCount !== files.length
    || totalByteSize !== files.reduce((total, item) => total + item.proposed_byte_size, 0)
    || addedLines !== files.reduce((total, item) => total + item.added_lines, 0)
    || removedLines !== files.reduce((total, item) => total + item.removed_lines, 0)
    || files.reduce((total, item) => total + item.diff.length, 0) > MAX_TOTAL_DIFF_CHARS
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview totals were incoherent");
  }
  const expiresAt = text(raw.expires_at, 1, 64);
  if (!Number.isFinite(Date.parse(expiresAt))) {
    throw new AgentWorkspaceTransactionPayloadError("transaction preview expiry was invalid");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: id(raw.session_id, expectedSessionId),
    plan_id: id(raw.plan_id),
    file_count: fileCount,
    total_byte_size: totalByteSize,
    added_lines: addedLines,
    removed_lines: removedLines,
    files,
    expires_at: expiresAt,
  };
}

function resultFile(
  value: unknown,
  reviewed: AgentWorkspaceTransactionPreviewFile,
): AgentWorkspaceTransactionFileResult {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "path", "revision", "state"]);
  const path = relativePath(raw.path);
  if (path !== reviewed.path || typeof raw.state !== "string" || !FILE_STATES.has(raw.state)) {
    throw new AgentWorkspaceTransactionPayloadError("transaction file result was invalid");
  }
  const state = raw.state as AgentWorkspaceTransactionFileResult["state"];
  let resultRevision: string | null = null;
  let byteSize: number | null = null;
  if (state === "committed") {
    resultRevision = revision(raw.revision, reviewed.proposed_revision);
    byteSize = integer(raw.byte_size, MAX_FILE_BYTES);
    if (byteSize !== reviewed.proposed_byte_size) {
      throw new AgentWorkspaceTransactionPayloadError("committed transaction size changed");
    }
  } else if (state === "restored") {
    if (reviewed.operation !== "edit" || reviewed.expected_revision == null) {
      throw new AgentWorkspaceTransactionPayloadError("created transaction file could not be restored");
    }
    resultRevision = revision(raw.revision, reviewed.expected_revision);
    byteSize = integer(raw.byte_size, MAX_FILE_BYTES);
  } else if (state === "removed") {
    if (reviewed.operation !== "create" || raw.revision !== null || raw.byte_size !== null) {
      throw new AgentWorkspaceTransactionPayloadError("edited transaction file could not be removed");
    }
  } else if (raw.revision !== null || raw.byte_size !== null) {
    throw new AgentWorkspaceTransactionPayloadError("unverified transaction file claimed a revision");
  }
  return { path, state, revision: resultRevision, byte_size: byteSize };
}

export function parseAgentWorkspaceTransactionResult(
  value: unknown,
  expectedSessionId: string,
  preview: AgentWorkspaceTransactionPreview,
): AgentWorkspaceTransactionApplyResult {
  const raw = record(value);
  exactKeys(raw, ["contract_version", "file_count", "files", "plan_id", "reason", "session_id", "state"]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || !Array.isArray(raw.files)
    || raw.files.length !== preview.files.length
    || typeof raw.state !== "string"
    || !RESULT_STATES.has(raw.state)
    || (raw.reason !== null && (typeof raw.reason !== "string" || !REASONS.has(raw.reason)))
  ) {
    throw new AgentWorkspaceTransactionPayloadError("transaction result envelope was invalid");
  }
  const files = raw.files.map((item, index) => resultFile(item, preview.files[index]));
  assertSortedUnique(files.map((item) => item.path));
  const state = raw.state as AgentWorkspaceTransactionApplyResult["state"];
  const reason = raw.reason as AgentWorkspaceTransactionApplyResult["reason"];
  const states = files.map((item) => item.state);
  const coherent = state === "committed"
    ? reason === null && states.every((item) => item === "committed")
    : state === "rejected"
      ? typeof reason === "string" && ROLLBACK_REASONS.has(reason) && states.every((item) => item === "not_applied")
      : state === "rolled_back"
        ? typeof reason === "string" && ROLLBACK_REASONS.has(reason) && states.some((item) => item === "restored" || item === "removed") && states.every((item) => item === "restored" || item === "removed" || item === "not_applied")
        : reason === "workspace_transaction_unverified" && states.includes("unverified");
  if (!coherent || integer(raw.file_count, MAX_FILES) !== files.length) {
    throw new AgentWorkspaceTransactionPayloadError("transaction result state was incoherent");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: id(raw.session_id, expectedSessionId),
    plan_id: id(raw.plan_id, preview.plan_id),
    state,
    reason,
    file_count: files.length,
    files,
  };
}
