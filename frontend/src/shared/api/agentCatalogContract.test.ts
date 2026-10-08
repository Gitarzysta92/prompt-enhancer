import { describe, expect, it } from "vitest";

import {
  AgentCatalogPayloadError,
  parseAgentCatalogSession,
  parseAgentCatalogSessionList,
  parseAgentCatalogSessionPage,
  parseAgentProject,
  parseAgentProjectList,
  parseAgentProjectPage,
  parseAgentSessionForkReceipt,
  parseAgentSessionLineage,
} from "./agentCatalogContract";

const PROJECT_ID = "1".repeat(32);
const SESSION_ID = "2".repeat(32);
const SNAPSHOT = "a".repeat(64);

function project(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-catalog.v2",
    project_id: PROJECT_ID,
    name: "Example project",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    pinned: false,
    archived_at: null,
    session_count: 1,
    is_default: false,
    ...overrides,
  };
}

function session(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-catalog.v2",
    session_id: SESSION_ID,
    project_id: PROJECT_ID,
    title: "Example chat",
    workspace: "D:\\example\\workspace",
    model_alias: "example-model",
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    last_opened_at: "2040-01-01T10:00:00Z",
    revision: 2,
    pinned: true,
    archived_at: null,
    history_state: "memory_only",
    retention_policy: "metadata_only",
    history_revision: 0,
    last_event_seq: 0,
    turn_count: 0,
    conversation_available: false,
    lineage: null,
    ...overrides,
  };
}

function lineage(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-session-lineage.v1",
    source_project_id: PROJECT_ID,
    source_session_id: "3".repeat(32),
    source_catalog_revision: 2,
    source_history_revision: 7,
    branch_event_seq: 4,
    copied_event_count: 4,
    copied_turn_count: 1,
    copied_attachment_count: 0,
    created_at: "2040-01-01T10:00:00Z",
    ...overrides,
  };
}

function forkReceipt(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-session-fork.v1",
    request_id: "4".repeat(32),
    idempotent_replay: false,
    session: session({
      history_state: "durable_local",
      retention_policy: "local_history",
      history_revision: 4,
      last_event_seq: 4,
      turn_count: 1,
      conversation_available: true,
      lineage: lineage(),
    }),
    source_tail_omitted: true,
    approvals_copied: false,
    mutation_authority_copied: false,
    pending_tool_state_copied: false,
    staged_attachments_copied: false,
    artifacts_copied: false,
    ...overrides,
  };
}

describe("Agent catalog response contracts", () => {
  it("accepts exact versioned project and memory-only session records", () => {
    expect(parseAgentProject(project()).project_id).toBe(PROJECT_ID);
    expect(parseAgentCatalogSession(session(), SESSION_ID, PROJECT_ID)).toMatchObject({
      history_state: "memory_only",
      conversation_available: false,
    });
  });

  it.each([
    ["extra project field", project({ private_canary: "SYNTHETIC-PRIVATE-CANARY" })],
    ["non-normalized name", project({ name: " Example  project " })],
    ["unsafe revision", project({ revision: Number.MAX_SAFE_INTEGER + 1 })],
    ["backward timestamp", project({ updated_at: "2039-12-31T10:00:00Z" })],
  ])("rejects %s", (_label, value) => {
    expect(() => parseAgentProject(value)).toThrow(AgentCatalogPayloadError);
  });

  it.each([
    ["wrong session", session(), "3".repeat(32), PROJECT_ID],
    ["wrong project", session(), SESSION_ID, "4".repeat(32)],
    ["invented durable history", session({ history_state: "durable" }), SESSION_ID, PROJECT_ID],
    ["extra session field", session({ transcript: "SYNTHETIC-PRIVATE-CANARY" }), SESSION_ID, PROJECT_ID],
    ["backward opened time", session({ last_opened_at: "2039-12-31T10:00:00Z" }), SESSION_ID, PROJECT_ID],
  ])("rejects %s", (_label, value, expectedSession, expectedProject) => {
    expect(() => parseAgentCatalogSession(
      value,
      expectedSession,
      expectedProject,
    )).toThrow(AgentCatalogPayloadError);
  });

  it("rejects duplicate identifiers and unbounded list payloads", () => {
    expect(() => parseAgentProjectList({
      contract_version: "agent-catalog.v2",
      projects: [project(), project()],
    })).toThrow(AgentCatalogPayloadError);
    expect(() => parseAgentCatalogSessionList({
      contract_version: "agent-catalog.v2",
      sessions: [session(), session()],
    }, PROJECT_ID)).toThrow(AgentCatalogPayloadError);
    expect(() => parseAgentProjectList({
      contract_version: "agent-catalog.v2",
      projects: Array.from({ length: 201 }, (_, index) => project({
        project_id: index.toString(16).padStart(32, "0"),
      })),
    })).toThrow(AgentCatalogPayloadError);
  });

  it("accepts exact snapshot-bound project and chat pages", () => {
    const secondProject = project({
      project_id: "3".repeat(32),
      name: "Second project",
    });
    expect(parseAgentProjectPage({
      contract_version: "agent-catalog-page.v1",
      snapshot: SNAPSHOT,
      limit: 2,
      offset: 0,
      total: 2,
      next_offset: null,
      complete: true,
      projects: [project(), secondProject],
    }, 2, 0).projects).toHaveLength(2);

    const secondSession = session({
      session_id: "4".repeat(32),
      title: "Second chat",
    });
    expect(parseAgentCatalogSessionPage({
      contract_version: "agent-catalog-page.v1",
      snapshot: SNAPSHOT,
      limit: 1,
      offset: 1,
      total: 2,
      next_offset: null,
      complete: true,
      sessions: [secondSession],
    }, 1, 1, SNAPSHOT, PROJECT_ID).sessions[0].session_id).toBe("4".repeat(32));
  });

  it.each([
    ["unknown key", { private_canary: "SYNTHETIC-PRIVATE-CANARY" }],
    ["wrong request limit", { limit: 3 }],
    ["wrong request offset", { offset: 1, total: 2, next_offset: null, complete: true }],
    ["wrong replay snapshot", { snapshot: "b".repeat(64) }],
    ["contradictory continuation", { total: 2, next_offset: null, complete: true }],
    ["short non-terminal page", { total: 2, next_offset: 0, complete: false, projects: [] }],
  ])("rejects a project page with %s", (_label, overrides) => {
    expect(() => parseAgentProjectPage({
      contract_version: "agent-catalog-page.v1",
      snapshot: SNAPSHOT,
      limit: 1,
      offset: 0,
      total: 1,
      next_offset: null,
      complete: true,
      projects: [project()],
      ...overrides,
    }, 1, 0, SNAPSHOT)).toThrow(AgentCatalogPayloadError);
  });

  it("rejects duplicate page identities and cross-project chat pages", () => {
    expect(() => parseAgentProjectPage({
      contract_version: "agent-catalog-page.v1",
      snapshot: SNAPSHOT,
      limit: 2,
      offset: 0,
      total: 2,
      next_offset: null,
      complete: true,
      projects: [project(), project()],
    }, 2, 0, SNAPSHOT)).toThrow(AgentCatalogPayloadError);

    expect(() => parseAgentCatalogSessionPage({
      contract_version: "agent-catalog-page.v1",
      snapshot: SNAPSHOT,
      limit: 1,
      offset: 0,
      total: 1,
      next_offset: null,
      complete: true,
      sessions: [session({ project_id: "5".repeat(32) })],
    }, 1, 0, undefined, PROJECT_ID)).toThrow(AgentCatalogPayloadError);
  });

  it("accepts exact branch lineage and an authority-free fork receipt", () => {
    expect(parseAgentSessionLineage(lineage()).branch_event_seq).toBe(4);
    const parsed = parseAgentSessionForkReceipt(forkReceipt());
    expect(parsed.session.lineage?.source_session_id).toBe("3".repeat(32));
    expect(parsed.mutation_authority_copied).toBe(false);
  });

  it.each([
    ["extra lineage field", forkReceipt({
      session: session({
        history_state: "durable_local",
        retention_policy: "local_history",
        history_revision: 4,
        last_event_seq: 4,
        turn_count: 1,
        conversation_available: true,
        lineage: lineage({ raw_prompt: "SYNTHETIC-PRIVATE-CANARY" }),
      }),
    })],
    ["copied authority", forkReceipt({ mutation_authority_copied: true })],
    ["missing lineage", forkReceipt({ session: session() })],
    ["lineage event count mismatch", forkReceipt({
      session: session({
        history_state: "durable_local",
        retention_policy: "local_history",
        history_revision: 4,
        last_event_seq: 4,
        turn_count: 1,
        conversation_available: true,
        lineage: lineage({ copied_event_count: 3 }),
      }),
    })],
    ["branch beyond source history", forkReceipt({
      session: session({
        history_state: "durable_local",
        retention_policy: "local_history",
        history_revision: 4,
        last_event_seq: 4,
        turn_count: 1,
        conversation_available: true,
        lineage: lineage({ source_history_revision: 3 }),
      }),
    })],
    ["self lineage", forkReceipt({
      session: session({
        history_state: "durable_local",
        retention_policy: "local_history",
        history_revision: 4,
        last_event_seq: 4,
        turn_count: 1,
        conversation_available: true,
        lineage: lineage({ source_session_id: SESSION_ID }),
      }),
    })],
  ])("rejects unsafe fork payload: %s", (_label, value) => {
    expect(() => parseAgentSessionForkReceipt(value)).toThrow(
      AgentCatalogPayloadError,
    );
  });
});
