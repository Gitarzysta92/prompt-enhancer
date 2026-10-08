import type { CandidateDecisionsResponse, TaskDecision } from "./contracts";

const PSEUDONYM = /^[0-9a-f]{64}$/u;
const SAFE_CODE = /^[a-z0-9][a-z0-9._-]{0,127}$/u;
const ACTIONS = new Set(["accept", "reject", "merge", "split"]);
const ROLES = new Set(["input", "output"]);
const MAX_DECISIONS = 100;
const MAX_IDENTITIES = 100;

export class TaskDecisionPayloadError extends Error {
  constructor() {
    super("Decision audit response was invalid");
    this.name = "TaskDecisionPayloadError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === [...expected].sort()[index]);
}

function safeUtcTime(value: unknown): value is string {
  if (typeof value !== "string" || !/(?:Z|\+00:00)$/u.test(value)) return false;
  return Number.isFinite(new Date(value).getTime());
}

function safeIdentities(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length > 0
    && value.length <= MAX_IDENTITIES
    && value.every((item) => typeof item === "string" && PSEUDONYM.test(item))
    && new Set(value).size === value.length;
}

function parseDecision(value: unknown, candidateId: string): TaskDecision {
  if (!isRecord(value) || !exactKeys(value, [
    "action",
    "candidate_ids",
    "decided_at",
    "decision_code",
    "decision_id",
    "decision_schema_version",
    "decision_source",
    "revision_links",
  ])) throw new TaskDecisionPayloadError();
  if (
    typeof value.decision_id !== "string"
    || !PSEUDONYM.test(value.decision_id)
    || typeof value.action !== "string"
    || !ACTIONS.has(value.action)
    || !safeIdentities(value.candidate_ids)
    || !value.candidate_ids.includes(candidateId)
    || typeof value.decision_schema_version !== "string"
    || !SAFE_CODE.test(value.decision_schema_version)
    || (value.decision_code !== null
      && (typeof value.decision_code !== "string" || !SAFE_CODE.test(value.decision_code)))
    || !safeUtcTime(value.decided_at)
    || (value.decision_source !== "person" && value.decision_source !== "automation")
    || !Array.isArray(value.revision_links)
    || value.revision_links.length > MAX_IDENTITIES
  ) throw new TaskDecisionPayloadError();

  const revisionKeys = new Set<string>();
  const revisionLinks = value.revision_links.map((link) => {
    if (!isRecord(link) || !exactKeys(link, ["revision", "role", "task_id"])) {
      throw new TaskDecisionPayloadError();
    }
    if (
      typeof link.task_id !== "string"
      || !PSEUDONYM.test(link.task_id)
      || typeof link.revision !== "number"
      || !Number.isSafeInteger(link.revision)
      || link.revision < 1
      || typeof link.role !== "string"
      || !ROLES.has(link.role)
    ) throw new TaskDecisionPayloadError();
    const identity = `${link.role}:${link.task_id}:${link.revision}`;
    if (revisionKeys.has(identity)) throw new TaskDecisionPayloadError();
    revisionKeys.add(identity);
    return { task_id: link.task_id, revision: link.revision, role: link.role };
  });

  const isReject = value.action === "reject";
  if (isReject !== (value.decision_code !== null)) throw new TaskDecisionPayloadError();
  if (isReject && revisionLinks.length !== 0) throw new TaskDecisionPayloadError();

  return {
    decision_id: value.decision_id,
    action: value.action as TaskDecision["action"],
    candidate_ids: [...value.candidate_ids],
    revision_links: revisionLinks as TaskDecision["revision_links"],
    decision_schema_version: value.decision_schema_version,
    decision_code: value.decision_code,
    decided_at: value.decided_at,
    decision_source: value.decision_source,
  };
}

/** Strict, content-free boundary for the existing local decision-audit route. */
export function parseCandidateDecisionsResponse(
  value: unknown,
  expectedCandidateId: string,
): CandidateDecisionsResponse {
  if (!PSEUDONYM.test(expectedCandidateId)) throw new TaskDecisionPayloadError();
  if (
    !isRecord(value)
    || !exactKeys(value, ["candidate_id", "decisions"])
    || value.candidate_id !== expectedCandidateId
    || !Array.isArray(value.decisions)
    || value.decisions.length > MAX_DECISIONS
  ) throw new TaskDecisionPayloadError();
  const decisions = value.decisions.map((decision) => parseDecision(decision, expectedCandidateId));
  const identities = new Set(decisions.map((decision) => decision.decision_id));
  if (identities.size !== decisions.length) throw new TaskDecisionPayloadError();
  const ordered = [...decisions].sort((left, right) => {
    const byTime = left.decided_at.localeCompare(right.decided_at);
    return byTime !== 0 ? byTime : left.decision_id.localeCompare(right.decision_id);
  });
  if (ordered.some((decision, index) => decision.decision_id !== decisions[index].decision_id)) {
    throw new TaskDecisionPayloadError();
  }
  return { candidate_id: expectedCandidateId, decisions };
}
