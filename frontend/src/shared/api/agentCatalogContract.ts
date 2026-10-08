import type {
  AgentCatalogSession,
  AgentCatalogSessionList,
  AgentCatalogSessionPage,
  AgentProject,
  AgentProjectList,
  AgentProjectPage,
  AgentSessionForkReceipt,
  AgentSessionLineage,
} from "./contracts";

const ID = /^[0-9a-f]{32}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const UTC_TIMESTAMP = /(?:Z|\+00:00)$/u;
const PROJECT_KEYS = new Set([
  "contract_version", "project_id", "name", "created_at", "updated_at",
  "revision", "pinned", "archived_at", "session_count", "is_default",
]);
const SESSION_KEYS = new Set([
  "contract_version", "session_id", "project_id", "title", "workspace",
  "model_alias", "created_at", "updated_at", "last_opened_at", "revision",
  "pinned", "archived_at", "history_state", "retention_policy",
  "history_revision", "last_event_seq", "turn_count", "conversation_available",
  "lineage",
]);
const LINEAGE_KEYS = new Set([
  "contract_version", "source_project_id", "source_session_id",
  "source_catalog_revision", "source_history_revision", "branch_event_seq",
  "copied_event_count", "copied_turn_count", "copied_attachment_count",
  "created_at",
]);
const FORK_RECEIPT_KEYS = new Set([
  "contract_version", "request_id", "idempotent_replay", "session",
  "source_tail_omitted", "approvals_copied", "mutation_authority_copied",
  "pending_tool_state_copied", "staged_attachments_copied", "artifacts_copied",
]);
const PROJECT_PAGE_KEYS = new Set([
  "contract_version", "snapshot", "limit", "offset", "total",
  "next_offset", "complete", "projects",
]);
const SESSION_PAGE_KEYS = new Set([
  "contract_version", "snapshot", "limit", "offset", "total",
  "next_offset", "complete", "sessions",
]);

export class AgentCatalogPayloadError extends Error {
  constructor() {
    super("Agent catalog payload was invalid");
    this.name = "AgentCatalogPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function timestamp(value: unknown): value is string {
  return typeof value === "string"
    && UTC_TIMESTAMP.test(value)
    && Number.isFinite(Date.parse(value));
}

function nullableTimestamp(value: unknown): value is string | null {
  return value === null || timestamp(value);
}

function boundedInteger(value: unknown, minimum: number): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum;
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && Array.from(value).length >= 1
    && Array.from(value).length <= maximum;
}

function normalizedLabel(value: unknown): value is string {
  return boundedText(value, 120)
    && value === value.trim()
    && !/\s{2,}/u.test(value);
}

export function parseAgentSessionLineage(value: unknown): AgentSessionLineage {
  if (
    !record(value) || !exact(value, LINEAGE_KEYS)
    || value.contract_version !== "agent-session-lineage.v1"
    || typeof value.source_project_id !== "string" || !ID.test(value.source_project_id)
    || typeof value.source_session_id !== "string" || !ID.test(value.source_session_id)
    || !boundedInteger(value.source_catalog_revision, 1)
    || !boundedInteger(value.source_history_revision, 0)
    || !boundedInteger(value.branch_event_seq, 0)
    || !boundedInteger(value.copied_event_count, 0)
    || (value.copied_event_count as number) > 4_000
    || !boundedInteger(value.copied_turn_count, 0)
    || (value.copied_turn_count as number) > (value.copied_event_count as number)
    || !boundedInteger(value.copied_attachment_count, 0)
    || !timestamp(value.created_at)
    || value.copied_event_count !== value.branch_event_seq
    || (value.branch_event_seq as number) > (value.source_history_revision as number)
  ) throw new AgentCatalogPayloadError();
  return value as unknown as AgentSessionLineage;
}

export function parseAgentProject(value: unknown): AgentProject {
  if (
    !record(value) || !exact(value, PROJECT_KEYS)
    || value.contract_version !== "agent-catalog.v2"
    || typeof value.project_id !== "string" || !ID.test(value.project_id)
    || !normalizedLabel(value.name)
    || !timestamp(value.created_at) || !timestamp(value.updated_at)
    || Date.parse(value.updated_at) < Date.parse(value.created_at)
    || !boundedInteger(value.revision, 1)
    || typeof value.pinned !== "boolean"
    || !nullableTimestamp(value.archived_at)
    || (value.archived_at !== null && Date.parse(value.archived_at) < Date.parse(value.created_at))
    || !boundedInteger(value.session_count, 0)
    || typeof value.is_default !== "boolean"
  ) throw new AgentCatalogPayloadError();
  return value as unknown as AgentProject;
}

export function parseAgentProjectList(value: unknown): AgentProjectList {
  if (
    !record(value)
    || Object.keys(value).length !== 2
    || value.contract_version !== "agent-catalog.v2"
    || !Array.isArray(value.projects)
    || value.projects.length > 200
  ) throw new AgentCatalogPayloadError();
  const projects = value.projects.map(parseAgentProject);
  if (new Set(projects.map((project) => project.project_id)).size !== projects.length) {
    throw new AgentCatalogPayloadError();
  }
  return { contract_version: "agent-catalog.v2", projects };
}

function validatePageShape(
  value: Record<string, unknown>,
  expectedLimit: number,
  expectedOffset: number,
  expectedSnapshot: string | undefined,
  itemCount: number,
  maximumTotal: number,
): void {
  if (
    value.contract_version !== "agent-catalog-page.v1"
    || typeof value.snapshot !== "string" || !SHA256.test(value.snapshot)
    || (expectedSnapshot !== undefined && value.snapshot !== expectedSnapshot)
    || value.limit !== expectedLimit
    || value.offset !== expectedOffset
    || !boundedInteger(value.total, 0) || (value.total as number) > maximumTotal
    || expectedOffset > (value.total as number)
    || itemCount !== Math.min(expectedLimit, (value.total as number) - expectedOffset)
    || typeof value.complete !== "boolean"
  ) throw new AgentCatalogPayloadError();
  const expectedNext = expectedOffset + itemCount < (value.total as number)
    ? expectedOffset + itemCount
    : null;
  if (value.next_offset !== expectedNext || value.complete !== (expectedNext === null)) {
    throw new AgentCatalogPayloadError();
  }
}

export function parseAgentProjectPage(
  value: unknown,
  expectedLimit: number,
  expectedOffset: number,
  expectedSnapshot?: string,
): AgentProjectPage {
  if (
    !record(value) || !exact(value, PROJECT_PAGE_KEYS)
    || !Array.isArray(value.projects)
    || value.projects.length > 100
  ) throw new AgentCatalogPayloadError();
  const projects = value.projects.map(parseAgentProject);
  validatePageShape(
    value,
    expectedLimit,
    expectedOffset,
    expectedSnapshot,
    projects.length,
    200,
  );
  if (new Set(projects.map((project) => project.project_id)).size !== projects.length) {
    throw new AgentCatalogPayloadError();
  }
  return { ...value, projects } as AgentProjectPage;
}

export function parseAgentCatalogSession(
  value: unknown,
  expectedSessionId?: string,
  expectedProjectId?: string,
): AgentCatalogSession {
  const lineage = record(value) && value.lineage !== null
    ? parseAgentSessionLineage(value.lineage)
    : null;
  if (
    !record(value) || !exact(value, SESSION_KEYS)
    || value.contract_version !== "agent-catalog.v2"
    || typeof value.session_id !== "string" || !ID.test(value.session_id)
    || (expectedSessionId !== undefined && value.session_id !== expectedSessionId)
    || typeof value.project_id !== "string" || !ID.test(value.project_id)
    || (expectedProjectId !== undefined && value.project_id !== expectedProjectId)
    || !normalizedLabel(value.title)
    || !boundedText(value.workspace, 1024)
    || !(value.model_alias === null || boundedText(value.model_alias, 64))
    || !timestamp(value.created_at) || !timestamp(value.updated_at) || !timestamp(value.last_opened_at)
    || Date.parse(value.updated_at) < Date.parse(value.created_at)
    || Date.parse(value.last_opened_at) < Date.parse(value.created_at)
    || !boundedInteger(value.revision, 1)
    || typeof value.pinned !== "boolean"
    || !nullableTimestamp(value.archived_at)
    || (value.archived_at !== null && Date.parse(value.archived_at) < Date.parse(value.created_at))
    || (value.history_state !== "memory_only" && value.history_state !== "durable_local")
    || (value.retention_policy !== "metadata_only" && value.retention_policy !== "local_history")
    || (value.history_state === "memory_only") !== (value.retention_policy === "metadata_only")
    || !boundedInteger(value.history_revision, 0)
    || !boundedInteger(value.last_event_seq, 0)
    || !boundedInteger(value.turn_count, 0)
    || (value.retention_policy === "metadata_only" && (
      value.history_revision !== 0 || value.last_event_seq !== 0 || value.turn_count !== 0
    ))
    || (value.turn_count as number) > (value.history_revision as number)
    || typeof value.conversation_available !== "boolean"
    || !(value.lineage === null || lineage !== null)
    || (lineage !== null && (
      value.retention_policy !== "local_history"
      || lineage.source_session_id === value.session_id
      || lineage.branch_event_seq !== value.last_event_seq
      || lineage.copied_event_count !== value.history_revision
      || lineage.copied_turn_count !== value.turn_count
      || Date.parse(lineage.created_at) !== Date.parse(value.created_at as string)
    ))
  ) throw new AgentCatalogPayloadError();
  return value as unknown as AgentCatalogSession;
}

export function parseAgentCatalogSessionList(
  value: unknown,
  expectedProjectId?: string,
): AgentCatalogSessionList {
  if (
    !record(value)
    || Object.keys(value).length !== 2
    || value.contract_version !== "agent-catalog.v2"
    || !Array.isArray(value.sessions)
    || value.sessions.length > 200
  ) throw new AgentCatalogPayloadError();
  const sessions = value.sessions.map((session) => (
    parseAgentCatalogSession(session, undefined, expectedProjectId)
  ));
  if (new Set(sessions.map((session) => session.session_id)).size !== sessions.length) {
    throw new AgentCatalogPayloadError();
  }
  return { contract_version: "agent-catalog.v2", sessions };
}

export function parseAgentCatalogSessionPage(
  value: unknown,
  expectedLimit: number,
  expectedOffset: number,
  expectedSnapshot?: string,
  expectedProjectId?: string,
): AgentCatalogSessionPage {
  if (
    !record(value) || !exact(value, SESSION_PAGE_KEYS)
    || !Array.isArray(value.sessions)
    || value.sessions.length > 100
  ) throw new AgentCatalogPayloadError();
  const sessions = value.sessions.map((session) => (
    parseAgentCatalogSession(session, undefined, expectedProjectId)
  ));
  validatePageShape(
    value,
    expectedLimit,
    expectedOffset,
    expectedSnapshot,
    sessions.length,
    2_000,
  );
  if (new Set(sessions.map((session) => session.session_id)).size !== sessions.length) {
    throw new AgentCatalogPayloadError();
  }
  return { ...value, sessions } as AgentCatalogSessionPage;
}

export function parseAgentSessionForkReceipt(value: unknown): AgentSessionForkReceipt {
  if (
    !record(value) || !exact(value, FORK_RECEIPT_KEYS)
    || value.contract_version !== "agent-session-fork.v1"
    || typeof value.request_id !== "string" || !ID.test(value.request_id)
    || typeof value.idempotent_replay !== "boolean"
    || typeof value.source_tail_omitted !== "boolean"
    || value.approvals_copied !== false
    || value.mutation_authority_copied !== false
    || value.pending_tool_state_copied !== false
    || value.staged_attachments_copied !== false
    || value.artifacts_copied !== false
  ) throw new AgentCatalogPayloadError();
  const session = parseAgentCatalogSession(value.session);
  if (session.lineage === null || session.lineage === undefined) {
    throw new AgentCatalogPayloadError();
  }
  return { ...value, session } as unknown as AgentSessionForkReceipt;
}
