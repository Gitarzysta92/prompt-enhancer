import { describe, expect, it } from "vitest";

import {
  AgentArtifactPayloadError,
  parseAgentArtifactCapturePreview,
  parseAgentArtifactDetail,
  parseAgentArtifactExport,
  parseAgentArtifactPage,
  parseAgentDocumentPreview,
  parseAgentArtifactList,
} from "./agentArtifactContract";

const PROJECT_ID = "1".repeat(32);
const SESSION_ID = "2".repeat(32);
const ARTIFACT_ID = "3".repeat(32);
const SNAPSHOT = "a".repeat(64);

function version(number = 1, overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-artifact.v3",
    version_id: number.toString(16).repeat(32),
    artifact_id: ARTIFACT_ID,
    version_number: number,
    created_at: `2040-01-01T10:0${number}:00Z`,
    path: "docs/example.md",
    media_type: "text/markdown; charset=utf-8",
    preview_kind: "text",
    provenance: "reviewed_write",
    sha256: number.toString(16).repeat(64),
    byte_size: 120 + number,
    source_turn_id: "4".repeat(32),
    source_event_seq: number,
    ...overrides,
  };
}

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-artifact.v3",
    artifact_id: ARTIFACT_ID,
    project_id: PROJECT_ID,
    session_id: SESSION_ID,
    title: "example.md",
    kind: "markdown",
    path: "docs/example.md",
    created_at: "2040-01-01T10:01:00Z",
    updated_at: "2040-01-01T10:01:00Z",
    revision: 1,
    version_count: 1,
    availability: "available",
    lifecycle_state: "active",
    archived_at: null,
    removed_at: null,
    latest_version: version(),
    ...overrides,
  };
}

describe("Agent artifact response contracts", () => {
  it("accepts a content-free capture preview bound to the exact request", () => {
    const parsed = parseAgentArtifactCapturePreview({
      contract_version: "agent-artifact-capture-preview.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      path: "reports/example.pdf",
      title: "Reviewed report",
      kind: "pdf",
      media_type: "application/pdf",
      preview_kind: "pdf",
      sha256: "a".repeat(64),
      byte_size: 2048,
      requires_native_confirmation: true,
      file_content_included: false,
    }, PROJECT_ID, SESSION_ID, "reports/example.pdf", "Reviewed report");

    expect(parsed).toMatchObject({
      path: "reports/example.pdf",
      preview_kind: "pdf",
      file_content_included: false,
    });
  });

  it.each([
    ["wrong path", { path: "reports/other.pdf" }],
    ["cross-session identity", { session_id: "8".repeat(32) }],
    ["forged title", { title: "Other report" }],
    ["active media mismatch", { kind: "document", preview_kind: "download_only", media_type: "text/html" }],
    ["content leak", { file_content_included: true }],
    ["unknown key", { raw_content: "SYNTHETIC-PRIVATE-CANARY" }],
  ])("rejects a capture preview with %s", (_label, overrides) => {
    expect(() => parseAgentArtifactCapturePreview({
      contract_version: "agent-artifact-capture-preview.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      path: "reports/example.pdf",
      title: "example.pdf",
      kind: "pdf",
      media_type: "application/pdf",
      preview_kind: "pdf",
      sha256: "a".repeat(64),
      byte_size: 2048,
      requires_native_confirmation: true,
      file_content_included: false,
      ...overrides,
    }, PROJECT_ID, SESSION_ID, "reports/example.pdf")).toThrow(AgentArtifactPayloadError);
  });

  it("accepts an exact coherent list and immutable detail lineage", () => {
    expect(parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      counts: { active: 1, archived: 0, removed: 0, total: 1 },
      artifacts: [artifact()],
    }, PROJECT_ID, SESSION_ID).artifacts[0].kind).toBe("markdown");

    const first = version();
    const second = version(2);
    const detail = artifact({
      updated_at: "2040-01-01T10:02:00Z",
      revision: 2,
      version_count: 2,
      latest_version: second,
      versions: [first, second],
    });
    expect(parseAgentArtifactDetail(
      detail,
      PROJECT_ID,
      SESSION_ID,
      ARTIFACT_ID,
    ).versions).toHaveLength(2);
  });

  it("accepts an exact snapshot-bound artifact page", () => {
    const parsed = parseAgentArtifactPage({
      contract_version: "agent-artifact-page.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      snapshot: SNAPSHOT,
      limit: 1,
      offset: 0,
      total: 1,
      next_offset: null,
      complete: true,
      counts: { active: 1, archived: 0, removed: 0, total: 1 },
      artifacts: [artifact()],
    }, PROJECT_ID, SESSION_ID, "active", 1, 0);

    expect(parsed).toMatchObject({
      snapshot: SNAPSHOT,
      total: 1,
      complete: true,
    });
  });

  it.each([
    ["unknown key", { raw_content: "SYNTHETIC-PRIVATE-CANARY" }],
    ["wrong request scope", { session_id: "8".repeat(32) }],
    ["wrong lifecycle view", { view: "archived" }],
    ["wrong replay snapshot", { snapshot: "b".repeat(64) }],
    ["wrong request limit", { limit: 2 }],
    ["contradictory total", { total: 2, next_offset: null, complete: true }],
    ["contradictory counts", { counts: { active: 1, archived: 1, removed: 0, total: 1 } }],
  ])("rejects an artifact page with %s", (_label, overrides) => {
    expect(() => parseAgentArtifactPage({
      contract_version: "agent-artifact-page.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      snapshot: SNAPSHOT,
      limit: 1,
      offset: 0,
      total: 1,
      next_offset: null,
      complete: true,
      counts: { active: 1, archived: 0, removed: 0, total: 1 },
      artifacts: [artifact()],
      ...overrides,
    }, PROJECT_ID, SESSION_ID, "active", 1, 0, SNAPSHOT)).toThrow(AgentArtifactPayloadError);
  });

  it("rejects duplicate artifact identities and paths within a page", () => {
    const secondId = "5".repeat(32);
    const second = artifact({
      artifact_id: secondId,
      title: "second.md",
      path: "docs/second.md",
      latest_version: {
        ...version(),
        artifact_id: secondId,
        version_id: "6".repeat(32),
        path: "docs/second.md",
      },
    });
    const base = {
      contract_version: "agent-artifact-page.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      snapshot: SNAPSHOT,
      limit: 2,
      offset: 0,
      total: 2,
      next_offset: null,
      complete: true,
      counts: { active: 2, archived: 0, removed: 0, total: 2 },
    };

    expect(() => parseAgentArtifactPage({
      ...base,
      artifacts: [artifact(), artifact()],
    }, PROJECT_ID, SESSION_ID, "active", 2, 0)).toThrow(AgentArtifactPayloadError);
    expect(() => parseAgentArtifactPage({
      ...base,
      artifacts: [artifact(), {
        ...second,
        path: "docs/example.md",
        latest_version: { ...second.latest_version, path: "docs/example.md" },
      }],
    }, PROJECT_ID, SESSION_ID, "active", 2, 0)).toThrow(AgentArtifactPayloadError);
  });

  it("accepts lifecycle revisions without treating them as new immutable versions", () => {
    const archived = artifact({
      title: "Reviewed title",
      lifecycle_state: "archived",
      archived_at: "2040-01-01T10:03:00Z",
      updated_at: "2040-01-01T10:03:00Z",
      revision: 3,
    });
    const parsed = parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "archived",
      counts: { active: 0, archived: 1, removed: 0, total: 1 },
      artifacts: [archived],
    }, PROJECT_ID, SESSION_ID, "archived");

    expect(parsed.artifacts[0]).toMatchObject({
      lifecycle_state: "archived",
      revision: 3,
      version_count: 1,
    });
  });

  it("accepts only exact content-free lineage export evidence", () => {
    const selected = version();
    const detail = artifact({ versions: [selected] });
    const candidate = {
      contract_version: "agent-artifact-export.v1",
      exported_at: "2040-01-01T10:04:00Z",
      artifact: detail,
      selected_version: selected,
      evidence: {
        verification: "exact_current_workspace_readback",
        algorithm: "sha256",
        sha256: selected.sha256,
        byte_size: selected.byte_size,
        verified: true,
      },
      content_included: false,
      absolute_path_included: false,
      sensitivity: "sensitive_local_metadata",
    };

    expect(parseAgentArtifactExport(
      candidate,
      PROJECT_ID,
      SESSION_ID,
      ARTIFACT_ID,
      1,
      selected.version_id,
    )).toMatchObject({
      contract_version: "agent-artifact-export.v1",
      content_included: false,
      absolute_path_included: false,
    });

    const attacks = [
      { ...candidate, content_included: true },
      { ...candidate, absolute_path_included: true },
      { ...candidate, raw_content: "SYNTHETIC-PRIVATE-CANARY" },
      { ...candidate, evidence: { ...candidate.evidence, sha256: "9".repeat(64) } },
      { ...candidate, evidence: { ...candidate.evidence, verified: false } },
      { ...candidate, selected_version: { ...selected, version_id: "8".repeat(32) } },
      { ...candidate, artifact: { ...detail, project_id: "7".repeat(32) } },
    ];
    for (const attack of attacks) {
      expect(() => parseAgentArtifactExport(
        attack,
        PROJECT_ID,
        SESSION_ID,
        ARTIFACT_ID,
        1,
        selected.version_id,
      )).toThrow(AgentArtifactPayloadError);
    }
    expect(() => parseAgentArtifactExport(
      candidate,
      PROJECT_ID,
      SESSION_ID,
      ARTIFACT_ID,
      2,
      selected.version_id,
    )).toThrow(AgentArtifactPayloadError);
  });

  it.each([
    ["removed without archive", artifact({ lifecycle_state: "removed", removed_at: "2040-01-01T10:03:00Z", updated_at: "2040-01-01T10:03:00Z" })],
    ["active with archive timestamp", artifact({ archived_at: "2040-01-01T10:01:00Z" })],
    ["revision behind lineage", artifact({ revision: 1, version_count: 2, latest_version: version(2) })],
  ])("rejects incoherent lifecycle state: %s", (_label, candidate) => {
    expect(() => parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      counts: { active: 1, archived: 0, removed: 0, total: 1 },
      artifacts: [candidate],
    }, PROJECT_ID, SESSION_ID)).toThrow(AgentArtifactPayloadError);
  });

  it("rejects the wrong view and incoherent lifecycle counts", () => {
    expect(() => parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "archived",
      counts: { active: 1, archived: 0, removed: 0, total: 2 },
      artifacts: [],
    }, PROJECT_ID, SESSION_ID, "active")).toThrow(AgentArtifactPayloadError);
  });

  it("accepts a path-only reviewed move while refusing invented event provenance", () => {
    const first = version();
    const moved = version(2, {
      path: "archive/example.md",
      provenance: "reviewed_move",
      sha256: first.sha256,
      byte_size: first.byte_size,
      source_turn_id: null,
      source_event_seq: null,
    });
    const detail = artifact({
      path: "archive/example.md",
      updated_at: "2040-01-01T10:02:00Z",
      revision: 2,
      version_count: 2,
      latest_version: moved,
      versions: [first, moved],
    });
    expect(parseAgentArtifactDetail(
      detail,
      PROJECT_ID,
      SESSION_ID,
      ARTIFACT_ID,
    ).latest_version.provenance).toBe("reviewed_move");
    expect(() => parseAgentArtifactDetail({
      ...detail,
      latest_version: { ...moved, source_event_seq: 2 },
      versions: [first, { ...moved, source_event_seq: 2 }],
    }, PROJECT_ID, SESSION_ID, ARTIFACT_ID)).toThrow(AgentArtifactPayloadError);
    expect(() => parseAgentArtifactDetail({
      ...detail,
      latest_version: { ...moved, source_turn_id: "b".repeat(32) },
      versions: [first, { ...moved, source_turn_id: "b".repeat(32) }],
    }, PROJECT_ID, SESSION_ID, ARTIFACT_ID)).toThrow(AgentArtifactPayloadError);
  });

  it("accepts an exact document preview bound to the selected immutable version", () => {
    const selected = parseAgentArtifactDetail(artifact({
      kind: "document",
      path: "docs/example.docx",
      latest_version: version(1, {
        path: "docs/example.docx",
        media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        preview_kind: "document",
      }),
      versions: [version(1, {
        path: "docs/example.docx",
        media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        preview_kind: "document",
      })],
    }), PROJECT_ID, SESSION_ID, ARTIFACT_ID).versions[0];

    const preview = parseAgentDocumentPreview({
      contract_version: "agent-document-preview.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      artifact_id: ARTIFACT_ID,
      version_id: selected.version_id,
      source_sha256: selected.sha256,
      source_byte_size: selected.byte_size,
      format: "docx",
      sections: [{
        index: 1,
        kind: "document",
        title: "Document",
        paragraphs: ["Synthetic design note"],
        rows: [{ cells: ["Field", "Value"] }],
        truncated: false,
      }],
      omitted_features: ["media", "comments"],
      truncated: false,
    }, PROJECT_ID, SESSION_ID, ARTIFACT_ID, selected);

    expect(preview.sections[0].rows[0].cells).toEqual(["Field", "Value"]);
  });

  it.each([
    ["wrong source digest", { source_sha256: "9".repeat(64) }],
    ["cross-session identity", { session_id: "8".repeat(32) }],
    ["unknown key", { raw_xml: "SYNTHETIC-PRIVATE-CANARY" }],
    ["duplicate omission", { omitted_features: ["media", "media"] }],
    ["non-contiguous section", {
      sections: [{
        index: 2,
        kind: "document",
        title: "Document",
        paragraphs: [],
        rows: [],
        truncated: false,
      }],
    }],
    ["active-format mismatch", { format: "pptx" }],
  ])("rejects a document preview with %s", (_label, overrides) => {
    const selected = parseAgentArtifactDetail(artifact({
      kind: "document",
      path: "docs/example.docx",
      latest_version: version(1, {
        path: "docs/example.docx",
        media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        preview_kind: "document",
      }),
      versions: [version(1, {
        path: "docs/example.docx",
        media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        preview_kind: "document",
      })],
    }), PROJECT_ID, SESSION_ID, ARTIFACT_ID).versions[0];
    const candidate = {
      contract_version: "agent-document-preview.v1",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      artifact_id: ARTIFACT_ID,
      version_id: selected.version_id,
      source_sha256: selected.sha256,
      source_byte_size: selected.byte_size,
      format: "docx",
      sections: [{
        index: 1,
        kind: "document",
        title: "Document",
        paragraphs: [],
        rows: [],
        truncated: false,
      }],
      omitted_features: [],
      truncated: false,
      ...overrides,
    };

    expect(() => parseAgentDocumentPreview(
      candidate,
      PROJECT_ID,
      SESSION_ID,
      ARTIFACT_ID,
      selected,
    )).toThrow(AgentArtifactPayloadError);
  });

  it.each([
    ["extra metadata", artifact({ raw_content: "SYNTHETIC-PRIVATE-CANARY" })],
    ["cross-project identity", artifact({ project_id: "5".repeat(32) })],
    ["traversal path", artifact({ path: "../outside.md" })],
    ["invented preview", artifact({ latest_version: version(1, { preview_kind: "html" }) })],
    ["unproved active media", artifact({ latest_version: version(1, { preview_kind: "download_only", media_type: "text/html" }) })],
    ["unsafe byte count", artifact({ latest_version: version(1, { byte_size: Number.MAX_SAFE_INTEGER + 1 }) })],
  ])("rejects %s", (_label, value) => {
    expect(() => parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      counts: { active: 1, archived: 0, removed: 0, total: 1 },
      artifacts: [value],
    }, PROJECT_ID, SESSION_ID)).toThrow(AgentArtifactPayloadError);
  });

  it("rejects duplicate heads, incomplete versions, and a forged latest head", () => {
    expect(() => parseAgentArtifactList({
      contract_version: "agent-artifact.v3",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      view: "active",
      counts: { active: 2, archived: 0, removed: 0, total: 2 },
      artifacts: [artifact(), artifact()],
    }, PROJECT_ID, SESSION_ID)).toThrow(AgentArtifactPayloadError);

    expect(() => parseAgentArtifactDetail(artifact({
      updated_at: "2040-01-01T10:02:00Z",
      revision: 2,
      version_count: 2,
      latest_version: version(2),
      versions: [version(2), version(1)],
    }), PROJECT_ID, SESSION_ID, ARTIFACT_ID)).toThrow(AgentArtifactPayloadError);

    expect(() => parseAgentArtifactDetail(artifact({
      versions: [version(1, { sha256: "a".repeat(64) })],
    }), PROJECT_ID, SESSION_ID, ARTIFACT_ID)).toThrow(AgentArtifactPayloadError);
  });
});
