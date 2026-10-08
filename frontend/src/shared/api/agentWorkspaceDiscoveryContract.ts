import type {
  AgentWorkspaceDiscovery,
  AgentWorkspaceDiscoveryFile,
  AgentWorkspaceGitChange,
} from "./contracts";

const CONTRACT_VERSION = "local-agent-workspace-discovery.v1";
const ID = /^[0-9a-f]{32}$/u;
const INVENTORY_REASONS = new Set([
  "deadline_reached", "depth_limit", "display_limit", "entry_limit",
  "excluded_directories", "link_or_reparse_entries", "unavailable_entries",
  "unrepresentable_entries",
]);
const GIT_REASONS = new Set([
  "command_cleanup_unconfirmed", "command_in_progress", "deadline_reached",
  "display_limit", "executable_unavailable", "excluded_paths", "output_limit",
  "repository_changed", "repository_layout_unsupported", "status_failed",
  "status_invalid", "unrepresentable_paths",
]);
const GIT_KINDS = new Set([
  "modified", "added", "deleted", "renamed", "copied", "type_changed",
  "untracked", "conflicted", "unknown",
]);
const MAX_FILES = 400;
const MAX_FILE_BYTES = 256_000;
const MAX_SCANNED = 20_000;

export class AgentWorkspaceDiscoveryPayloadError extends Error {}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery payload must be an object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery fields were invalid");
  }
}

function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery count was invalid");
  }
  return value as number;
}

function relativePath(value: unknown): string {
  if (typeof value !== "string" || value.length < 1 || value.length > 1024) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery path was invalid");
  }
  if (
    value.startsWith("/")
    || value.includes("\\")
    || /^[A-Za-z]:/u.test(value)
    || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
    || value.split("/").some((part) => part === "" || part === "." || part === "..")
    || hasUnpairedSurrogate(value)
  ) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery path escaped its root");
  }
  return value;
}

function hasUnpairedSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function reasons(value: unknown, allowed: ReadonlySet<string>, maximum: number): string[] {
  if (!Array.isArray(value) || value.length > maximum || value.some((item) => typeof item !== "string" || !allowed.has(item))) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery reasons were invalid");
  }
  const copy = value as string[];
  if (new Set(copy).size !== copy.length || copy.some((item, index) => index > 0 && copy[index - 1] >= item)) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery reasons were not unique and sorted");
  }
  return copy;
}

function file(value: unknown): AgentWorkspaceDiscoveryFile {
  const raw = record(value);
  exactKeys(raw, ["byte_size", "editable_candidate", "path"]);
  if (typeof raw.editable_candidate !== "boolean") {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery editability was invalid");
  }
  const byteSize = integer(raw.byte_size);
  if (raw.editable_candidate && byteSize > MAX_FILE_BYTES) {
    throw new AgentWorkspaceDiscoveryPayloadError("oversized discovery file claimed editability");
  }
  return {
    path: relativePath(raw.path),
    byte_size: byteSize,
    editable_candidate: raw.editable_candidate,
  };
}

function gitChange(value: unknown): AgentWorkspaceGitChange {
  const raw = record(value);
  exactKeys(raw, ["kind", "path", "staged", "unstaged"]);
  if (typeof raw.kind !== "string" || !GIT_KINDS.has(raw.kind) || typeof raw.staged !== "boolean" || typeof raw.unstaged !== "boolean") {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace Git change was invalid");
  }
  if (raw.kind === "untracked" && (raw.staged || raw.unstaged)) {
    throw new AgentWorkspaceDiscoveryPayloadError("untracked Git change claimed staging");
  }
  if (raw.kind === "conflicted" && !(raw.staged && raw.unstaged)) {
    throw new AgentWorkspaceDiscoveryPayloadError("conflicted Git change omitted a side");
  }
  return {
    path: relativePath(raw.path),
    kind: raw.kind as AgentWorkspaceGitChange["kind"],
    staged: raw.staged,
    unstaged: raw.unstaged,
  };
}

function uniqueSortedPaths(values: readonly { path: string }[], label: string): void {
  const paths = values.map((item) => item.path);
  if (
    new Set(paths).size !== paths.length
    || paths.some((path, index) => index > 0 && compareUtf8(paths[index - 1], path) > 0)
  ) {
    throw new AgentWorkspaceDiscoveryPayloadError(`${label} paths were not unique and sorted`);
  }
}

function compareUtf8(left: string, right: string): number {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  const length = Math.min(leftBytes.length, rightBytes.length);
  for (let index = 0; index < length; index += 1) {
    if (leftBytes[index] !== rightBytes[index]) return leftBytes[index] - rightBytes[index];
  }
  return leftBytes.length - rightBytes.length;
}

export function parseAgentWorkspaceDiscovery(
  value: unknown,
  expectedSessionId: string,
): AgentWorkspaceDiscovery {
  const raw = record(value);
  exactKeys(raw, [
    "contract_version", "files", "git_change_count", "git_changes", "git_coverage",
    "git_reasons", "git_state", "inventory_coverage", "inventory_reasons",
    "observed_file_count", "scanned_entry_count", "scope", "session_id",
  ]);
  if (
    raw.contract_version !== CONTRACT_VERSION
    || raw.scope !== "selected_workspace"
    || typeof raw.session_id !== "string"
    || !ID.test(raw.session_id)
    || raw.session_id !== expectedSessionId
    || !Array.isArray(raw.files)
    || raw.files.length > MAX_FILES
    || !Array.isArray(raw.git_changes)
    || raw.git_changes.length > MAX_FILES
  ) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace discovery envelope was invalid");
  }
  const files = raw.files.map(file);
  const gitChanges = raw.git_changes.map(gitChange);
  uniqueSortedPaths(files, "inventory");
  uniqueSortedPaths(gitChanges, "Git");
  const inventoryReasons = reasons(raw.inventory_reasons, INVENTORY_REASONS, INVENTORY_REASONS.size);
  const gitReasons = reasons(raw.git_reasons, GIT_REASONS, GIT_REASONS.size);
  const scanned = integer(raw.scanned_entry_count, MAX_SCANNED);
  const observed = integer(raw.observed_file_count, MAX_SCANNED);
  if (observed < files.length || scanned < observed) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace inventory counts were incoherent");
  }
  if (raw.inventory_coverage === "complete") {
    if (inventoryReasons.length !== 0 || observed !== files.length) {
      throw new AgentWorkspaceDiscoveryPayloadError("complete workspace inventory omitted evidence");
    }
  } else if (raw.inventory_coverage !== "partial" || inventoryReasons.length === 0) {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace inventory coverage was invalid");
  }

  let gitChangeCount: number | null;
  if (raw.git_change_count === null) gitChangeCount = null;
  else gitChangeCount = integer(raw.git_change_count);
  if (raw.git_state === "available") {
    if (gitChangeCount === null || gitChangeCount < gitChanges.length || !["complete", "partial"].includes(String(raw.git_coverage))) {
      throw new AgentWorkspaceDiscoveryPayloadError("available Git state was incoherent");
    }
    if (raw.git_coverage === "complete") {
      if (gitReasons.length !== 0 || gitChangeCount !== gitChanges.length) {
        throw new AgentWorkspaceDiscoveryPayloadError("complete Git state omitted evidence");
      }
    } else if (gitReasons.length === 0) {
      throw new AgentWorkspaceDiscoveryPayloadError("partial Git state omitted its reason");
    }
  } else if (raw.git_state === "not_repository") {
    if (raw.git_coverage !== "not_applicable" || gitReasons.length !== 0 || gitChangeCount !== 0 || gitChanges.length !== 0) {
      throw new AgentWorkspaceDiscoveryPayloadError("non-repository Git state was incoherent");
    }
  } else if (raw.git_state === "unavailable") {
    if (raw.git_coverage !== "unavailable" || gitReasons.length === 0 || gitChangeCount !== null || gitChanges.length !== 0) {
      throw new AgentWorkspaceDiscoveryPayloadError("unavailable Git state was incoherent");
    }
  } else {
    throw new AgentWorkspaceDiscoveryPayloadError("workspace Git state was invalid");
  }

  return {
    contract_version: CONTRACT_VERSION,
    session_id: raw.session_id,
    scope: "selected_workspace",
    inventory_coverage: raw.inventory_coverage,
    inventory_reasons: inventoryReasons as AgentWorkspaceDiscovery["inventory_reasons"],
    scanned_entry_count: scanned,
    observed_file_count: observed,
    files,
    git_state: raw.git_state,
    git_coverage: raw.git_coverage,
    git_reasons: gitReasons as AgentWorkspaceDiscovery["git_reasons"],
    git_change_count: gitChangeCount,
    git_changes: gitChanges,
  } as AgentWorkspaceDiscovery;
}
