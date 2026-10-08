import type {
  AgentAttachment,
  AgentAttachmentDocumentPreview,
  AgentAttachmentList,
  AgentMessageAttachment,
} from "./contracts";

const ID = /^[0-9a-f]{32}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const ALIAS = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const PROBE = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const UTC_TIMESTAMP = /(?:Z|\+00:00)$/u;
const MESSAGE_KEYS = new Set([
  "attachment_id", "byte_size", "channels", "context_cost_source",
  "context_tokens", "contract_version", "display_name", "document_format",
  "duration_ms", "height", "kind", "media_type", "omitted_features",
  "projected_characters", "projection_truncated", "routing", "sample_rate_hz",
  "sha256", "width",
]);
const ATTACHMENT_KEYS = new Set([
  ...MESSAGE_KEYS,
  "attached_event_seq", "capability_probe_version", "created_at", "expires_at",
  "model_alias", "retention", "session_id", "source", "state",
]);
const DOCUMENT_PREVIEW_KEYS = new Set([
  "attachment_id", "contract_version", "document_format", "media_type",
  "omitted_features", "preview_truncated", "projected_characters",
  "projection_truncated", "session_id", "sha256", "text",
]);
const DOCUMENT_MEDIA_BY_FORMAT = {
  plain_text: "text/plain",
  markdown: "text/markdown",
  json: "application/json",
  csv: "text/csv",
  tsv: "text/tab-separated-values",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  odt: "application/vnd.oasis.opendocument.text",
} as const;
const PLAIN_DOCUMENT_FORMATS = new Set(["plain_text", "markdown", "json", "csv", "tsv"]);
const OMITTED_FEATURES = new Set([
  "comments", "embedded_objects", "external_links", "macros", "media", "notes",
]);

export class AgentAttachmentPayloadError extends Error {
  constructor() {
    super("Local Agent attachment payload was invalid");
    this.name = "AgentAttachmentPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value)
    && value >= minimum && value <= maximum;
}

function nullableInteger(value: unknown, minimum: number, maximum: number): boolean {
  return value === null || integer(value, minimum, maximum);
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && UTC_TIMESTAMP.test(value)
    && Number.isFinite(Date.parse(value));
}

function displayName(value: unknown): value is string {
  return typeof value === "string"
    && Array.from(value).length >= 1
    && Array.from(value).length <= 120
    && !/[\\/\u0000-\u001f\u007f]/u.test(value)
    && value.trim() === value;
}

function documentFormat(value: unknown): value is keyof typeof DOCUMENT_MEDIA_BY_FORMAT {
  return typeof value === "string"
    && Object.prototype.hasOwnProperty.call(DOCUMENT_MEDIA_BY_FORMAT, value);
}

function omittedFeatures(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length <= OMITTED_FEATURES.size
    && value.every((item) => typeof item === "string" && OMITTED_FEATURES.has(item))
    && new Set(value).size === value.length;
}

function unicodeLength(value: string): number {
  return Array.from(value).length;
}

export function parseAgentMessageAttachment(value: unknown): AgentMessageAttachment {
  if (
    !record(value) || !exact(value, MESSAGE_KEYS)
    || value.contract_version !== "agent-attachment.v2"
    || typeof value.attachment_id !== "string" || !ID.test(value.attachment_id)
    || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)
    || !displayName(value.display_name)
    || value.context_tokens !== null
    || value.context_cost_source !== "runtime_unreported"
    || !integer(value.byte_size, 1, 12 * 1024 * 1024)
    || !nullableInteger(value.width, 1, 8192)
    || !nullableInteger(value.height, 1, 8192)
    || !nullableInteger(value.duration_ms, 1, 300_000)
    || !nullableInteger(value.sample_rate_hz, 8_000, 48_000)
    || !nullableInteger(value.channels, 1, 2)
    || !nullableInteger(value.projected_characters, 1, 100_000)
    || !(value.projection_truncated === null || typeof value.projection_truncated === "boolean")
    || !omittedFeatures(value.omitted_features)
  ) throw new AgentAttachmentPayloadError();
  if (value.kind === "image") {
    if (
      !["image/png", "image/jpeg"].includes(String(value.media_type))
      || typeof value.width !== "number" || typeof value.height !== "number"
      || value.width * value.height > 33_554_432
      || value.duration_ms !== null || value.sample_rate_hz !== null || value.channels !== null
      || value.routing !== "native_multimodal" || value.document_format !== null
      || value.projected_characters !== null || value.projection_truncated !== null
      || value.omitted_features.length !== 0
      || (value.byte_size as number) > 8 * 1024 * 1024
    ) throw new AgentAttachmentPayloadError();
  } else if (value.kind === "audio") {
    if (
      value.media_type !== "audio/wav"
      || value.width !== null || value.height !== null
      || typeof value.duration_ms !== "number"
      || typeof value.sample_rate_hz !== "number"
      || typeof value.channels !== "number"
      || value.routing !== "native_multimodal" || value.document_format !== null
      || value.projected_characters !== null || value.projection_truncated !== null
      || value.omitted_features.length !== 0
    ) throw new AgentAttachmentPayloadError();
  } else if (value.kind === "document") {
    if (
      value.width !== null || value.height !== null || value.duration_ms !== null
      || value.sample_rate_hz !== null || value.channels !== null
      || value.routing !== "local_text_projection"
      || !documentFormat(value.document_format)
      || DOCUMENT_MEDIA_BY_FORMAT[value.document_format] !== value.media_type
      || typeof value.projected_characters !== "number"
      || typeof value.projection_truncated !== "boolean"
      || (PLAIN_DOCUMENT_FORMATS.has(value.document_format) && value.omitted_features.length !== 0)
    ) throw new AgentAttachmentPayloadError();
  } else {
    throw new AgentAttachmentPayloadError();
  }
  return value as unknown as AgentMessageAttachment;
}

export function parseAgentAttachment(
  value: unknown,
  expectedSessionId?: string,
  expectedAttachmentId?: string,
): AgentAttachment {
  if (
    !record(value) || !exact(value, ATTACHMENT_KEYS)
    || typeof value.session_id !== "string" || !ID.test(value.session_id)
    || (expectedSessionId !== undefined && value.session_id !== expectedSessionId)
    || (expectedAttachmentId !== undefined && value.attachment_id !== expectedAttachmentId)
    || typeof value.model_alias !== "string" || !ALIAS.test(value.model_alias)
    || typeof value.capability_probe_version !== "string" || !PROBE.test(value.capability_probe_version)
    || !timestamp(value.created_at)
    || !(value.expires_at === null || timestamp(value.expires_at))
    || (
      value.source !== "file"
      && value.source !== "microphone"
      && value.source !== "external_agent"
    )
    || (value.retention !== "memory_only" && value.retention !== "local_history")
    || (value.state !== "staged" && value.state !== "attached")
    || !nullableInteger(value.attached_event_seq, 1, Number.MAX_SAFE_INTEGER)
  ) throw new AgentAttachmentPayloadError();
  const metadata = parseAgentMessageAttachment(
    Object.fromEntries([...MESSAGE_KEYS].map((key) => [key, value[key]])),
  );
  if (
    (value.state === "staged" && (value.expires_at === null || value.attached_event_seq !== null))
    || (value.state === "attached" && value.attached_event_seq === null)
    || (value.state === "attached" && value.retention === "local_history" && value.expires_at !== null)
  ) throw new AgentAttachmentPayloadError();
  return { ...value, ...metadata } as unknown as AgentAttachment;
}

export function parseAgentAttachmentList(
  value: unknown,
  expectedSessionId: string,
): AgentAttachmentList {
  if (
    !record(value)
    || Object.keys(value).sort().join(",") !== "attachments,contract_version,session_id"
    || value.contract_version !== "agent-attachment.v2"
    || value.session_id !== expectedSessionId
    || !Array.isArray(value.attachments)
    || value.attachments.length > 16
  ) throw new AgentAttachmentPayloadError();
  const attachments = value.attachments.map((attachment) => (
    parseAgentAttachment(attachment, expectedSessionId)
  ));
  if (
    attachments.some((attachment) => attachment.state !== "staged")
    || new Set(attachments.map((attachment) => attachment.attachment_id)).size !== attachments.length
  ) throw new AgentAttachmentPayloadError();
  return {
    contract_version: "agent-attachment.v2",
    session_id: expectedSessionId,
    attachments,
  };
}

export function parseAgentAttachmentDocumentPreview(
  value: unknown,
  expectedSessionId: string,
  expectedAttachmentId: string,
): AgentAttachmentDocumentPreview {
  if (
    !record(value) || !exact(value, DOCUMENT_PREVIEW_KEYS)
    || value.contract_version !== "agent-attachment-document-preview.v1"
    || value.session_id !== expectedSessionId || !ID.test(expectedSessionId)
    || value.attachment_id !== expectedAttachmentId || !ID.test(expectedAttachmentId)
    || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)
    || !documentFormat(value.document_format)
    || DOCUMENT_MEDIA_BY_FORMAT[value.document_format] !== value.media_type
    || typeof value.text !== "string"
    || unicodeLength(value.text) < 1 || unicodeLength(value.text) > 12_000
    || !integer(value.projected_characters, 1, 100_000)
    || unicodeLength(value.text) > value.projected_characters
    || typeof value.projection_truncated !== "boolean"
    || typeof value.preview_truncated !== "boolean"
    || value.preview_truncated !== (value.projected_characters > unicodeLength(value.text))
    || !omittedFeatures(value.omitted_features)
    || (PLAIN_DOCUMENT_FORMATS.has(value.document_format) && value.omitted_features.length !== 0)
  ) throw new AgentAttachmentPayloadError();
  return value as unknown as AgentAttachmentDocumentPreview;
}
