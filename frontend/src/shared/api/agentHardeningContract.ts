import type {
  AgentCatalogHardeningStatus,
  AgentHardeningSnapshot,
  AgentLiveHardeningFacts,
  AgentLiveHardeningStatus,
  AgentPersistenceCounts,
} from "./contracts";

const SNAPSHOT_KEYS = new Set([
  "contract_version",
  "generated_on_demand",
  "contains_content",
  "recovery_state",
  "recovery_actions",
  "catalog",
  "live",
]);
const CATALOG_KEYS = new Set([
  "state",
  "reason_code",
  "schema_version",
  "quick_check_passed",
  "foreign_key_violations_observed",
  "foreign_key_scan_truncated",
  "projection_violations",
  "counts",
]);
const PERSISTENCE_KEYS = new Set([
  "projects",
  "archived_projects",
  "sessions",
  "archived_sessions",
  "metadata_only_sessions",
  "retained_sessions",
  "history_events",
  "interrupted_retained_sessions",
  "artifacts",
  "artifact_versions",
  "staged_attachments",
  "attached_attachments",
]);
const LIVE_STATUS_KEYS = new Set(["state", "reason_code", "counts"]);
const LIVE_KEYS = new Set([
  "sessions",
  "running_turns",
  "closing_sessions",
  "pending_approvals",
  "cleanup_unconfirmed",
  "command_cleanup_quarantined",
  "recovered_read_only",
  "history_write_failures",
  "shutting_down",
]);
const CATALOG_REASONS = new Set([
  "catalog_path_invalid",
  "catalog_path_unsafe",
  "catalog_schema_newer",
  "catalog_migration_invalid",
  "catalog_storage_unavailable",
  "catalog_quick_check_failed",
  "catalog_foreign_key_violation",
  "catalog_projection_mismatch",
  "catalog_diagnostic_unavailable",
]);
const RECOVERY_ACTIONS = new Set([
  "inspect_local_catalog",
  "resume_interrupted_read_only",
  "revalidate_recovered_authority",
  "restart_after_cleanup_uncertain",
  "retry_after_history_write_failure",
  "verify_live_state",
]);

export class AgentHardeningPayloadError extends Error {
  constructor() {
    super("Agent hardening response was invalid");
    this.name = "AgentHardeningPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: Set<string>): boolean {
  const observed = Object.keys(value);
  return observed.length === keys.size && observed.every((key) => keys.has(key));
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nullableCount(value: unknown): value is number | null {
  return value === null || count(value);
}

function persistenceCounts(value: unknown): AgentPersistenceCounts {
  if (!record(value) || !exactKeys(value, PERSISTENCE_KEYS)) {
    throw new AgentHardeningPayloadError();
  }
  for (const key of PERSISTENCE_KEYS) {
    if (!count(value[key])) throw new AgentHardeningPayloadError();
  }
  const parsed = value as unknown as AgentPersistenceCounts;
  if (
    parsed.archived_projects > parsed.projects ||
    parsed.archived_sessions > parsed.sessions ||
    parsed.metadata_only_sessions + parsed.retained_sessions !== parsed.sessions ||
    parsed.interrupted_retained_sessions > parsed.retained_sessions
  ) {
    throw new AgentHardeningPayloadError();
  }
  return parsed;
}

function catalogStatus(value: unknown): AgentCatalogHardeningStatus {
  if (
    !record(value) ||
    !exactKeys(value, CATALOG_KEYS) ||
    !["ready", "degraded", "unavailable"].includes(String(value.state)) ||
    !(value.reason_code === null || CATALOG_REASONS.has(String(value.reason_code))) ||
    !(
      value.schema_version === null ||
      (count(value.schema_version) && value.schema_version >= 1)
    ) ||
    !(value.quick_check_passed === null || typeof value.quick_check_passed === "boolean") ||
    !nullableCount(value.foreign_key_violations_observed) ||
    typeof value.foreign_key_scan_truncated !== "boolean" ||
    !nullableCount(value.projection_violations)
  ) {
    throw new AgentHardeningPayloadError();
  }
  const unavailable = value.state === "unavailable";
  if (unavailable) {
    if (
      value.reason_code === null ||
      value.schema_version !== null ||
      value.quick_check_passed !== null ||
      value.foreign_key_violations_observed !== null ||
      value.foreign_key_scan_truncated !== false ||
      value.projection_violations !== null ||
      value.counts !== null
    ) {
      throw new AgentHardeningPayloadError();
    }
    return value as unknown as AgentCatalogHardeningStatus;
  }
  if (value.counts === null) throw new AgentHardeningPayloadError();
  persistenceCounts(value.counts);
  const quick = value.quick_check_passed;
  const foreignKeys = value.foreign_key_violations_observed;
  const projections = value.projection_violations;
  if (value.state === "ready") {
    if (value.reason_code !== null || quick !== true || foreignKeys !== 0 || projections !== 0) {
      throw new AgentHardeningPayloadError();
    }
  } else {
    const expected = quick !== true
      ? "catalog_quick_check_failed"
      : foreignKeys !== 0
        ? "catalog_foreign_key_violation"
        : projections !== 0
          ? "catalog_projection_mismatch"
          : null;
    if (value.reason_code !== expected) throw new AgentHardeningPayloadError();
  }
  return value as unknown as AgentCatalogHardeningStatus;
}

function liveFacts(value: unknown): AgentLiveHardeningFacts {
  if (!record(value) || !exactKeys(value, LIVE_KEYS)) {
    throw new AgentHardeningPayloadError();
  }
  for (const key of LIVE_KEYS) {
    if (key !== "shutting_down" && key !== "command_cleanup_quarantined" && !count(value[key])) {
      throw new AgentHardeningPayloadError();
    }
  }
  if (
    typeof value.shutting_down !== "boolean" ||
    typeof value.command_cleanup_quarantined !== "boolean"
  ) {
    throw new AgentHardeningPayloadError();
  }
  const parsed = value as unknown as AgentLiveHardeningFacts;
  for (const subcount of [
    parsed.running_turns,
    parsed.closing_sessions,
    parsed.pending_approvals,
    parsed.cleanup_unconfirmed,
    parsed.recovered_read_only,
    parsed.history_write_failures,
  ]) {
    if (subcount > parsed.sessions) throw new AgentHardeningPayloadError();
  }
  return parsed;
}

function liveStatus(value: unknown): AgentLiveHardeningStatus {
  if (
    !record(value) ||
    !exactKeys(value, LIVE_STATUS_KEYS) ||
    !["ready", "unavailable"].includes(String(value.state))
  ) {
    throw new AgentHardeningPayloadError();
  }
  if (value.state === "ready") {
    if (value.reason_code !== null || value.counts === null) {
      throw new AgentHardeningPayloadError();
    }
    liveFacts(value.counts);
  } else if (value.reason_code !== "live_state_unavailable" || value.counts !== null) {
    throw new AgentHardeningPayloadError();
  }
  return value as unknown as AgentLiveHardeningStatus;
}

export function parseAgentHardeningSnapshot(value: unknown): AgentHardeningSnapshot {
  if (
    !record(value) ||
    !exactKeys(value, SNAPSHOT_KEYS) ||
    value.contract_version !== "agent-hardening.v1" ||
    value.generated_on_demand !== true ||
    value.contains_content !== false ||
    !["clean", "attention_required", "unknown"].includes(String(value.recovery_state)) ||
    !Array.isArray(value.recovery_actions) ||
    value.recovery_actions.length > 6 ||
    value.recovery_actions.some((action) => !RECOVERY_ACTIONS.has(String(action))) ||
    new Set(value.recovery_actions).size !== value.recovery_actions.length
  ) {
    throw new AgentHardeningPayloadError();
  }
  const catalog = catalogStatus(value.catalog);
  const live = liveStatus(value.live);
  const expectedActions: string[] = [];
  if (catalog.state === "degraded") expectedActions.push("inspect_local_catalog");
  if (catalog.counts?.interrupted_retained_sessions) {
    expectedActions.push("resume_interrupted_read_only");
  }
  if (live.counts === null) {
    expectedActions.push("verify_live_state");
  } else {
    if (live.counts.recovered_read_only) {
      expectedActions.push("revalidate_recovered_authority");
    }
    if (live.counts.cleanup_unconfirmed || live.counts.command_cleanup_quarantined) {
      expectedActions.push("restart_after_cleanup_uncertain");
    }
    if (live.counts.history_write_failures) {
      expectedActions.push("retry_after_history_write_failure");
    }
  }
  const expectedRecovery = catalog.state === "unavailable"
    ? "unknown"
    : expectedActions.length > 0
      ? "attention_required"
      : "clean";
  if (
    value.recovery_state !== expectedRecovery ||
    value.recovery_actions.length !== expectedActions.length ||
    value.recovery_actions.some((action, index) => action !== expectedActions[index])
  ) {
    throw new AgentHardeningPayloadError();
  }
  return {
    contract_version: "agent-hardening.v1",
    generated_on_demand: true,
    contains_content: false,
    recovery_state: value.recovery_state as AgentHardeningSnapshot["recovery_state"],
    recovery_actions: value.recovery_actions as AgentHardeningSnapshot["recovery_actions"],
    catalog,
    live,
  };
}
