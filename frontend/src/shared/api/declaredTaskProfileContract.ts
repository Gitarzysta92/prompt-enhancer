import type {
  DeclaredTaskProfile,
  DeclaredTaskProfileCurrent,
  DeclaredTaskProfileOutcome,
} from "./contracts";

export const DECLARED_TASK_PROFILE_CONFIRMATION = "save_reviewed_declared_task_profile" as const;
export const DECLARED_TASK_PROFILE_CONSTRAINT_KINDS = [
  "cost",
  "delivery",
  "performance",
  "platform",
  "privacy",
  "safety",
  "scope",
  "version",
] as const;
export const DECLARED_TASK_PROFILE_DELIVERABLE_SLOTS = [
  "artifact",
  "audience",
  "compatibility",
  "format",
  "interface",
  "location",
] as const;

export class DeclaredTaskProfilePayloadError extends Error {
  constructor() {
    super("Reviewed task profile response was invalid");
    this.name = "DeclaredTaskProfilePayloadError";
  }
}

type Row = Record<string, unknown>;
const HEX_64 = /^[a-f0-9]{64}$/;
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/;

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new DeclaredTaskProfilePayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new DeclaredTaskProfilePayloadError();
  }
}

function safeId(value: unknown): value is string {
  return typeof value === "string" && HEX_64.test(value);
}

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isInteger(value) && (value as number) >= minimum && (value as number) <= maximum;
}

function utcTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !UTC_TIMESTAMP.test(value)) return false;
  const parsed = new Date(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  return match !== null
    && !Number.isNaN(parsed.getTime())
    && parsed.getUTCFullYear() === Number(match[1])
    && parsed.getUTCMonth() + 1 === Number(match[2])
    && parsed.getUTCDate() === Number(match[3])
    && parsed.getUTCHours() === Number(match[4])
    && parsed.getUTCMinutes() === Number(match[5])
    && parsed.getUTCSeconds() === Number(match[6]);
}

function configuredValues<T extends string>(
  value: unknown,
  allowed: readonly T[],
): readonly T[] | null {
  if (value === null) return null;
  if (!Array.isArray(value) || value.length === 0 || value.length > allowed.length) {
    throw new DeclaredTaskProfilePayloadError();
  }
  if (value.some((item) => typeof item !== "string" || !allowed.includes(item as T))) {
    throw new DeclaredTaskProfilePayloadError();
  }
  const values = value as T[];
  if (
    new Set(values).size !== values.length
    || [...values].sort().some((item, index) => item !== values[index])
  ) {
    throw new DeclaredTaskProfilePayloadError();
  }
  return values;
}

export function parseDeclaredTaskProfile(value: unknown, expectedSessionId: string): DeclaredTaskProfile {
  const profile = row(value);
  exact(profile, [
    "profile_id",
    "provider",
    "session_id",
    "revision",
    "previous_profile_id",
    "constraint_kinds",
    "expected_outcome_count",
    "deliverable_slots",
    "profile_fingerprint",
    "confirmed_at",
    "confirmation_authority",
    "schema_version",
    "policy_version",
    "local_only",
    "content_persisted",
  ]);
  const constraints = configuredValues(profile.constraint_kinds, DECLARED_TASK_PROFILE_CONSTRAINT_KINDS);
  const deliverables = configuredValues(profile.deliverable_slots, DECLARED_TASK_PROFILE_DELIVERABLE_SLOTS);
  const revision = profile.revision;
  if (
    !safeId(profile.profile_id)
    || !safeId(profile.session_id)
    || profile.session_id !== expectedSessionId
    || !["codex", "claude_code", "synthetic"].includes(String(profile.provider))
    || !integer(revision, 1, 1_000_000)
    || !(
      (revision === 1 && profile.previous_profile_id === null)
      || (revision > 1 && safeId(profile.previous_profile_id))
    )
    || !(profile.expected_outcome_count === null || integer(profile.expected_outcome_count, 1, 100))
    || !safeId(profile.profile_fingerprint)
    || !utcTimestamp(profile.confirmed_at)
    || profile.confirmation_authority !== "authenticated_local_user"
    || profile.schema_version !== "declared-task-profile-v1"
    || profile.policy_version !== "authenticated-local-user-v1"
    || profile.local_only !== true
    || profile.content_persisted !== false
  ) {
    throw new DeclaredTaskProfilePayloadError();
  }
  return {
    ...(profile as unknown as DeclaredTaskProfile),
    constraint_kinds: constraints,
    deliverable_slots: deliverables,
  };
}

export function parseDeclaredTaskProfileCurrent(
  value: unknown,
  expectedSessionId: string,
): DeclaredTaskProfileCurrent {
  const current = row(value);
  exact(current, ["session_id", "profile", "confirmation_available"]);
  if (
    !safeId(current.session_id)
    || current.session_id !== expectedSessionId
    || typeof current.confirmation_available !== "boolean"
  ) {
    throw new DeclaredTaskProfilePayloadError();
  }
  return {
    session_id: expectedSessionId,
    confirmation_available: current.confirmation_available,
    profile: current.profile === null
      ? null
      : parseDeclaredTaskProfile(current.profile, expectedSessionId),
  };
}

export function parseDeclaredTaskProfileOutcome(
  value: unknown,
  expectedSessionId: string,
): DeclaredTaskProfileOutcome {
  const outcome = row(value);
  exact(outcome, ["profile", "applied"]);
  if (typeof outcome.applied !== "boolean") throw new DeclaredTaskProfilePayloadError();
  return {
    profile: parseDeclaredTaskProfile(outcome.profile, expectedSessionId),
    applied: outcome.applied,
  };
}
