import type {
  AgentChangeRestoreApplyResult,
  AgentChangeRestorePreview,
} from "./contracts";

const CONTRACT_VERSION = "agent-change-restore.v1";
const ID = /^[0-9a-f]{32}$/u;
const REVISION = /^[0-9a-f]{64}$/u;
const MAX_PATH = 1024;
const MAX_FILE_BYTES = 256_000;
const MAX_DIFF_CHARS = 60_000;
const OPERATIONS = new Set(["edit", "recreate", "trash_created"]);
const DIFF_STATES = new Set(["available", "line_ending_only", "too_large"]);
const VERIFICATIONS = new Set([
  "verified", "partial", "unverified", "unavailable", "tracking_unavailable",
]);
const REASONS = new Set([
  "publication_unverified", "current_revision_changed", "review_chain_gap",
  "current_file_missing", "current_file_unavailable", "baseline_not_retained",
  "tracking_failed",
]);

export class AgentChangeRestorePayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentChangeRestorePayloadError("change restore payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentChangeRestorePayloadError("change restore payload fields were invalid");
  }
}

function relativePath(value: unknown, expected?: string): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > MAX_PATH
    || value === "."
    || value === ".."
    || value.startsWith("/")
    || value.includes("\\")
    || value.includes(":")
    || value.split("/").some((part) => part === "" || part === "." || part === "..")
    || [...value].some((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code < 32 || code === 127;
    })
    || (expected !== undefined && value !== expected)
  ) throw new AgentChangeRestorePayloadError("change restore path was invalid");
  return value;
}

function sessionId(value: unknown, expected: string): string {
  if (typeof value !== "string" || !ID.test(value) || value !== expected) {
    throw new AgentChangeRestorePayloadError("change restore session identity was invalid");
  }
  return value;
}

function nullableRevision(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !REVISION.test(value)) {
    throw new AgentChangeRestorePayloadError("change restore revision was invalid");
  }
  return value;
}

function count(value: unknown, max = MAX_FILE_BYTES + 1): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new AgentChangeRestorePayloadError("change restore count was invalid");
  }
  return value as number;
}

function operation(value: unknown): AgentChangeRestorePreview["operation"] {
  if (typeof value !== "string" || !OPERATIONS.has(value)) {
    throw new AgentChangeRestorePayloadError("change restore operation was invalid");
  }
  return value as AgentChangeRestorePreview["operation"];
}

export function parseAgentChangeRestorePreview(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
): AgentChangeRestorePreview {
  const raw = record(value);
  exactKeys(raw, [
    "added_lines", "baseline_state", "contract_version", "diff", "diff_state",
    "expected_revision", "expires_at", "line_ending", "operation", "path", "permanent",
    "preview_id", "recovery", "removed_lines", "requires_native_confirmation",
    "restored_byte_size", "restored_revision", "session_id",
  ]);
  const selectedOperation = operation(raw.operation);
  const path = relativePath(raw.path, expectedPath);
  const expectedRevision = nullableRevision(raw.expected_revision);
  const restoredRevision = nullableRevision(raw.restored_revision);
  const restoredByteSize = raw.restored_byte_size === null
    ? null
    : count(raw.restored_byte_size, MAX_FILE_BYTES);
  const addedLines = count(raw.added_lines);
  const removedLines = count(raw.removed_lines);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || !ID.test(String(raw.preview_id))
    || (raw.baseline_state !== "present" && raw.baseline_state !== "absent")
    || (raw.recovery !== "revision_bound_write" && raw.recovery !== "windows_recycle_bin")
    || raw.permanent !== false
    || raw.requires_native_confirmation !== true
    || typeof raw.diff_state !== "string"
    || !DIFF_STATES.has(raw.diff_state)
    || typeof raw.expires_at !== "string"
    || !/(?:Z|[+-]\d{2}:\d{2})$/u.test(raw.expires_at)
    || !Number.isFinite(Date.parse(raw.expires_at))
  ) throw new AgentChangeRestorePayloadError("change restore preview envelope was invalid");
  const restoresFile = selectedOperation === "edit" || selectedOperation === "recreate";
  if (
    restoresFile !== (raw.baseline_state === "present")
    || (restoresFile && (
      restoredRevision === null
      || restoredByteSize === null
      || !["lf", "crlf", "none"].includes(String(raw.line_ending))
      || raw.recovery !== "revision_bound_write"
    ))
    || (selectedOperation === "edit" && expectedRevision === null)
    || (selectedOperation === "recreate" && expectedRevision !== null)
    || (selectedOperation === "trash_created" && (
      expectedRevision === null
      || restoredRevision !== null
      || restoredByteSize !== null
      || raw.line_ending !== null
      || raw.recovery !== "windows_recycle_bin"
    ))
  ) throw new AgentChangeRestorePayloadError("change restore preview authority was incoherent");

  const diff = raw.diff;
  if (raw.diff_state === "available") {
    if (typeof diff !== "string" || diff.length < 1 || diff.length > MAX_DIFF_CHARS) {
      throw new AgentChangeRestorePayloadError("available restore diff was invalid");
    }
    const lines = diff.split("\n");
    const expectedFrom = selectedOperation === "recreate" ? "/dev/null" : `a/${path}`;
    const expectedTo = selectedOperation === "trash_created" ? "/dev/null" : `b/${path}`;
    if (
      lines[0] !== `--- ${expectedFrom}`
      || lines[1] !== `+++ ${expectedTo}`
      || !lines.slice(2).some((line) => line.startsWith("@@"))
    ) throw new AgentChangeRestorePayloadError("restore diff headers were invalid");
  } else if (diff !== null) {
    throw new AgentChangeRestorePayloadError("content-free restore diff carried text");
  }
  if (
    raw.diff_state === "line_ending_only"
    && (selectedOperation !== "edit" || addedLines !== 0 || removedLines !== 0)
  ) throw new AgentChangeRestorePayloadError("line-ending restore state was incoherent");

  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    preview_id: raw.preview_id as string,
    path,
    operation: selectedOperation,
    baseline_state: raw.baseline_state as AgentChangeRestorePreview["baseline_state"],
    expected_revision: expectedRevision,
    restored_revision: restoredRevision,
    restored_byte_size: restoredByteSize,
    line_ending: raw.line_ending as AgentChangeRestorePreview["line_ending"],
    diff_state: raw.diff_state as AgentChangeRestorePreview["diff_state"],
    diff: diff as string | null,
    added_lines: addedLines,
    removed_lines: removedLines,
    recovery: raw.recovery as AgentChangeRestorePreview["recovery"],
    permanent: false,
    expires_at: raw.expires_at,
    requires_native_confirmation: true,
  };
}

export function parseAgentChangeRestoreResult(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
  expectedOperation: AgentChangeRestorePreview["operation"],
): AgentChangeRestoreApplyResult {
  const raw = record(value);
  exactKeys(raw, [
    "applied", "baseline_state", "change_set_reason", "change_set_verification",
    "contract_version", "current_byte_size", "current_revision", "filesystem_verification",
    "net_effect", "operation", "path", "permanent", "recovery", "session_id",
  ]);
  const selectedOperation = operation(raw.operation);
  const currentRevision = nullableRevision(raw.current_revision);
  const currentByteSize = raw.current_byte_size === null
    ? null
    : count(raw.current_byte_size, MAX_FILE_BYTES);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || selectedOperation !== expectedOperation
    || (raw.baseline_state !== "present" && raw.baseline_state !== "absent")
    || (raw.recovery !== "revision_bound_write" && raw.recovery !== "windows_recycle_bin")
    || raw.permanent !== false
    || raw.net_effect !== "reverted"
    || raw.filesystem_verification !== "verified"
    || raw.applied !== true
    || typeof raw.change_set_verification !== "string"
    || !VERIFICATIONS.has(raw.change_set_verification)
  ) throw new AgentChangeRestorePayloadError("change restore result envelope was invalid");
  const restoresFile = selectedOperation === "edit" || selectedOperation === "recreate";
  if (
    restoresFile !== (raw.baseline_state === "present")
    || (restoresFile && (
      currentRevision === null
      || currentByteSize === null
      || raw.recovery !== "revision_bound_write"
    ))
    || (selectedOperation === "trash_created" && (
      currentRevision !== null
      || currentByteSize !== null
      || raw.recovery !== "windows_recycle_bin"
    ))
  ) throw new AgentChangeRestorePayloadError("change restore result read-back was incoherent");
  const reason = raw.change_set_reason;
  if (reason !== null && (typeof reason !== "string" || !REASONS.has(reason))) {
    throw new AgentChangeRestorePayloadError("change restore result reason was invalid");
  }
  const expectedReason = raw.change_set_verification === "verified"
    ? null
    : raw.change_set_verification === "unverified"
      ? "publication_unverified"
      : raw.change_set_verification === "unavailable"
        ? "current_file_unavailable"
        : raw.change_set_verification === "tracking_unavailable"
          ? "tracking_failed"
          : reason;
  if (
    reason !== expectedReason
    || (raw.change_set_verification === "partial" && ![
      "current_revision_changed", "review_chain_gap", "current_file_missing", "baseline_not_retained",
    ].includes(String(reason)))
  ) throw new AgentChangeRestorePayloadError("change restore result verification was incoherent");
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    path: relativePath(raw.path, expectedPath),
    operation: selectedOperation,
    baseline_state: raw.baseline_state as AgentChangeRestoreApplyResult["baseline_state"],
    current_revision: currentRevision,
    current_byte_size: currentByteSize,
    recovery: raw.recovery as AgentChangeRestoreApplyResult["recovery"],
    permanent: false,
    net_effect: "reverted",
    filesystem_verification: "verified",
    change_set_verification: raw.change_set_verification as AgentChangeRestoreApplyResult["change_set_verification"],
    change_set_reason: reason as AgentChangeRestoreApplyResult["change_set_reason"],
    applied: true,
  };
}
