import type { AgentChangeDiff, AgentChangedFile, AgentChangeSet } from "./contracts";

const CONTRACT_VERSION = "agent-change-set.v1";
const ID = /^[0-9a-f]{32}$/u;
const MAX_PATH = 1024;
const MAX_FILES = 64;
const MAX_FILE_BYTES = 256_000;
const MAX_DIFF_CHARS = 60_000;
const EFFECTS = new Set(["created", "modified", "deleted", "reverted", "unknown"]);
const VERIFICATIONS = new Set(["verified", "partial", "unverified", "unavailable"]);
const REASONS = new Set([
  "publication_unverified",
  "current_revision_changed",
  "review_chain_gap",
  "current_file_missing",
  "current_file_unavailable",
  "baseline_not_retained",
]);
const DIFF_STATES = new Set(["available", "no_change", "line_ending_only", "too_large", "unavailable"]);

export class AgentChangeSetPayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentChangeSetPayloadError("change-set payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentChangeSetPayloadError("change-set payload fields were invalid");
  }
}

function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new AgentChangeSetPayloadError("change-set count was invalid");
  }
  return value as number;
}

function relativePath(value: unknown): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > MAX_PATH
    || value === "."
    || value === ".."
    || value.startsWith("/")
    || value.includes("\\")
    || value.includes(":")
    || [...value].some((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code < 32 || code === 127;
    })
    || value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new AgentChangeSetPayloadError("change-set path was invalid");
  }
  return value;
}

function sessionId(value: unknown, expected: string): string {
  if (typeof value !== "string" || !ID.test(value) || value !== expected) {
    throw new AgentChangeSetPayloadError("change-set session identity was invalid");
  }
  return value;
}

function changedFile(value: unknown): AgentChangedFile {
  const raw = record(value);
  exactKeys(raw, [
    "agent_writes", "current_byte_size", "diff_available", "manual_writes", "net_effect",
    "path", "reason", "reviewed_writes", "verification",
  ]);
  if (
    typeof raw.net_effect !== "string" || !EFFECTS.has(raw.net_effect)
    || typeof raw.verification !== "string" || !VERIFICATIONS.has(raw.verification)
    || typeof raw.diff_available !== "boolean"
  ) throw new AgentChangeSetPayloadError("change-set file state was invalid");
  const reason = raw.reason;
  if (reason !== null && (typeof reason !== "string" || !REASONS.has(reason))) {
    throw new AgentChangeSetPayloadError("change-set file reason was invalid");
  }
  const reviewedWrites = integer(raw.reviewed_writes);
  const agentWrites = integer(raw.agent_writes, reviewedWrites);
  const manualWrites = integer(raw.manual_writes, reviewedWrites);
  if (reviewedWrites < 1 || agentWrites + manualWrites !== reviewedWrites) {
    throw new AgentChangeSetPayloadError("change-set file counts were incoherent");
  }
  const expectedReason = raw.verification === "verified"
    ? null
    : raw.verification === "unverified"
      ? "publication_unverified"
      : raw.verification === "unavailable"
        ? "current_file_unavailable"
        : reason;
  if (
    reason !== expectedReason
    || (raw.verification === "partial" && ![
      "current_revision_changed", "review_chain_gap", "current_file_missing", "baseline_not_retained",
    ].includes(String(reason)))
    || (raw.net_effect === "unknown" && raw.diff_available)
  ) throw new AgentChangeSetPayloadError("change-set file authority was incoherent");
  const byteSize = raw.current_byte_size === null ? null : integer(raw.current_byte_size, MAX_FILE_BYTES);
  if (
    (["created", "modified"].includes(raw.net_effect) && byteSize === null)
    || (raw.net_effect === "deleted" && byteSize !== null)
    || (reason === "current_file_missing" && (
      !["deleted", "reverted"].includes(raw.net_effect) || byteSize !== null
    ))
    || (reason === "current_file_unavailable" && (
      raw.net_effect !== "unknown" || byteSize !== null || raw.diff_available
    ))
    || (["current_revision_changed", "review_chain_gap", "baseline_not_retained"].includes(String(reason))
      && byteSize === null)
    || (reason === "baseline_not_retained" && raw.diff_available)
  ) throw new AgentChangeSetPayloadError("change-set file presence was incoherent");
  return {
    path: relativePath(raw.path),
    net_effect: raw.net_effect as AgentChangedFile["net_effect"],
    verification: raw.verification as AgentChangedFile["verification"],
    reason: reason as AgentChangedFile["reason"],
    reviewed_writes: reviewedWrites,
    agent_writes: agentWrites,
    manual_writes: manualWrites,
    current_byte_size: byteSize,
    diff_available: raw.diff_available,
  };
}

export function parseAgentChangeSet(value: unknown, expectedSessionId: string): AgentChangeSet {
  const raw = record(value);
  exactKeys(raw, [
    "agent_writes", "command_attempts", "contract_version", "coverage", "files", "manual_writes",
    "omitted_write_receipts", "reviewed_noops", "reviewed_writes", "scope", "session_id", "settled",
    "tracking_failed", "unverified_writes", "verified_writes",
  ]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.scope !== "reviewed_paths_only"
    || (raw.coverage !== "complete" && raw.coverage !== "partial")
    || typeof raw.settled !== "boolean"
    || typeof raw.tracking_failed !== "boolean"
    || !Array.isArray(raw.files)
    || raw.files.length > MAX_FILES
  ) throw new AgentChangeSetPayloadError("change-set envelope was invalid");
  const reviewed = integer(raw.reviewed_writes);
  const verified = integer(raw.verified_writes, reviewed);
  const unverified = integer(raw.unverified_writes, reviewed);
  const agent = integer(raw.agent_writes, reviewed);
  const manual = integer(raw.manual_writes, reviewed);
  const noops = integer(raw.reviewed_noops, verified);
  const commands = integer(raw.command_attempts);
  const omitted = integer(raw.omitted_write_receipts, reviewed);
  if (verified + unverified !== reviewed || agent + manual !== reviewed) {
    throw new AgentChangeSetPayloadError("change-set totals were incoherent");
  }
  const files = raw.files.map(changedFile);
  if (new Set(files.map((file) => file.path)).size !== files.length) {
    throw new AgentChangeSetPayloadError("change-set paths were duplicated");
  }
  if (
    files.reduce((sum, file) => sum + file.reviewed_writes, 0) > reviewed
    || files.reduce((sum, file) => sum + file.agent_writes, 0) > agent
    || files.reduce((sum, file) => sum + file.manual_writes, 0) > manual
  ) throw new AgentChangeSetPayloadError("change-set file totals exceeded the envelope");
  const complete = raw.settled
    && commands === 0
    && omitted === 0
    && raw.tracking_failed === false
    && unverified === 0
    && files.every((file) => file.verification === "verified");
  if ((raw.coverage === "complete") !== complete) {
    throw new AgentChangeSetPayloadError("change-set coverage was incoherent");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    scope: "reviewed_paths_only",
    coverage: raw.coverage,
    settled: raw.settled,
    reviewed_writes: reviewed,
    verified_writes: verified,
    unverified_writes: unverified,
    agent_writes: agent,
    manual_writes: manual,
    reviewed_noops: noops,
    command_attempts: commands,
    omitted_write_receipts: omitted,
    tracking_failed: raw.tracking_failed,
    files,
  };
}

export function parseAgentChangeDiff(
  value: unknown,
  expectedSessionId: string,
  expectedPath: string,
): AgentChangeDiff {
  const raw = record(value);
  exactKeys(raw, ["added_lines", "contract_version", "diff", "diff_state", "removed_lines", "session_id", "summary"]);
  if (raw.contract_version !== CONTRACT_VERSION || typeof raw.diff_state !== "string" || !DIFF_STATES.has(raw.diff_state)) {
    throw new AgentChangeSetPayloadError("change diff envelope was invalid");
  }
  const summary = changedFile(raw.summary);
  if (summary.path !== expectedPath) throw new AgentChangeSetPayloadError("change diff path changed");
  const diff = raw.diff;
  const added = raw.added_lines === null ? null : integer(raw.added_lines, MAX_FILE_BYTES + 1);
  const removed = raw.removed_lines === null ? null : integer(raw.removed_lines, MAX_FILE_BYTES + 1);
  if (raw.diff_state === "available") {
    if (typeof diff !== "string" || diff.length < 1 || diff.length > MAX_DIFF_CHARS || added === null || removed === null) {
      throw new AgentChangeSetPayloadError("available change diff was invalid");
    }
    const lines = diff.split("\n");
    const expectedFrom = summary.net_effect === "created" ? "/dev/null" : `a/${summary.path}`;
    const expectedTo = summary.net_effect === "deleted" ? "/dev/null" : `b/${summary.path}`;
    if (lines[0] !== `--- ${expectedFrom}` || lines[1] !== `+++ ${expectedTo}` || !lines.slice(2).some((line) => line.startsWith("@@"))) {
      throw new AgentChangeSetPayloadError("change diff headers were invalid");
    }
  } else if (diff !== null) {
    throw new AgentChangeSetPayloadError("content-free change diff carried text");
  }
  if (["no_change", "line_ending_only"].includes(raw.diff_state) && (added !== 0 || removed !== 0)) {
    throw new AgentChangeSetPayloadError("content-free change diff counts were invalid");
  }
  if (raw.diff_state === "no_change" && summary.net_effect !== "reverted") {
    throw new AgentChangeSetPayloadError("unchanged diff effect was incoherent");
  }
  if (raw.diff_state === "line_ending_only" && summary.net_effect !== "modified") {
    throw new AgentChangeSetPayloadError("line-ending diff effect was incoherent");
  }
  if (raw.diff_state === "too_large" && (added === null || removed === null)) {
    throw new AgentChangeSetPayloadError("oversized change diff counts were missing");
  }
  if (raw.diff_state === "unavailable" && (added !== null || removed !== null || summary.diff_available)) {
    throw new AgentChangeSetPayloadError("unavailable change diff was incoherent");
  }
  if (raw.diff_state !== "unavailable" && !summary.diff_available) {
    throw new AgentChangeSetPayloadError("change diff availability was incoherent");
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: sessionId(raw.session_id, expectedSessionId),
    summary,
    diff_state: raw.diff_state as AgentChangeDiff["diff_state"],
    diff: diff as string | null,
    added_lines: added,
    removed_lines: removed,
  };
}
