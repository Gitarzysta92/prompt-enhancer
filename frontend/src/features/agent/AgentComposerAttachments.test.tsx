import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentAttachment, PromptEnhancerTransport, RuntimeCapabilities } from "../../shared/api/contracts";
import { AgentComposerAttachments } from "./AgentComposerAttachments";

const SESSION = "a".repeat(32);
const ATTACHMENT = "b".repeat(32);
const originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
const originalAudioContext = Object.getOwnPropertyDescriptor(window, "AudioContext");

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

function installRecorderBoundary(streamPromise?: Promise<{ getTracks(): Array<{ stop(): void }> }>) {
  const trackStop = vi.fn();
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const processor = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onaudioprocess: null as ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null,
  };
  const gain = { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } };
  const close = vi.fn(async () => undefined);
  const context = {
    sampleRate: 32_000,
    state: "running",
    destination: {},
    createMediaStreamSource: vi.fn(() => source),
    createScriptProcessor: vi.fn(() => processor),
    createGain: vi.fn(() => gain),
    close,
    resume: vi.fn(async () => undefined),
  };
  const stream = { getTracks: () => [{ stop: trackStop }] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(() => streamPromise ?? Promise.resolve(stream)) },
  });
  Object.defineProperty(window, "AudioContext", {
    configurable: true,
    value: vi.fn(function SyntheticAudioContext() { return context; }),
  });
  return { close, processor, stream, trackStop };
}

function capabilities(overrides: Partial<RuntimeCapabilities> = {}): RuntimeCapabilities {
  return {
    probe_version: "local-runtime-multimodal-probe.v2",
    state: "verified",
    text: true,
    tools: true,
    structured_output: false,
    vision: true,
    audio: false,
    recording: false,
    error_code: null,
    ...overrides,
  };
}

function attachment(overrides: Partial<AgentAttachment> = {}): AgentAttachment {
  return {
    contract_version: "agent-attachment.v2",
    attachment_id: ATTACHMENT,
    session_id: SESSION,
    display_name: "example.png",
    kind: "image",
    media_type: "image/png",
    byte_size: 68,
    sha256: "c".repeat(64),
    width: 1,
    height: 1,
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

function documentAttachment(overrides: Partial<AgentAttachment> = {}): AgentAttachment {
  return attachment({
    display_name: "example-notes.md",
    kind: "document",
    media_type: "text/markdown",
    byte_size: 42,
    width: null,
    height: null,
    duration_ms: null,
    sample_rate_hz: null,
    channels: null,
    routing: "local_text_projection",
    document_format: "markdown",
    projected_characters: 31,
    projection_truncated: false,
    omitted_features: [],
    ...overrides,
  });
}

function Harness({
  compact = false,
  disabled = false,
  modelAlias = "example-model",
  onBusyChange,
  runtime = capabilities(),
  runtimeKey = "runtime-a",
  sessionId = SESSION,
  transport,
}: {
  compact?: boolean;
  disabled?: boolean;
  modelAlias?: string | null;
  onBusyChange?: (busy: boolean) => void;
  runtime?: RuntimeCapabilities | null;
  runtimeKey?: string;
  sessionId?: string;
  transport: Parameters<typeof AgentComposerAttachments>[0]["transport"];
}) {
  const [attachments, setAttachments] = useState<AgentAttachment[]>([]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const mismatched = modelAlias !== null && attachments.some((item) => item.model_alias !== modelAlias);
  return (
    <>
      <AgentComposerAttachments
        attachments={attachments}
        capabilities={runtime}
        compact={compact}
        disabled={disabled}
        modelAlias={modelAlias}
        onAttachmentsChange={setAttachments}
        onBusyChange={(value) => {
          setAttachmentBusy(value);
          onBusyChange?.(value);
        }}
        runtimeKey={runtimeKey}
        sessionId={sessionId}
        transport={transport}
      />
      <output data-testid="attachment-count">{attachments.length}</output>
      <button disabled={attachmentBusy || mismatched} type="button">Synthetic send</button>
    </>
  );
}

async function openMediaPicker() {
  const trigger = await screen.findByRole("button", { name: "Attach" });
  await waitFor(() => expect(trigger).toBeEnabled());
  if (trigger.getAttribute("aria-expanded") !== "true") fireEvent.click(trigger);
  return trigger;
}

beforeEach(() => {
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:synthetic-preview") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

afterEach(() => {
  if (originalCreateObjectUrl) Object.defineProperty(URL, "createObjectURL", originalCreateObjectUrl);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevokeObjectUrl) Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectUrl);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
  if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  else Reflect.deleteProperty(navigator, "mediaDevices");
  if (originalAudioContext) Object.defineProperty(window, "AudioContext", originalAudioContext);
  else Reflect.deleteProperty(window, "AudioContext");
});

describe("AgentComposerAttachments", () => {
  it("keeps primary media controls compact while capability-gating the microphone", async () => {
    installRecorderBoundary();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness
      compact
      runtime={capabilities({ audio: true, recording: true })}
      transport={transport}
    />);

    const attachmentRegion = screen.getByLabelText("Message attachments");
    expect(attachmentRegion).toHaveClass("agent-attachments--compact");
    const attach = await screen.findByRole("button", { name: "Attach" });
    await waitFor(() => expect(attach).toBeEnabled());
    expect(screen.getByRole("button", { name: "Record audio" })).toBeEnabled();
    expect(screen.queryByRole("group", { name: "Attachment sources" })).not.toBeInTheDocument();

    fireEvent.click(attach);
    expect(screen.getByRole("group", { name: "Attachment sources" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh staged" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add image" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add audio" })).toBeEnabled();
  });

  it("keeps an open source menu stable while a new runtime identity re-gates its choices", async () => {
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    const rendered = render(<Harness compact runtimeKey="runtime-a" transport={transport} />);
    const attach = await screen.findByRole("button", { name: "Attach" });
    await waitFor(() => expect(attach).toBeEnabled());
    fireEvent.click(attach);
    expect(screen.getByRole("group", { name: "Attachment sources" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add image" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add audio" })).toBeDisabled();

    rendered.rerender(<Harness
      compact
      runtime={capabilities({ audio: true, recording: false, vision: false })}
      runtimeKey="runtime-b"
      transport={transport}
    />);

    expect(screen.getByRole("group", { name: "Attachment sources" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add image" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add audio" })).toBeEnabled();
  });

  it("keeps media locked until the exact live runtime verifies it", async () => {
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness runtime={null} transport={transport} />);

    expect(screen.queryByRole("button", { name: "Add image" })).not.toBeInTheDocument();
    await openMediaPicker();
    expect(screen.getByRole("button", { name: "Add image" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add audio" })).toBeDisabled();
    expect(screen.getByText(/locked until the served model/u)).toBeVisible();
    expect(transport.stageAgentAttachment).not.toHaveBeenCalled();
  });

  it("keeps secondary media choices compact and restores trigger focus on Escape", async () => {
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness transport={transport} />);

    const trigger = await openMediaPicker();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: "Attachment sources" })).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("group", { name: "Attachment sources" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("allows a staged attachment to be removed while model media input is unavailable", async () => {
    const deleteAgentAttachment = vi.fn(async () => undefined);
    const transport = {
      listAgentAttachments: vi.fn(async () => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: SESSION,
        attachments: [attachment()],
      })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment,
    };
    render(<Harness runtime={null} transport={transport} />);

    expect(await screen.findByText("example.png")).toBeVisible();
    await openMediaPicker();
    expect(screen.getByRole("button", { name: "Add image" })).toBeDisabled();
    const remove = screen.getByRole("button", { name: "Remove example.png" });
    expect(remove).toBeEnabled();
    fireEvent.click(remove);
    await waitFor(() => expect(deleteAgentAttachment).toHaveBeenCalledWith(
      SESSION,
      ATTACHMENT,
      expect.any(AbortSignal),
    ));
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("0");
  });

  it("serializes staged-media refresh before file selection can mutate the composer", async () => {
    const listing = deferred<{
      contract_version: "agent-attachment.v2";
      session_id: string;
      attachments: AgentAttachment[];
    }>();
    const transport = {
      listAgentAttachments: vi.fn(() => listing.promise),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness transport={transport} />);

    expect(await screen.findByText("Refreshing staged attachments…")).toBeVisible();
    expect(screen.getByRole("button", { name: "Attach" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add image" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Choose images")).toBeDisabled();
    await act(async () => {
      listing.resolve({ contract_version: "agent-attachment.v2", session_id: SESSION, attachments: [] });
      await listing.promise;
    });

    await openMediaPicker();
    expect(screen.getByRole("button", { name: "Add image" })).toBeEnabled();
    expect(screen.getByLabelText("Choose images")).toBeEnabled();
    expect(transport.stageAgentAttachment).not.toHaveBeenCalled();
  });

  it("enables verified WAV upload while keeping recording gated by this window's microphone boundary", async () => {
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness runtime={capabilities({ vision: false, audio: true, recording: true })} transport={transport} />);

    await openMediaPicker();
    expect(screen.getByRole("button", { name: "Add audio" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add image" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Record audio" })).toBeDisabled();
    expect(screen.getByText(/Audio input is experimental/u)).toBeVisible();
  });

  it("uploads a verified image, previews it, and removes only the staged identity", async () => {
    const admitted = attachment();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment: vi.fn(async () => admitted),
      deleteAgentAttachment: vi.fn(async () => undefined),
    };
    render(<Harness transport={transport} />);
    await waitFor(() => expect(transport.listAgentAttachments).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal)));

    const file = new File([new Uint8Array([1, 2, 3])], "example.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Choose images"), { target: { files: [file] } });

    expect(await screen.findByText("example.png")).toBeVisible();
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("1");
    expect(transport.stageAgentAttachment).toHaveBeenCalledWith(
      SESSION,
      {
        blob: file,
        displayName: "example.png",
        source: "file",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("img", { name: "Preview example.png" })).toHaveAttribute("src", "blob:synthetic-preview");

    fireEvent.click(screen.getByRole("button", { name: "Remove example.png" }));
    await waitFor(() => expect(transport.deleteAgentAttachment).toHaveBeenCalledWith(
      SESSION,
      ATTACHMENT,
      expect.any(AbortSignal),
    ));
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("0");
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-preview"));
  });

  it("recovers staged metadata and private preview content after remount", async () => {
    const admitted = attachment();
    const preview = new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" });
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [admitted] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentContent: vi.fn(async () => ({ blob: preview, contentType: "image/png" as const, filename: "agent-attachment-bbbbbbbb.png", byteSize: 3 })),
    };
    render(<Harness transport={transport} />);

    expect(await screen.findByText("example.png")).toBeVisible();
    await waitFor(() => expect(transport.getAgentAttachmentContent).toHaveBeenCalledWith(SESSION, ATTACHMENT, expect.any(AbortSignal)));
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("1");
    expect(screen.getByRole("img", { name: "Preview example.png" })).toHaveAttribute("src", "blob:synthetic-preview");
  });

  it("normalizes a document MIME type, stages it, and renders only the server projection", async () => {
    const admitted = documentAttachment();
    const getAgentAttachmentDocumentPreview = vi.fn(async () => ({
      contract_version: "agent-attachment-document-preview.v1" as const,
      session_id: SESSION,
      attachment_id: ATTACHMENT,
      sha256: admitted.sha256,
      media_type: "text/markdown" as const,
      document_format: "markdown" as const,
      text: "# Synthetic notes\n\nLocal projection.",
      projected_characters: 31,
      projection_truncated: false,
      preview_truncated: false,
      omitted_features: [],
    }));
    const stageAgentAttachment = vi.fn<PromptEnhancerTransport["stageAgentAttachment"]>(
      async () => admitted,
    );
    const transport = {
      listAgentAttachments: vi.fn(async () => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: SESSION,
        attachments: [],
      })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentDocumentPreview,
    };
    render(<Harness runtime={capabilities({ vision: false })} transport={transport} />);
    await openMediaPicker();
    expect(screen.getByRole("button", { name: "Add document" })).toBeEnabled();

    const file = new File(["# Synthetic notes"], "example-notes.md", { type: "" });
    fireEvent.change(screen.getByLabelText("Choose documents"), { target: { files: [file] } });

    expect(await screen.findByText("example-notes.md")).toBeVisible();
    await waitFor(() => expect(stageAgentAttachment).toHaveBeenCalledOnce());
    const upload = stageAgentAttachment.mock.calls[0]?.[1];
    expect(upload?.blob).toBeInstanceOf(Blob);
    expect(upload?.blob.type).toBe("text/markdown");
    expect(upload?.displayName).toBe("example-notes.md");
    expect(getAgentAttachmentDocumentPreview).toHaveBeenCalledWith(
      SESSION,
      ATTACHMENT,
      expect.any(AbortSignal),
    );
    expect(screen.getByText("Extracted preview")).toBeVisible();
    expect(screen.getByText(/Local projection/u)).toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("recovers document projection after remount and refuses PDF before upload", async () => {
    const admitted = documentAttachment();
    const getAgentAttachmentContent = vi.fn();
    const getAgentAttachmentDocumentPreview = vi.fn(async () => ({
      contract_version: "agent-attachment-document-preview.v1" as const,
      session_id: SESSION,
      attachment_id: ATTACHMENT,
      sha256: admitted.sha256,
      media_type: "text/markdown" as const,
      document_format: "markdown" as const,
      text: "Synthetic restart-safe projection",
      projected_characters: 33,
      projection_truncated: false,
      preview_truncated: false,
      omitted_features: [],
    }));
    const stageAgentAttachment = vi.fn();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: SESSION,
        attachments: [admitted],
      })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
      getAgentAttachmentContent,
      getAgentAttachmentDocumentPreview,
    };
    render(<Harness transport={transport} />);

    expect(await screen.findByText(/restart-safe projection/u)).toBeInTheDocument();
    expect(getAgentAttachmentContent).not.toHaveBeenCalled();
    const pdf = new File(["%PDF-1.7 synthetic"], "synthetic.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(screen.getByLabelText("Choose documents"), { target: { files: [pdf] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("PDF input is intentionally unavailable");
    expect(stageAgentAttachment).not.toHaveBeenCalled();
  });

  it("refreshes and labels media staged by a connected external agent", async () => {
    const external = attachment({ source: "external_agent", display_name: "from-agent.png" });
    const listAgentAttachments = vi.fn()
      .mockResolvedValueOnce({ contract_version: "agent-attachment.v2", session_id: SESSION, attachments: [] })
      .mockResolvedValueOnce({ contract_version: "agent-attachment.v2", session_id: SESSION, attachments: [external] });
    const transport = {
      listAgentAttachments,
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness transport={transport} />);

    await waitFor(() => expect(listAgentAttachments).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh staged" }));

    expect(await screen.findByText("from-agent.png")).toBeVisible();
    expect(screen.getByText(/via external agent/u)).toBeVisible();
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("1");
    expect(listAgentAttachments).toHaveBeenCalledTimes(2);
  });

  it("keeps known staged identities when an explicit refresh fails", async () => {
    const admitted = attachment();
    const listAgentAttachments = vi.fn()
      .mockResolvedValueOnce({ contract_version: "agent-attachment.v2", session_id: SESSION, attachments: [admitted] })
      .mockRejectedValueOnce(new Error("synthetic refresh failure"));
    const transport = {
      listAgentAttachments,
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness transport={transport} />);
    expect(await screen.findByText("example.png")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Refresh staged" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Known attachment identities were kept");
    expect(screen.getByText("example.png")).toBeVisible();
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("1");
  });

  it("blocks parent send while recording and stages the exact local WAV only after Stop", async () => {
    const boundary = installRecorderBoundary();
    const admitted = attachment({
      kind: "audio",
      media_type: "audio/wav",
      display_name: "synthetic-recording.wav",
      width: null,
      height: null,
      duration_ms: 20,
      sample_rate_hz: 16_000,
      channels: 1,
      source: "microphone",
    });
    const stageAgentAttachment = vi.fn(async () => admitted);
    const busyChanges = vi.fn();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness
      onBusyChange={busyChanges}
      runtime={capabilities({ audio: true, recording: true })}
      transport={transport}
    />);

    await openMediaPicker();
    const record = screen.getByRole("button", { name: "Record audio" });
    expect(record).toBeEnabled();
    fireEvent.click(record);
    expect(await screen.findByText(/Recording locally/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Synthetic send" })).toBeDisabled();
    boundary.processor.onaudioprocess?.({
      inputBuffer: { getChannelData: () => new Float32Array([0, 0.25, 0.5, 0.75]) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(stageAgentAttachment).toHaveBeenCalledWith(
      SESSION,
      expect.objectContaining({
        blob: expect.any(Blob),
        displayName: expect.stringMatching(/^recording-.*\.wav$/u),
        source: "microphone",
      }),
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("synthetic-recording.wav")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Synthetic send" })).toBeEnabled());
    expect(busyChanges).toHaveBeenCalledWith(true);
    expect(busyChanges).toHaveBeenLastCalledWith(false);
    expect(boundary.trackStop).toHaveBeenCalledOnce();
  });

  it("cancels a pending microphone grant when the model runtime changes", async () => {
    const pendingStream = deferred<{ getTracks(): Array<{ stop(): void }> }>();
    const boundary = installRecorderBoundary(pendingStream.promise);
    const stageAgentAttachment = vi.fn();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
    };
    const rendered = render(<Harness
      runtime={capabilities({ audio: true, recording: true })}
      runtimeKey="runtime-a"
      transport={transport}
    />);
    await openMediaPicker();
    fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
    expect(await screen.findByText(/Waiting for this window's microphone permission/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Starting microphone…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Synthetic send" })).toBeDisabled();

    rendered.rerender(<Harness
      runtime={capabilities({ audio: true, recording: true })}
      runtimeKey="runtime-b"
      transport={transport}
    />);
    expect(await screen.findByRole("alert")).toHaveTextContent("active model or verified input capability changed");
    await act(async () => {
      pendingStream.resolve(boundary.stream);
      await pendingStream.promise;
      await Promise.resolve();
    });

    await waitFor(() => expect(boundary.trackStop).toHaveBeenCalledOnce());
    expect(stageAgentAttachment).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Synthetic send" })).toBeEnabled();
  });

  it("releases a microphone grant that resolves after the composer unmounts", async () => {
    const pendingStream = deferred<{ getTracks(): Array<{ stop(): void }> }>();
    const boundary = installRecorderBoundary(pendingStream.promise);
    const stageAgentAttachment = vi.fn();
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
    };
    const rendered = render(<Harness
      runtime={capabilities({ audio: true, recording: true })}
      transport={transport}
    />);
    await openMediaPicker();
    fireEvent.click(screen.getByRole("button", { name: "Record audio" }));
    await screen.findByText(/Waiting for this window's microphone permission/u);
    rendered.unmount();

    await act(async () => {
      pendingStream.resolve(boundary.stream);
      await pendingStream.promise;
      await Promise.resolve();
    });

    await waitFor(() => expect(boundary.trackStop).toHaveBeenCalledOnce());
    expect(stageAgentAttachment).not.toHaveBeenCalled();
  });

  it("aborts and ignores a late stage result after the runtime scope changes", async () => {
    const pending = deferred<AgentAttachment>();
    const stageAgentAttachment = vi.fn<PromptEnhancerTransport["stageAgentAttachment"]>(() => pending.promise);
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [] })),
      stageAgentAttachment,
      deleteAgentAttachment: vi.fn(),
    };
    const rendered = render(<Harness runtimeKey="runtime-a" transport={transport} />);
    const file = new File([new Uint8Array([1, 2, 3])], "late.png", { type: "image/png" });
    fireEvent.change(await screen.findByLabelText("Choose images"), { target: { files: [file] } });
    await waitFor(() => expect(stageAgentAttachment).toHaveBeenCalledOnce());
    const signal = stageAgentAttachment.mock.calls[0]?.[2];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    rendered.rerender(<Harness runtimeKey="runtime-b" transport={transport} />);
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve(attachment({ display_name: "late.png" }));
      await pending.promise;
      await Promise.resolve();
    });

    expect(screen.queryByText("late.png")).not.toBeInTheDocument();
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("0");
  });

  it("aborts and ignores a late removal after the runtime scope changes", async () => {
    const pending = deferred<void>();
    const staged = attachment();
    const deleteAgentAttachment = vi.fn<PromptEnhancerTransport["deleteAgentAttachment"]>(() => pending.promise);
    const transport = {
      listAgentAttachments: vi.fn(async () => ({ contract_version: "agent-attachment.v2" as const, session_id: SESSION, attachments: [staged] })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment,
    };
    const rendered = render(<Harness runtimeKey="runtime-a" transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove example.png" }));
    await waitFor(() => expect(deleteAgentAttachment).toHaveBeenCalledOnce());
    const signal = deleteAgentAttachment.mock.calls[0]?.[2];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    rendered.rerender(<Harness runtimeKey="runtime-b" transport={transport} />);
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve();
      await pending.promise;
      await Promise.resolve();
    });

    expect(screen.getByText("example.png")).toBeVisible();
    expect(screen.getByTestId("attachment-count")).toHaveTextContent("1");
  });

  it("marks a retained attachment from another model and blocks sending until it is removed", async () => {
    const transport = {
      listAgentAttachments: vi.fn(async () => ({
        contract_version: "agent-attachment.v2" as const,
        session_id: SESSION,
        attachments: [attachment({ model_alias: "previous-model" })],
      })),
      stageAgentAttachment: vi.fn(),
      deleteAgentAttachment: vi.fn(),
    };
    render(<Harness modelAlias="current-model" transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("belongs to a different model");
    expect(screen.getByText(/different model · context cost unknown/u)).toBeVisible();
    expect(screen.getByRole("button", { name: "Synthetic send" })).toBeDisabled();
  });
});
