import { describe, expect, it } from "vitest";

import {
  AgentAttachmentPayloadError,
  parseAgentAttachment,
  parseAgentAttachmentDocumentPreview,
  parseAgentAttachmentList,
  parseAgentMessageAttachment,
} from "./agentAttachmentContract";

const SESSION = "a".repeat(32);
const ATTACHMENT = "b".repeat(32);

function imageMetadata(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "agent-attachment.v2",
    attachment_id: ATTACHMENT,
    display_name: "example-image.png",
    kind: "image",
    media_type: "image/png",
    byte_size: 128,
    sha256: "c".repeat(64),
    width: 16,
    height: 12,
    duration_ms: null,
    sample_rate_hz: null,
    channels: null,
    routing: "native_multimodal",
    document_format: null,
    projected_characters: null,
    projection_truncated: null,
    omitted_features: [],
    context_tokens: null,
    context_cost_source: "runtime_unreported",
    ...overrides,
  };
}

function staged(overrides: Record<string, unknown> = {}) {
  return {
    ...imageMetadata(),
    session_id: SESSION,
    model_alias: "example-model",
    capability_probe_version: "local-runtime-multimodal-probe.v2",
    source: "file",
    retention: "memory_only",
    state: "staged",
    created_at: "2040-01-01T10:00:00Z",
    expires_at: "2040-01-01T11:00:00Z",
    attached_event_seq: null,
    ...overrides,
  };
}

describe("Agent attachment contracts", () => {
  it("accepts exact payload-free image and PCM audio metadata", () => {
    expect(parseAgentMessageAttachment(imageMetadata())).toMatchObject({
      attachment_id: ATTACHMENT,
      kind: "image",
      width: 16,
      context_tokens: null,
    });
    expect(parseAgentMessageAttachment(imageMetadata({
      display_name: "example-audio.wav",
      kind: "audio",
      media_type: "audio/wav",
      byte_size: 32044,
      width: null,
      height: null,
      duration_ms: 1000,
      sample_rate_hz: 16000,
      channels: 1,
    }))).toMatchObject({ kind: "audio", duration_ms: 1000, sample_rate_hz: 16000 });
  });

  it("accepts only staged attachments for a matching session list", () => {
    expect(parseAgentAttachment(staged(), SESSION, ATTACHMENT).state).toBe("staged");
    expect(parseAgentAttachmentList({
      contract_version: "agent-attachment.v2",
      session_id: SESSION,
      attachments: [staged()],
    }, SESSION).attachments).toHaveLength(1);
    expect(parseAgentAttachment(staged({ source: "external_agent" }), SESSION).source)
      .toBe("external_agent");
  });

  it("accepts coherent document metadata and a bounded matching preview", () => {
    const document = imageMetadata({
      display_name: "example-notes.md",
      kind: "document",
      media_type: "text/markdown",
      byte_size: 64,
      width: null,
      height: null,
      routing: "local_text_projection",
      document_format: "markdown",
      projected_characters: 24,
      projection_truncated: false,
    });
    expect(parseAgentMessageAttachment(document)).toMatchObject({
      kind: "document",
      document_format: "markdown",
    });
    expect(parseAgentAttachmentDocumentPreview({
      contract_version: "agent-attachment-document-preview.v1",
      session_id: SESSION,
      attachment_id: ATTACHMENT,
      sha256: "c".repeat(64),
      media_type: "text/markdown",
      document_format: "markdown",
      text: "Synthetic preview 😀",
      projected_characters: 19,
      projection_truncated: false,
      preview_truncated: false,
      omitted_features: [],
    }, SESSION, ATTACHMENT).document_format).toBe("markdown");
  });

  it.each([
    imageMetadata({
      kind: "document", media_type: "text/markdown", width: null, height: null,
      routing: "native_multimodal", document_format: "markdown",
      projected_characters: 10, projection_truncated: false,
    }),
    imageMetadata({
      kind: "document", media_type: "text/plain", width: null, height: null,
      routing: "local_text_projection", document_format: "markdown",
      projected_characters: 10, projection_truncated: false,
    }),
    imageMetadata({ omitted_features: ["media"] }),
  ])("rejects contradictory v2 routing metadata", (payload) => {
    expect(() => parseAgentMessageAttachment(payload)).toThrow(AgentAttachmentPayloadError);
  });

  it.each([
    imageMetadata({ display_name: "..\\private.png" }),
    imageMetadata({ media_type: "audio/wav" }),
    imageMetadata({ byte_size: 9 * 1024 * 1024 }),
    imageMetadata({ duration_ms: 1 }),
    imageMetadata({ width: 8192, height: 8192 }),
    imageMetadata({ payload: "forbidden" }),
  ])("rejects malformed or payload-bearing message metadata", (payload) => {
    expect(() => parseAgentMessageAttachment(payload)).toThrow(AgentAttachmentPayloadError);
  });

  it("rejects contradictory lifecycle state and duplicate staged identities", () => {
    expect(() => parseAgentAttachment(staged({ state: "attached" }))).toThrow(AgentAttachmentPayloadError);
    expect(() => parseAgentAttachment(staged({ expires_at: null }))).toThrow(AgentAttachmentPayloadError);
    expect(() => parseAgentAttachmentList({
      contract_version: "agent-attachment.v2",
      session_id: SESSION,
      attachments: [staged(), staged()],
    }, SESSION)).toThrow(AgentAttachmentPayloadError);
  });
});
