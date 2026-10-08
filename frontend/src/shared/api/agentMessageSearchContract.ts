export interface AgentMessageSearchRequest {
  query: string;
  projectId?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
  snapshot?: string;
}

export interface AgentMessageSearchMatch {
  session_id: string;
  project_id: string;
  project_name: string;
  title: string;
  match_event_seq: number;
  history_revision: number;
  role: "user" | "assistant";
  excerpt: string;
}

export interface AgentMessageSearchResult {
  contract_version: "agent-message-search.v1";
  snapshot: string;
  limit: number;
  offset: number;
  total: number;
  next_offset: number | null;
  complete: boolean;
  matches: AgentMessageSearchMatch[];
}

export class AgentMessageSearchPayloadError extends Error {
  constructor(message = "Agent message search payload was invalid") {
    super(message);
    this.name = "AgentMessageSearchPayloadError";
  }
}

const ID = /^[0-9a-f]{32}$/u;
const SNAPSHOT = /^[0-9a-f]{64}$/u;

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new AgentMessageSearchPayloadError();
  return value as Record<string, unknown>;
}

function exact(value: Record<string, unknown>, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new AgentMessageSearchPayloadError();
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) throw new AgentMessageSearchPayloadError();
  return value;
}

function label(value: unknown, maximum: number): string {
  if (typeof value !== "string" || value.length < 1 || Array.from(value).length > maximum || value !== value.trim() || /[\u0000-\u001f\u007f]/u.test(value)) throw new AgentMessageSearchPayloadError();
  return value;
}

export function parseAgentMessageSearchResult(value: unknown, request: AgentMessageSearchRequest): AgentMessageSearchResult {
  const raw = object(value);
  exact(raw, ["contract_version", "snapshot", "limit", "offset", "total", "next_offset", "complete", "matches"]);
  if (raw.contract_version !== "agent-message-search.v1" || typeof raw.snapshot !== "string" || !SNAPSHOT.test(raw.snapshot)) throw new AgentMessageSearchPayloadError();
  const limit = integer(raw.limit, 1, 50);
  const offset = integer(raw.offset, 0, 2000);
  const total = integer(raw.total, 0, 2000);
  if ((request.limit ?? 20) !== limit || (request.offset ?? 0) !== offset || (request.snapshot !== undefined && request.snapshot !== raw.snapshot) || offset > total) throw new AgentMessageSearchPayloadError("Agent message search pagination did not match the request");
  if (typeof raw.complete !== "boolean" || !Array.isArray(raw.matches) || raw.matches.length > limit) throw new AgentMessageSearchPayloadError();
  const nextOffset = raw.next_offset === null ? null : integer(raw.next_offset, 0, 2000);
  const expectedCount = Math.min(limit, total - offset);
  if (raw.matches.length !== expectedCount || raw.complete !== (offset + raw.matches.length === total)
    || (raw.complete ? nextOffset !== null : nextOffset !== offset + raw.matches.length)) throw new AgentMessageSearchPayloadError("Agent message search pagination was incoherent");
  const matches = raw.matches.map((item) => {
    const match = object(item);
    exact(match, ["session_id", "project_id", "project_name", "title", "match_event_seq", "history_revision", "role", "excerpt"]);
    if (typeof match.session_id !== "string" || !ID.test(match.session_id) || typeof match.project_id !== "string" || !ID.test(match.project_id)) throw new AgentMessageSearchPayloadError();
    const role: "user" | "assistant" = match.role === "user" || match.role === "assistant" ? match.role : (() => { throw new AgentMessageSearchPayloadError(); })();
    return {
      session_id: match.session_id,
      project_id: match.project_id,
      project_name: label(match.project_name, 120),
      title: label(match.title, 120),
      match_event_seq: integer(match.match_event_seq, 1, 2_000_000_000),
      history_revision: integer(match.history_revision, 1, 2_000_000_000),
      role,
      excerpt: typeof match.excerpt === "string" && match.excerpt.length >= 1 && Array.from(match.excerpt).length <= 240
        ? match.excerpt
        : (() => { throw new AgentMessageSearchPayloadError(); })(),
    };
  });
  if (new Set(matches.map((match) => match.session_id)).size !== matches.length) throw new AgentMessageSearchPayloadError("Agent message search matches were incoherent");
  if (request.projectId !== undefined && matches.some((match) => match.project_id !== request.projectId)) throw new AgentMessageSearchPayloadError("Agent message search scope did not match the request");
  return { contract_version: "agent-message-search.v1", snapshot: raw.snapshot, limit, offset, total, next_offset: nextOffset, complete: raw.complete, matches };
}
