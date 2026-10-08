import type { AgentWorkspaceSearchResult } from "./contracts";

const CONTRACT_VERSION = "local-agent-workspace-search.v1";
const SESSION_ID = /^[0-9a-f]{32}$/u;
const REASON_CODE = /^[a-z][a-z0-9_]*$/u;
const MAX_RESULTS = 80;
const MAX_SCANNED_ENTRIES = 20_000;
const MAX_INSPECTED_BYTES = 16_000_000;

export class AgentWorkspaceSearchPayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentWorkspaceSearchPayloadError("workspace search payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentWorkspaceSearchPayloadError("workspace search payload fields were invalid");
  }
}

function integer(value: unknown, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > maximum) {
    throw new AgentWorkspaceSearchPayloadError("workspace search count was invalid");
  }
  return value as number;
}

function relativePath(value: unknown): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > 1024
    || value === "."
    || value.startsWith("/")
    || value.includes("\\")
    || value.includes("\0")
    || /^[A-Za-z]:/u.test(value)
    || value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new AgentWorkspaceSearchPayloadError("workspace search path was invalid");
  }
  return value;
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

export function parseAgentWorkspaceSearchResult(
  value: unknown,
  expectedSessionId: string,
): AgentWorkspaceSearchResult {
  const raw = record(value);
  exactKeys(raw, [
    "contract_version",
    "coverage",
    "inspected_byte_count",
    "match_count",
    "matches",
    "reason_code",
    "reasons",
    "scanned_entry_count",
    "scope",
    "session_id",
    "skipped_entry_count",
  ]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.scope !== "application_readable_utf8_text"
    || !SESSION_ID.test(String(raw.session_id))
    || raw.session_id !== expectedSessionId
    || !["complete", "partial"].includes(String(raw.coverage))
    || !Array.isArray(raw.reasons)
    || raw.reasons.length > 16
    || !Array.isArray(raw.matches)
    || raw.matches.length > MAX_RESULTS
  ) {
    throw new AgentWorkspaceSearchPayloadError("workspace search envelope was invalid");
  }

  const reasons = raw.reasons.map((reason) => {
    if (
      typeof reason !== "string"
      || reason.length < 1
      || Array.from(reason).length > 200
      || reason.trim() !== reason
    ) {
      throw new AgentWorkspaceSearchPayloadError("workspace search reason was invalid");
    }
    return reason;
  });
  if (new Set(reasons).size !== reasons.length || reasons.some((reason, index) => (
    index > 0 && reasons[index - 1] > reason
  ))) {
    throw new AgentWorkspaceSearchPayloadError("workspace search reasons were not canonical");
  }

  const reasonCode = raw.reason_code;
  if (reasonCode !== null && (typeof reasonCode !== "string" || !REASON_CODE.test(reasonCode))) {
    throw new AgentWorkspaceSearchPayloadError("workspace search reason code was invalid");
  }
  if (
    (raw.coverage === "complete" && (reasons.length > 0 || reasonCode !== null))
    || (raw.coverage === "partial" && (reasons.length === 0 || reasonCode === null))
  ) {
    throw new AgentWorkspaceSearchPayloadError("workspace search coverage was incoherent");
  }

  const matches = raw.matches.map((item) => {
    const match = record(item);
    exactKeys(match, ["line_number", "path", "preview"]);
    const path = relativePath(match.path);
    const lineNumber = integer(match.line_number, 2_147_483_647);
    if (
      lineNumber < 1
      || typeof match.preview !== "string"
      || Array.from(match.preview).length > 240
      || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(match.preview)
    ) {
      throw new AgentWorkspaceSearchPayloadError("workspace search match was invalid");
    }
    return { path, line_number: lineNumber, preview: match.preview };
  });
  const identities = new Set(matches.map((item) => `${item.path}\0${item.line_number}`));
  if (identities.size !== matches.length) {
    throw new AgentWorkspaceSearchPayloadError("workspace search matches were duplicated");
  }
  for (let index = 1; index < matches.length; index += 1) {
    const previous = matches[index - 1];
    const current = matches[index];
    const pathOrder = compareUtf8(previous.path, current.path);
    if (pathOrder > 0 || (pathOrder === 0 && previous.line_number >= current.line_number)) {
      throw new AgentWorkspaceSearchPayloadError("workspace search matches were not canonical");
    }
  }

  const scannedEntryCount = integer(raw.scanned_entry_count, MAX_SCANNED_ENTRIES);
  const skippedEntryCount = integer(raw.skipped_entry_count, MAX_SCANNED_ENTRIES);
  const matchCount = integer(raw.match_count, MAX_RESULTS);
  if (skippedEntryCount > scannedEntryCount || matchCount !== matches.length) {
    throw new AgentWorkspaceSearchPayloadError("workspace search counts were incoherent");
  }

  return {
    contract_version: CONTRACT_VERSION,
    session_id: expectedSessionId,
    scope: "application_readable_utf8_text",
    coverage: raw.coverage as AgentWorkspaceSearchResult["coverage"],
    reasons,
    reason_code: reasonCode,
    scanned_entry_count: scannedEntryCount,
    inspected_byte_count: integer(raw.inspected_byte_count, MAX_INSPECTED_BYTES),
    skipped_entry_count: skippedEntryCount,
    match_count: matchCount,
    matches,
  };
}
