import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "../../src/app/App";
import type { AgentCatalogSession, AgentEvent, AgentProject, AgentSessionView } from "../../src/shared/api/contracts";
import type { AgentMessageSearchRequest, AgentMessageSearchResult } from "../../src/shared/api/agentMessageSearchContract";
import { TransportError } from "../../src/shared/api/httpTransport";
import { createSyntheticTransport } from "../../src/shared/api/syntheticTransport";
import { createBrowserPlatform } from "../../src/shared/platform/browserPlatform";
import { createRuntimeComposition, type SyntheticRuntimeTransport } from "../../src/shared/platform/runtimeMode";
import "../../src/styles.css";
import "../../src/app/theme.css";
import "../../src/app/palette.generated.css";

window.history.replaceState(null, "", "/agent");
const PROJECT = "1".repeat(32); const OTHER = "2".repeat(32);
const RETAINED = "3".repeat(32); const SECOND = "7".repeat(32); const LIVE = "4".repeat(32); const ARCHIVED = "5".repeat(32); const METADATA = "6".repeat(32);
const SNAPSHOT = "a".repeat(64);
const counters = { create: 0, send: 0, resume: 0, activate: 0, slowAbort: 0, slowLate: 0, retainedReads: 0 };
const publish = () => Object.entries(counters).forEach(([key, value]) => document.documentElement.dataset[`messageSearch${key[0].toUpperCase()}${key.slice(1)}`] = String(value));
const project = (project_id: string, name: string): AgentProject => ({ contract_version: "agent-catalog.v2", project_id, name, created_at: "2040-01-01T00:00:00Z", updated_at: "2040-01-01T00:00:00Z", revision: 1, pinned: false, archived_at: null, session_count: 2, is_default: false });
const catalog = (session_id: string, project_id: string, title: string, overrides: Partial<AgentCatalogSession> = {}): AgentCatalogSession => ({ contract_version: "agent-catalog.v2", session_id, project_id, title, workspace: "D:/synthetic/disposable", model_alias: null, created_at: "2040-01-01T00:00:00Z", updated_at: "2040-01-01T00:00:00Z", last_opened_at: "2040-01-01T00:00:00Z", revision: 1, pinned: false, archived_at: null, history_state: "durable_local", retention_policy: "local_history", history_revision: 202, last_event_seq: 405, turn_count: 101, conversation_available: true, lineage: null, ...overrides });
const sessions = [
  catalog(RETAINED, PROJECT, "Retained synthetic chat"),
  catalog(SECOND, PROJECT, "Second retained synthetic chat", { history_revision: 1, last_event_seq: 9, turn_count: 1 }),
  catalog(LIVE, PROJECT, "Live synthetic draft", { history_state: "memory_only", retention_policy: "metadata_only", history_revision: 0, last_event_seq: 0, turn_count: 0, conversation_available: false }),
  catalog(ARCHIVED, OTHER, "Archived synthetic chat", { archived_at: "2040-01-02T00:00:00Z", history_revision: 2, last_event_seq: 7, turn_count: 1 }),
  catalog(METADATA, OTHER, "Metadata-only synthetic chat", { history_state: "memory_only", retention_policy: "metadata_only", history_revision: 0, last_event_seq: 0, turn_count: 0, conversation_available: false }),
];
const event = (seq: number, kind: "user" | "assistant", text: string): AgentEvent => ({ seq, kind, text, at: "2040-01-01T00:00:00Z", attachments: [] });
const retainedEvents = Array.from({ length: 202 }, (_, index) => event(
  index === 0 ? 2 : index === 201 ? 405 : index * 2 + 2,
  index % 2 === 0 ? "user" : "assistant",
  index === 0 ? "Synthetic early match outside the default window." : index === 201 ? "Synthetic retained final response." : `Synthetic retained event ${index + 1}.`,
));
const secondEvents = [event(4, "user", "Second synthetic request."), event(9, "assistant", "A synthetic <b>HTML-like</b> retained answer.")];
const archivedEvents = [event(3, "user", "Archived retained phrase."), event(7, "assistant", "Archived synthetic response.")];
let failNext = true;
function result(request: AgentMessageSearchRequest): AgentMessageSearchResult {
  if (request.query === "failure") { if (failNext) { failNext = false; throw new TransportError("Synthetic bounded failure", 503); } }
  const all = request.query.toLowerCase().includes("pagination") ? Array.from({ length: 21 }, (_, index) => ({ session_id: (index + 8).toString(16).padStart(32, "7"), project_id: PROJECT, project_name: "Synthetic project", title: `Paged synthetic chat ${index + 1}`, match_event_seq: index + 1, history_revision: index + 1, role: "user" as const, excerpt: `Synthetic page ${index + 1}.` })) : request.query.toLowerCase().includes("archived") ? [{ session_id: ARCHIVED, project_id: OTHER, project_name: "Other synthetic project", title: "Archived synthetic chat", match_event_seq: 3, history_revision: 2, role: "user" as const, excerpt: "Archived retained phrase." }] : [
    { session_id: RETAINED, project_id: PROJECT, project_name: "Synthetic project", title: "Retained synthetic chat", match_event_seq: 2, history_revision: 202, role: "user" as const, excerpt: "Synthetic early match outside the default window." },
    { session_id: SECOND, project_id: PROJECT, project_name: "Synthetic project", title: "Second retained synthetic chat", match_event_seq: 9, history_revision: 1, role: "assistant" as const, excerpt: "A synthetic <b>HTML-like</b> retained answer." },
  ];
  const archivedAllowed = request.includeArchived ? all : all.filter((match) => match.session_id !== ARCHIVED);
  const scoped = archivedAllowed.filter((match) => request.projectId === undefined || match.project_id === request.projectId);
  const offset = request.offset ?? 0; const limit = request.limit ?? 20; const matches = scoped.slice(offset, offset + limit);
  return { contract_version: "agent-message-search.v1", snapshot: SNAPSHOT, limit, offset, total: scoped.length, next_offset: offset + matches.length < scoped.length ? offset + matches.length : null, complete: offset + matches.length === scoped.length, matches };
}
const base = createSyntheticTransport();
const live: AgentSessionView = { contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false, session_id: LIVE, running: false, pending_approval_id: null, last_seq: 0, turns: 0, history_revision: 0, model_alias: null, created_at: "2040-01-01T00:00:00Z", recovered: false, authority_revalidated: true, history_write_failed: false, recovery_state: "current", settings: { workspace: "D:/synthetic/disposable", project_id: PROJECT, model_alias: null, parameters: { temperature: 0.2, top_p: 0.9, max_tokens: 100, enable_thinking: false }, instructions: null, allow_writes: false, allow_commands: false, allow_web: false, max_steps: 1, command_timeout_seconds: 1, title: "Live synthetic draft", retention_policy: "metadata_only" } };
const transport: SyntheticRuntimeTransport = { ...base,
  listAgentProjects: async () => ({ contract_version: "agent-catalog.v2", projects: [project(PROJECT, "Synthetic project"), project(OTHER, "Other synthetic project")] }),
  listAgentCatalogSessions: async (query) => ({ contract_version: "agent-catalog.v2", sessions: sessions.filter((item) => (query?.projectId === undefined || item.project_id === query.projectId) && (query?.includeArchived || item.archived_at === null)) }),
  getAgentCatalogSession: async (id) => { const found = sessions.find((item) => item.session_id === id); if (!found) throw new TransportError("missing", 404); return found; },
  getAgentPersistedEvents: async (_projectId, id, after) => { if (id === RETAINED) { counters.retainedReads++; publish(); } const history = id === RETAINED ? retainedEvents : id === SECOND ? secondEvents : archivedEvents; return { contract_version: "local-agent.v9" as const, cleanup_unconfirmed: false, closing: false, stopping: false, session_id: id, events: history.filter((item) => item.seq > after).slice(0, 100), running: false, pending_approval_id: null, first_seq: history[0]?.seq ?? 0, last_seq: history.at(-1)?.seq ?? 0 }; },
  listAgentSessions: async () => [live], searchAgentSavedMessages: async (request, signal) => { if (request.query === "slow") await new Promise<void>((resolve) => { signal?.addEventListener("abort", () => { counters.slowAbort++; publish(); }, { once: true }); setTimeout(() => { counters.slowLate++; publish(); resolve(); }, 100); }); return result(request); },
  createAgentSession: async (...args) => { counters.create++; publish(); return base.createAgentSession(...args); }, sendAgentMessage: async (...args) => { counters.send++; publish(); return base.sendAgentMessage(...args); }, resumeAgentSession: async (...args) => { counters.resume++; publish(); return base.resumeAgentSession(...args); }, activateLocalModel: async (...args) => { counters.activate++; publish(); return base.activateLocalModel(...args); },
};
publish(); createRoot(document.getElementById("root")!).render(<StrictMode><App platform={createBrowserPlatform()} runtime={createRuntimeComposition("synthetic_demo", transport)} /></StrictMode>);
