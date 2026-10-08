import type {
  AgentArtifact,
  AgentArtifactCapturePreview,
  AgentArtifactDetail,
  AgentArtifactExport,
  AgentArtifactLifecycleCounts,
  AgentArtifactList,
  AgentArtifactListView,
  AgentArtifactPage,
  AgentArtifactVersion,
  AgentDocumentPreview,
} from "./contracts";

const ID = /^[0-9a-f]{32}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const UTC_TIMESTAMP = /(?:Z|\+00:00)$/u;
const SAFE_PATH = /^(?![./]|.*(?:^|\/)\.\.(?:\/|$))(?!.*[\\:\u0000-\u001f\u007f])[^/]+(?:\/[^/]+)*$/u;
const VERSION_KEYS = new Set([
  "contract_version", "version_id", "artifact_id", "version_number",
  "created_at", "path", "media_type", "preview_kind", "provenance",
  "sha256", "byte_size", "source_turn_id", "source_event_seq",
]);
const ARTIFACT_KEYS = new Set([
  "contract_version", "artifact_id", "project_id", "session_id", "title",
  "kind", "path", "created_at", "updated_at", "revision", "version_count",
  "availability", "latest_version", "lifecycle_state", "archived_at", "removed_at",
]);
const DETAIL_KEYS = new Set([...ARTIFACT_KEYS, "versions"]);
const LIST_KEYS = new Set([
  "contract_version", "project_id", "session_id", "view", "counts", "artifacts",
]);
const PAGE_KEYS = new Set([
  "contract_version", "project_id", "session_id", "view", "snapshot",
  "limit", "offset", "total", "next_offset", "complete", "counts",
  "artifacts",
]);
const COUNT_KEYS = new Set(["active", "archived", "removed", "total"]);
const EXPORT_KEYS = new Set([
  "contract_version", "exported_at", "artifact", "selected_version", "evidence",
  "content_included", "absolute_path_included", "sensitivity",
]);
const EXPORT_EVIDENCE_KEYS = new Set([
  "verification", "algorithm", "sha256", "byte_size", "verified",
]);
const KINDS = new Set([
  "code", "markdown", "text", "data", "image", "pdf", "document", "binary",
]);
const PREVIEWS = new Set(["text", "image", "pdf", "document", "download_only"]);
const PROVENANCE = new Set([
  "reviewed_write", "reviewed_move", "verified_output", "generated_unverified", "external_effect_unknown",
]);
const AVAILABILITY = new Set(["unchecked", "available", "stale", "missing", "malformed"]);
const LIFECYCLE_STATES = new Set(["active", "archived", "removed"]);
const LIST_VIEWS = new Set(["active", "archived", "removed", "all"]);
const MEDIA_TYPES = new Set([
  "text/plain; charset=utf-8",
  "text/markdown; charset=utf-8",
  "image/png",
  "image/jpeg",
  "image/gif",
  "application/pdf",
  "application/octet-stream",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.oasis.opendocument.text",
]);
const DOCUMENT_MEDIA_TYPES = new Set([
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.oasis.opendocument.text",
]);
const DOCUMENT_FORMAT_MEDIA_TYPE = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  odt: "application/vnd.oasis.opendocument.text",
} as const;
const DOCUMENT_PREVIEW_KEYS = new Set([
  "contract_version", "project_id", "session_id", "artifact_id", "version_id",
  "source_sha256", "source_byte_size", "format", "sections", "omitted_features",
  "truncated",
]);
const DOCUMENT_SECTION_KEYS = new Set([
  "index", "kind", "title", "paragraphs", "rows", "truncated",
]);
const DOCUMENT_ROW_KEYS = new Set(["cells"]);
const DOCUMENT_FORMATS = new Set(["docx", "pptx", "xlsx", "odt"]);
const DOCUMENT_SECTION_KINDS = new Set(["document", "slide", "sheet"]);
const DOCUMENT_OMITTED = new Set([
  "comments", "embedded_objects", "external_links", "macros", "media", "notes",
]);
const CAPTURE_PREVIEW_KEYS = new Set([
  "contract_version", "project_id", "session_id", "path", "title", "kind",
  "media_type", "preview_kind", "sha256", "byte_size",
  "requires_native_confirmation", "file_content_included",
]);

export class AgentArtifactPayloadError extends Error {
  constructor() {
    super("Agent artifact payload was invalid");
    this.name = "AgentArtifactPayloadError";
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

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && value <= maximum;
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && Array.from(value).length >= 1
    && Array.from(value).length <= maximum;
}

function characterCount(value: string): number {
  return Array.from(value).length;
}

function defaultArtifactTitle(path: string): string {
  return Array.from(path.split("/").at(-1) ?? "").slice(0, 120).join("");
}

export function parseAgentArtifactCapturePreview(
  value: unknown,
  expectedProjectId: string,
  expectedSessionId: string,
  expectedPath: string,
  expectedTitle?: string | null,
): AgentArtifactCapturePreview {
  if (
    !record(value) || !exact(value, CAPTURE_PREVIEW_KEYS)
    || value.contract_version !== "agent-artifact-capture-preview.v1"
    || value.project_id !== expectedProjectId
    || value.session_id !== expectedSessionId
    || value.path !== expectedPath || !SAFE_PATH.test(expectedPath)
    || !text(value.title, 120)
    || value.title !== (expectedTitle ?? defaultArtifactTitle(expectedPath))
    || typeof value.kind !== "string" || !KINDS.has(value.kind)
    || typeof value.media_type !== "string" || !MEDIA_TYPES.has(value.media_type)
    || typeof value.preview_kind !== "string" || !PREVIEWS.has(value.preview_kind)
    || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)
    || !integer(value.byte_size, 0, 24 * 1024 * 1024)
    || value.requires_native_confirmation !== true
    || value.file_content_included !== false
    || (value.preview_kind === "image" && (value.kind !== "image" || !String(value.media_type).startsWith("image/")))
    || (value.preview_kind === "pdf" && (value.kind !== "pdf" || value.media_type !== "application/pdf"))
    || (value.preview_kind === "document" && (value.kind !== "document" || !DOCUMENT_MEDIA_TYPES.has(String(value.media_type))))
    || (value.preview_kind === "download_only" && !["document", "binary"].includes(String(value.kind)))
    || (value.preview_kind === "download_only" && value.media_type !== "application/octet-stream")
    || (value.preview_kind === "text" && !["code", "markdown", "text", "data"].includes(String(value.kind)))
  ) throw new AgentArtifactPayloadError();
  return value as unknown as AgentArtifactCapturePreview;
}

function sameVersion(left: AgentArtifactVersion, right: AgentArtifactVersion): boolean {
  return VERSION_KEYS.size === Object.keys(left).length
    && VERSION_KEYS.size === Object.keys(right).length
    && [...VERSION_KEYS].every((key) => (
      left[key as keyof AgentArtifactVersion] === right[key as keyof AgentArtifactVersion]
    ));
}

export function parseAgentArtifactVersion(
  value: unknown,
  expectedArtifactId?: string,
): AgentArtifactVersion {
  if (
    !record(value) || !exact(value, VERSION_KEYS)
    || value.contract_version !== "agent-artifact.v3"
    || typeof value.version_id !== "string" || !ID.test(value.version_id)
    || typeof value.artifact_id !== "string" || !ID.test(value.artifact_id)
    || (expectedArtifactId !== undefined && value.artifact_id !== expectedArtifactId)
    || !integer(value.version_number, 1, 2_000)
    || !timestamp(value.created_at)
    || typeof value.path !== "string" || value.path.length > 1024 || !SAFE_PATH.test(value.path)
    || typeof value.media_type !== "string" || !MEDIA_TYPES.has(value.media_type)
    || typeof value.preview_kind !== "string" || !PREVIEWS.has(value.preview_kind)
    || typeof value.provenance !== "string" || !PROVENANCE.has(value.provenance)
    || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)
    || !integer(value.byte_size, 0, 24 * 1024 * 1024)
    || !(value.source_turn_id === null || (typeof value.source_turn_id === "string" && ID.test(value.source_turn_id)))
    || !(value.source_event_seq === null || integer(value.source_event_seq, 1, Number.MAX_SAFE_INTEGER))
    || (value.provenance === "reviewed_write" && value.source_event_seq === null)
    || (value.provenance === "reviewed_move" && (
      value.source_turn_id !== null || value.source_event_seq !== null
    ))
    || (value.preview_kind === "image" && !String(value.media_type).startsWith("image/"))
    || (value.preview_kind === "pdf" && value.media_type !== "application/pdf")
    || (value.preview_kind === "document" && !DOCUMENT_MEDIA_TYPES.has(String(value.media_type)))
    || (value.preview_kind === "download_only" && value.media_type !== "application/octet-stream")
  ) throw new AgentArtifactPayloadError();
  return value as unknown as AgentArtifactVersion;
}

export function parseAgentDocumentPreview(
  value: unknown,
  expectedProjectId: string,
  expectedSessionId: string,
  expectedArtifactId: string,
  expectedVersion: AgentArtifactVersion,
): AgentDocumentPreview {
  if (
    !record(value) || !exact(value, DOCUMENT_PREVIEW_KEYS)
    || value.contract_version !== "agent-document-preview.v1"
    || value.project_id !== expectedProjectId
    || value.session_id !== expectedSessionId
    || value.artifact_id !== expectedArtifactId
    || value.version_id !== expectedVersion.version_id
    || value.source_sha256 !== expectedVersion.sha256
    || value.source_byte_size !== expectedVersion.byte_size
    || typeof value.format !== "string" || !DOCUMENT_FORMATS.has(value.format)
    || expectedVersion.preview_kind !== "document"
    || expectedVersion.byte_size < 1
    || expectedVersion.media_type !== DOCUMENT_FORMAT_MEDIA_TYPE[
      value.format as keyof typeof DOCUMENT_FORMAT_MEDIA_TYPE
    ]
    || !Array.isArray(value.sections) || value.sections.length < 1 || value.sections.length > 64
    || !Array.isArray(value.omitted_features) || value.omitted_features.length > 6
    || value.omitted_features.some((item) => typeof item !== "string" || !DOCUMENT_OMITTED.has(item))
    || new Set(value.omitted_features).size !== value.omitted_features.length
    || typeof value.truncated !== "boolean"
  ) throw new AgentArtifactPayloadError();

  let rows = 0;
  let characters = 0;
  const expectedKind = value.format === "pptx"
    ? "slide"
    : value.format === "xlsx"
      ? "sheet"
      : "document";
  for (const [offset, section] of value.sections.entries()) {
    if (
      !record(section) || !exact(section, DOCUMENT_SECTION_KEYS)
      || section.index !== offset + 1
      || typeof section.kind !== "string" || !DOCUMENT_SECTION_KINDS.has(section.kind)
      || section.kind !== expectedKind
      || !text(section.title, 120)
      || !Array.isArray(section.paragraphs) || section.paragraphs.length > 240
      || section.paragraphs.some((item) => !text(item, 2_000))
      || !Array.isArray(section.rows) || section.rows.length > 400
      || typeof section.truncated !== "boolean"
    ) throw new AgentArtifactPayloadError();
    rows += section.rows.length;
    characters += section.paragraphs.reduce(
      (total, item) => total + characterCount(item),
      0,
    );
    for (const row of section.rows) {
      if (
        !record(row) || !exact(row, DOCUMENT_ROW_KEYS)
        || !Array.isArray(row.cells) || row.cells.length > 32
        || row.cells.some((cell) => (
          typeof cell !== "string" || characterCount(cell) > 2_000
        ))
      ) throw new AgentArtifactPayloadError();
      characters += row.cells.reduce(
        (total, cell) => total + characterCount(cell),
        0,
      );
    }
  }
  if (rows > 400 || characters > 100_000) throw new AgentArtifactPayloadError();
  return value as unknown as AgentDocumentPreview;
}

function parseArtifactHead(
  value: unknown,
  expectedProjectId?: string,
  expectedSessionId?: string,
  expectedArtifactId?: string,
  detail = false,
): AgentArtifact {
  const keys = detail ? DETAIL_KEYS : ARTIFACT_KEYS;
  if (
    !record(value) || !exact(value, keys)
    || value.contract_version !== "agent-artifact.v3"
    || typeof value.artifact_id !== "string" || !ID.test(value.artifact_id)
    || (expectedArtifactId !== undefined && value.artifact_id !== expectedArtifactId)
    || typeof value.project_id !== "string" || !ID.test(value.project_id)
    || (expectedProjectId !== undefined && value.project_id !== expectedProjectId)
    || typeof value.session_id !== "string" || !ID.test(value.session_id)
    || (expectedSessionId !== undefined && value.session_id !== expectedSessionId)
    || !text(value.title, 120)
    || typeof value.kind !== "string" || !KINDS.has(value.kind)
    || typeof value.path !== "string" || value.path.length > 1024 || !SAFE_PATH.test(value.path)
    || !timestamp(value.created_at) || !timestamp(value.updated_at)
    || Date.parse(value.updated_at) < Date.parse(value.created_at)
    || !integer(value.revision, 1, Number.MAX_SAFE_INTEGER)
    || !integer(value.version_count, 1, 2_000)
    || value.revision < value.version_count
    || typeof value.availability !== "string" || !AVAILABILITY.has(value.availability)
    || typeof value.lifecycle_state !== "string" || !LIFECYCLE_STATES.has(value.lifecycle_state)
    || !(value.archived_at === null || timestamp(value.archived_at))
    || !(value.removed_at === null || timestamp(value.removed_at))
    || (value.lifecycle_state === "active" && (value.archived_at !== null || value.removed_at !== null))
    || (value.lifecycle_state === "archived" && (!timestamp(value.archived_at) || value.removed_at !== null))
    || (value.lifecycle_state === "removed" && (!timestamp(value.archived_at) || !timestamp(value.removed_at)))
    || (timestamp(value.archived_at) && Date.parse(value.archived_at) > Date.parse(value.updated_at))
    || (timestamp(value.removed_at) && Date.parse(value.removed_at) > Date.parse(value.updated_at))
    || (timestamp(value.archived_at) && timestamp(value.removed_at)
      && Date.parse(value.removed_at) < Date.parse(value.archived_at))
  ) throw new AgentArtifactPayloadError();
  const latest = parseAgentArtifactVersion(value.latest_version, value.artifact_id);
  if (
    latest.path !== value.path
    || latest.version_number !== value.version_count
    || Date.parse(latest.created_at) > Date.parse(value.updated_at as string)
  ) throw new AgentArtifactPayloadError();
  return { ...value, latest_version: latest } as unknown as AgentArtifact;
}

export function parseAgentArtifact(
  value: unknown,
  expectedProjectId?: string,
  expectedSessionId?: string,
  expectedArtifactId?: string,
): AgentArtifact {
  return parseArtifactHead(value, expectedProjectId, expectedSessionId, expectedArtifactId);
}

export function parseAgentArtifactDetail(
  value: unknown,
  expectedProjectId?: string,
  expectedSessionId?: string,
  expectedArtifactId?: string,
): AgentArtifactDetail {
  const head = parseArtifactHead(
    value,
    expectedProjectId,
    expectedSessionId,
    expectedArtifactId,
    true,
  );
  if (!record(value) || !Array.isArray(value.versions) || value.versions.length !== head.version_count) {
    throw new AgentArtifactPayloadError();
  }
  const versions = value.versions.map((version) => parseAgentArtifactVersion(version, head.artifact_id));
  if (
    versions.some((version, index) => version.version_number !== index + 1)
    || new Set(versions.map((version) => version.version_id)).size !== versions.length
    || versions.some((version, index) => (
      index > 0 && Date.parse(version.created_at) < Date.parse(versions[index - 1].created_at)
    ))
    || !sameVersion(versions[versions.length - 1], head.latest_version)
  ) throw new AgentArtifactPayloadError();
  return { ...head, versions } as AgentArtifactDetail;
}

export function parseAgentArtifactExport(
  value: unknown,
  expectedProjectId: string,
  expectedSessionId: string,
  expectedArtifactId: string,
  expectedRevision: number,
  expectedVersionId: string,
): AgentArtifactExport {
  if (
    !record(value) || !exact(value, EXPORT_KEYS)
    || value.contract_version !== "agent-artifact-export.v1"
    || !timestamp(value.exported_at)
    || value.content_included !== false
    || value.absolute_path_included !== false
    || value.sensitivity !== "sensitive_local_metadata"
    || !record(value.evidence) || !exact(value.evidence, EXPORT_EVIDENCE_KEYS)
    || value.evidence.verification !== "exact_current_workspace_readback"
    || value.evidence.algorithm !== "sha256"
    || typeof value.evidence.sha256 !== "string" || !SHA256.test(value.evidence.sha256)
    || !integer(value.evidence.byte_size, 0, 24 * 1024 * 1024)
    || value.evidence.verified !== true
  ) throw new AgentArtifactPayloadError();
  const artifact = parseAgentArtifactDetail(
    value.artifact,
    expectedProjectId,
    expectedSessionId,
    expectedArtifactId,
  );
  const selected = parseAgentArtifactVersion(value.selected_version, expectedArtifactId);
  const retained = artifact.versions.find((version) => version.version_id === expectedVersionId);
  if (
    artifact.revision !== expectedRevision
    || artifact.lifecycle_state === "removed"
    || selected.version_id !== expectedVersionId
    || retained === undefined
    || !sameVersion(retained, selected)
    || value.evidence.sha256 !== selected.sha256
    || value.evidence.byte_size !== selected.byte_size
  ) throw new AgentArtifactPayloadError();
  return {
    ...value,
    artifact,
    selected_version: selected,
  } as AgentArtifactExport;
}

export function parseAgentArtifactList(
  value: unknown,
  expectedProjectId: string,
  expectedSessionId: string,
  expectedView: AgentArtifactListView = "active",
): AgentArtifactList {
  if (
    !record(value) || !exact(value, LIST_KEYS)
    || value.contract_version !== "agent-artifact.v3"
    || value.project_id !== expectedProjectId
    || value.session_id !== expectedSessionId
    || typeof value.view !== "string" || !LIST_VIEWS.has(value.view)
    || value.view !== expectedView
    || !record(value.counts) || !exact(value.counts, COUNT_KEYS)
    || !Array.isArray(value.artifacts)
    || value.artifacts.length > 200
  ) throw new AgentArtifactPayloadError();
  const counts = value.counts;
  if (
    !integer(counts.active, 0, 500)
    || !integer(counts.archived, 0, 500)
    || !integer(counts.removed, 0, 500)
    || !integer(counts.total, 0, 500)
    || counts.total !== counts.active + counts.archived + counts.removed
  ) throw new AgentArtifactPayloadError();
  const artifacts = value.artifacts.map((artifact) => (
    parseAgentArtifact(artifact, expectedProjectId, expectedSessionId)
  ));
  if (
    new Set(artifacts.map((artifact) => artifact.artifact_id)).size !== artifacts.length
    || new Set(artifacts.map((artifact) => artifact.path)).size !== artifacts.length
    || (expectedView !== "all" && artifacts.some((artifact) => (
      artifact.lifecycle_state !== expectedView
    )))
  ) throw new AgentArtifactPayloadError();
  return {
    contract_version: "agent-artifact.v3",
    project_id: expectedProjectId,
    session_id: expectedSessionId,
    view: expectedView,
    counts: counts as unknown as AgentArtifactLifecycleCounts,
    artifacts,
  };
}

export function parseAgentArtifactPage(
  value: unknown,
  expectedProjectId: string,
  expectedSessionId: string,
  expectedView: AgentArtifactListView,
  expectedLimit: number,
  expectedOffset: number,
  expectedSnapshot?: string,
): AgentArtifactPage {
  if (
    !record(value) || !exact(value, PAGE_KEYS)
    || value.contract_version !== "agent-artifact-page.v1"
    || value.project_id !== expectedProjectId
    || value.session_id !== expectedSessionId
    || value.view !== expectedView
    || typeof value.snapshot !== "string" || !SHA256.test(value.snapshot)
    || (expectedSnapshot !== undefined && value.snapshot !== expectedSnapshot)
    || value.limit !== expectedLimit
    || value.offset !== expectedOffset
    || !integer(value.total, 0, 500)
    || expectedOffset > (value.total as number)
    || typeof value.complete !== "boolean"
    || !record(value.counts) || !exact(value.counts, COUNT_KEYS)
    || !Array.isArray(value.artifacts)
    || value.artifacts.length > 100
  ) throw new AgentArtifactPayloadError();
  const counts = value.counts;
  if (
    !integer(counts.active, 0, 500)
    || !integer(counts.archived, 0, 500)
    || !integer(counts.removed, 0, 500)
    || !integer(counts.total, 0, 500)
    || counts.total !== counts.active + counts.archived + counts.removed
  ) throw new AgentArtifactPayloadError();
  const expectedTotal = (expectedView === "all"
    ? counts.total
    : counts[expectedView]) as number;
  const artifacts = value.artifacts.map((artifact) => (
    parseAgentArtifact(artifact, expectedProjectId, expectedSessionId)
  ));
  const expectedCount = Math.min(expectedLimit, expectedTotal - expectedOffset);
  const expectedNext = expectedOffset + artifacts.length < expectedTotal
    ? expectedOffset + artifacts.length
    : null;
  if (
    value.total !== expectedTotal
    || artifacts.length !== expectedCount
    || value.next_offset !== expectedNext
    || value.complete !== (expectedNext === null)
    || new Set(artifacts.map((artifact) => artifact.artifact_id)).size !== artifacts.length
    || new Set(artifacts.map((artifact) => artifact.path)).size !== artifacts.length
    || (expectedView !== "all" && artifacts.some((artifact) => (
      artifact.lifecycle_state !== expectedView
    )))
  ) throw new AgentArtifactPayloadError();
  return {
    ...value,
    counts: counts as unknown as AgentArtifactLifecycleCounts,
    artifacts,
  } as unknown as AgentArtifactPage;
}
