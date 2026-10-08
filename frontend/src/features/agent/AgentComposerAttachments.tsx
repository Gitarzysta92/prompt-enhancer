import { useEffect, useId, useRef, useState } from "react";

import type {
  AgentAttachment,
  AgentAttachmentDocumentPreview,
  PromptEnhancerTransport,
  RuntimeCapabilities,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Icon } from "../../shared/ui/Icon";
import {
  microphoneCaptureAvailable,
  startPcmWavRecorder,
  type PcmWavRecorder,
} from "./pcmWavRecorder";
import "./AgentComposerAttachments.css";

type AttachmentTransport = Partial<Pick<
  PromptEnhancerTransport,
  "listAgentAttachments" | "stageAgentAttachment" | "deleteAgentAttachment"
  | "getAgentAttachmentContent" | "getAgentAttachmentDocumentPreview"
>>;

type Props = {
  attachments: AgentAttachment[];
  capabilities: RuntimeCapabilities | null;
  compact?: boolean;
  disabled: boolean;
  modelAlias: string | null;
  onAttachmentsChange: (attachments: AgentAttachment[]) => void;
  onBusyChange: (busy: boolean) => void;
  runtimeKey: string;
  sessionId: string;
  transport: AttachmentTransport;
};

type MutationRequest = {
  controller: AbortController;
  generation: number;
};

type RecorderStartRequest = {
  generation: number;
};

type ListRequest = {
  controller: AbortController;
  generation: number;
};

const MAX_ATTACHMENTS = 4;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_AUDIO_BYTES = 12 * 1024 * 1024;
const MAX_DOCUMENT_BYTES = 12 * 1024 * 1024;
const MAX_TEXT_DOCUMENT_BYTES = 2 * 1024 * 1024;
const TEXT_DOCUMENT_SUFFIXES = new Set([
  ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".htm", ".html",
  ".java", ".js", ".jsx", ".kt", ".log", ".lua", ".php", ".ps1", ".py", ".pyi",
  ".rb", ".rs", ".rst", ".scss", ".sh", ".sql", ".swift", ".txt", ".vue", ".xml",
  ".yaml", ".yml",
]);
const DOCUMENT_MEDIA_BY_SUFFIX: Record<string, string> = {
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".json": "application/json",
  ".jsonl": "application/json",
  ".csv": "text/csv",
  ".tsv": "text/tab-separated-values",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".odt": "application/vnd.oasis.opendocument.text",
};
const DOCUMENT_ACCEPT = [
  ...TEXT_DOCUMENT_SUFFIXES,
  ...Object.keys(DOCUMENT_MEDIA_BY_SUFFIX),
].join(",");

function suffix(name: string): string {
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index).toLocaleLowerCase("en-US");
}

function canonicalMediaType(name: string, source: "file" | "microphone"): string | null {
  if (source === "microphone") return "audio/wav";
  const extension = suffix(name);
  if (extension === ".png") return "image/png";
  if (extension === ".jpg" || extension === ".jpeg") return "image/jpeg";
  if (extension === ".wav") return "audio/wav";
  if (TEXT_DOCUMENT_SUFFIXES.has(extension)) return "text/plain";
  return DOCUMENT_MEDIA_BY_SUFFIX[extension] ?? null;
}

function attachmentError(error: unknown): string {
  const reason = error instanceof TransportError ? error.reasonCode : null;
  if (reason === "agent_attachment_image_capability_unavailable") return "This live model did not verify image input.";
  if (reason === "agent_attachment_audio_capability_unavailable") return "This live model did not verify audio input.";
  if (reason === "agent_attachment_document_capability_unavailable") return "This live model did not verify text input for local document projection.";
  if (reason === "agent_attachment_media_mismatch") return "The file contents do not match the selected media type.";
  if (reason === "agent_attachment_document_encoding_unsupported") return "Text documents must use UTF-8 encoding.";
  if (reason === "agent_attachment_document_structure_invalid") return "The document structure is malformed or unsupported.";
  if (reason === "agent_attachment_document_empty") return "The document has no locally extractable text.";
  if (reason === "agent_attachment_dimensions_unsupported") return "That image is too large to decode safely.";
  if (reason === "agent_attachment_duration_unsupported") return "That recording is longer than the five-minute backend limit.";
  if (reason === "agent_attachment_model_changed") return "The live model changed. Remove this attachment and add it again.";
  if (reason === "agent_attachment_stage_limit") return "This chat already has too many staged attachments. Remove one first.";
  if (reason === "agent_attachment_session_too_large") return "This chat reached its private attachment storage limit.";
  if (reason === "turn_in_progress") return "Wait for the current response to finish before changing attachments.";
  if (reason === "agent_attachment_media_unsupported") return "That file type is not supported. PDF input is intentionally unavailable in this checkpoint.";
  return "The attachment could not be admitted. It was not added to the message.";
}

function attachmentRefreshError(error: unknown): string {
  const reason = error instanceof TransportError ? error.reasonCode : null;
  if (reason === "turn_in_progress") return "Staged attachments cannot be refreshed while this chat is responding.";
  if (reason === "agent_attachment_storage_unavailable") return "Private staged-attachment storage is unavailable. Known attachment identities were kept in this window.";
  return "Staged attachments could not be refreshed. Known attachment identities were kept in this window; retry Refresh staged.";
}

function formatBytes(value: number): string {
  return value < 1024 * 1024
    ? `${Math.ceil(value / 1024)} KB`
    : `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function recordingName(): string {
  return `recording-${new Date().toISOString().replace(/[:.]/gu, "-")}.wav`;
}

export function AgentComposerAttachments({
  attachments,
  capabilities,
  compact = false,
  disabled,
  modelAlias,
  onAttachmentsChange,
  onBusyChange,
  runtimeKey,
  sessionId,
  transport,
}: Props) {
  const pickerId = useId();
  const imageInput = useRef<HTMLInputElement | null>(null);
  const audioInput = useRef<HTMLInputElement | null>(null);
  const documentInput = useRef<HTMLInputElement | null>(null);
  const pickerButton = useRef<HTMLButtonElement | null>(null);
  const pickerPanel = useRef<HTMLDivElement | null>(null);
  const previews = useRef(new Map<string, string>());
  const documentPreviews = useRef(new Map<string, AgentAttachmentDocumentPreview>());
  const recorder = useRef<PcmWavRecorder | null>(null);
  const recorderStart = useRef<RecorderStartRequest | null>(null);
  const mutation = useRef<MutationRequest | null>(null);
  const listRequest = useRef<ListRequest | null>(null);
  const context = useRef(0);
  const operationContext = useRef(0);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingStarting, setRecordingStarting] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState("");
  const available = transport.listAgentAttachments !== undefined
    && transport.stageAgentAttachment !== undefined
    && transport.deleteAgentAttachment !== undefined;
  const verified = capabilities?.state === "verified";
  const vision = verified && capabilities.vision;
  const audio = verified && capabilities.audio;
  const text = verified && capabilities.text;
  const documentsAvailable = text
    && transport.getAgentAttachmentDocumentPreview !== undefined;
  const recordingAvailable = audio && capabilities.recording && microphoneCaptureAvailable();
  const incompatibleAttachments = modelAlias === null
    ? []
    : attachments.filter((attachment) => attachment.model_alias !== modelAlias);
  const readyInputs = [
    ...(documentsAvailable ? ["documents"] : []),
    ...(vision ? ["images"] : []),
    ...(audio ? ["audio"] : []),
  ];
  const attachmentStatus = !available
    ? "Attachment service off"
    : !verified
      ? "Model inputs unverified"
      : readyInputs.length > 0
        ? `${readyInputs.join(" + ")} ready`
        : "No attachment inputs verified";

  const replace = (next: AgentAttachment[]) => {
    onAttachmentsChange(next);
  };

  useEffect(() => {
    const generation = context.current + 1;
    context.current = generation;
    operationContext.current += 1;
    const controller = new AbortController();
    const request: ListRequest = { controller, generation };
    listRequest.current?.controller.abort();
    listRequest.current = request;
    mutation.current?.controller.abort();
    mutation.current = null;
    recorderStart.current = null;
    const activeRecorder = recorder.current;
    recorder.current = null;
    activeRecorder?.cancel();
    setRecording(false);
    setRecordingStarting(false);
    setPickerOpen(false);
    setError("");
    setBusy(false);
    setRefreshing(transport.listAgentAttachments !== undefined);
    onBusyChange(false);
    for (const url of previews.current.values()) URL.revokeObjectURL(url);
    previews.current.clear();
    documentPreviews.current.clear();
    const scopedAttachments = attachments.filter((attachment) => attachment.session_id === sessionId);
    if (scopedAttachments.length !== attachments.length) replace(scopedAttachments);
    const list = transport.listAgentAttachments;
    if (list !== undefined) {
      void list(sessionId, controller.signal).then(async (result) => {
        if (listRequest.current !== request || controller.signal.aborted || context.current !== generation) return;
        replace([...result.attachments]);
        await Promise.all(result.attachments.map(async (attachment) => {
          try {
            if (attachment.kind === "document") {
              const getDocumentPreview = transport.getAgentAttachmentDocumentPreview;
              if (getDocumentPreview === undefined) return;
              const preview = await getDocumentPreview(
                sessionId,
                attachment.attachment_id,
                controller.signal,
              );
              if (listRequest.current !== request || controller.signal.aborted || context.current !== generation) return;
              if (preview.sha256 !== attachment.sha256) return;
              documentPreviews.current.set(attachment.attachment_id, preview);
              setPreviewRevision((value) => value + 1);
              return;
            }
            const getContent = transport.getAgentAttachmentContent;
            if (getContent === undefined) return;
            const content = await getContent(
              sessionId,
              attachment.attachment_id,
              controller.signal,
            );
            if (listRequest.current !== request || controller.signal.aborted || context.current !== generation) return;
            previews.current.set(attachment.attachment_id, URL.createObjectURL(content.blob));
            setPreviewRevision((value) => value + 1);
          } catch {
            // Metadata remains usable for removal/send even when preview retrieval fails.
          }
        }));
      }).catch((caught: unknown) => {
        if (listRequest.current === request && !controller.signal.aborted && context.current === generation) {
          setError(attachmentRefreshError(caught));
        }
      }).finally(() => {
        if (listRequest.current === request) {
          listRequest.current = null;
          setRefreshing(false);
        }
      });
    } else {
      listRequest.current = null;
      setRefreshing(false);
    }
    return () => {
      if (context.current === generation) context.current += 1;
      operationContext.current += 1;
      controller.abort();
      if (listRequest.current === request) listRequest.current = null;
      mutation.current?.controller.abort();
      mutation.current = null;
      recorderStart.current = null;
      const currentRecorder = recorder.current;
      recorder.current = null;
      currentRecorder?.cancel();
      for (const url of previews.current.values()) URL.revokeObjectURL(url);
      previews.current.clear();
      documentPreviews.current.clear();
      onBusyChange(false);
    };
  // The transport methods are immutable for one app composition. Including
  // callbacks here would make an inline parent callback erase staged drafts.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    sessionId,
    refreshRevision,
    transport.listAgentAttachments,
    transport.getAgentAttachmentContent,
    transport.getAgentAttachmentDocumentPreview,
    transport.stageAgentAttachment,
    transport.deleteAgentAttachment,
  ]);

  useEffect(() => {
    operationContext.current += 1;
    const pendingMutation = mutation.current;
    const pendingStart = recorderStart.current;
    const activeRecorder = recorder.current;
    mutation.current = null;
    recorderStart.current = null;
    recorder.current = null;
    pendingMutation?.controller.abort();
    activeRecorder?.cancel();
    setBusy(false);
    setRecording(false);
    setRecordingStarting(false);
    onBusyChange(false);
    // Keep an already-open source menu in place while runtime evidence refreshes.
    // Every choice is capability-gated on the new render, while active capture
    // and mutations above are still cancelled against the old runtime identity.
    if (pendingStart !== null || activeRecorder !== null) {
      setError("Recording stopped because the active model or verified input capability changed. No recording was added.");
    } else if (pendingMutation !== null) {
      setError("The attachment action was cancelled because the active model changed. Refresh staged attachments before sending.");
    }
  // The callback is a stable parent state setter. Runtime identity, rather
  // than every coordinator poll, owns capture and mutation cancellation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runtimeKey]);

  useEffect(() => {
    if (!disabled) return;
    const pendingMutation = mutation.current;
    const pendingStart = recorderStart.current;
    const activeRecorder = recorder.current;
    if (pendingMutation === null && pendingStart === null && activeRecorder === null) return;
    operationContext.current += 1;
    mutation.current = null;
    recorderStart.current = null;
    recorder.current = null;
    pendingMutation?.controller.abort();
    activeRecorder?.cancel();
    setBusy(false);
    setRecording(false);
    setRecordingStarting(false);
    onBusyChange(false);
    setError(pendingStart !== null || activeRecorder !== null
      ? "Recording stopped because this chat became busy. No recording was added."
      : "The attachment action was cancelled because this chat became busy. Refresh staged attachments before sending.");
  // See the runtime effect above: this callback is stable for the mounted
  // composer and must not turn an inline callback into a cancellation loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled]);

  useEffect(() => {
    const retained = new Set(attachments.map((attachment) => attachment.attachment_id));
    for (const [attachmentId, url] of previews.current.entries()) {
      if (!retained.has(attachmentId)) {
        URL.revokeObjectURL(url);
        previews.current.delete(attachmentId);
      }
    }
    for (const attachmentId of documentPreviews.current.keys()) {
      if (!retained.has(attachmentId)) documentPreviews.current.delete(attachmentId);
    }
  }, [attachments]);

  useEffect(() => {
    if (!pickerOpen || recording || recordingStarting) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setPickerOpen(false);
      pickerButton.current?.focus();
    };
    const closeOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (pickerButton.current?.contains(target) || pickerPanel.current?.contains(target)) return;
      setPickerOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOutside);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOutside);
    };
  }, [pickerOpen, recording, recordingStarting]);

  async function upload(files: readonly File[] | readonly Blob[], source: "file" | "microphone", names?: readonly string[]) {
    const stage = transport.stageAgentAttachment;
    if (stage === undefined || files.length === 0 || refreshing || mutation.current !== null || recorderStart.current !== null || recorder.current !== null) return;
    if (attachments.length + files.length > MAX_ATTACHMENTS) {
      setError(`A message can contain at most ${MAX_ATTACHMENTS} attachments.`);
      return;
    }
    const candidates = files.map((file, index) => {
      const name = names?.[index] ?? (file instanceof File ? file.name : recordingName());
      const mediaType = canonicalMediaType(name, source);
      const blob = mediaType === null || file.type === mediaType
        ? file
        : file.slice(0, file.size, mediaType);
      return { blob, mediaType, name };
    });
    for (const candidate of candidates) {
      if (candidate.mediaType === null) {
        setError(suffix(candidate.name) === ".pdf"
          ? "PDF input is intentionally unavailable until extraction can be isolated with enforceable memory and time limits."
          : "That file type is not supported by local attachment projection.");
        return;
      }
      const isImage = candidate.mediaType?.startsWith("image/") === true;
      const isAudio = candidate.mediaType === "audio/wav";
      const isDocument = candidate.mediaType !== null && !isImage && !isAudio;
      const isTextDocument = candidate.mediaType !== null
        && [
          "text/plain", "text/markdown", "application/json", "text/csv",
          "text/tab-separated-values",
        ].includes(candidate.mediaType);
      if (
        candidate.blob.size < 1
        || (isImage && (!vision || candidate.blob.size > MAX_IMAGE_BYTES))
        || (isAudio && (!audio || candidate.blob.size > MAX_AUDIO_BYTES))
        || (isDocument && (!documentsAvailable || candidate.blob.size > MAX_DOCUMENT_BYTES))
        || (isTextDocument && candidate.blob.size > MAX_TEXT_DOCUMENT_BYTES)
      ) {
        setError(attachmentError(new TransportError("Attachment selection was invalid", 422)));
        return;
      }
    }
    listRequest.current?.controller.abort();
    listRequest.current = null;
    setRefreshing(false);
    const request: MutationRequest = {
      controller: new AbortController(),
      generation: operationContext.current,
    };
    mutation.current = request;
    setBusy(true);
    onBusyChange(true);
    setError("");
    let next = [...attachments];
    try {
      for (const candidate of candidates) {
        const admitted = await stage(sessionId, {
          blob: candidate.blob,
          displayName: candidate.name,
          source,
        }, request.controller.signal);
        if (mutation.current !== request || request.controller.signal.aborted || request.generation !== operationContext.current) return;
        if (admitted.session_id !== sessionId || (modelAlias !== null && admitted.model_alias !== modelAlias)) {
          throw new TransportError("The live model changed while staging media", 409, "agent_attachment_model_changed");
        }
        next = [...next, admitted];
        replace(next);
        try {
          if (admitted.kind === "document") {
            const getDocumentPreview = transport.getAgentAttachmentDocumentPreview;
            if (getDocumentPreview === undefined) {
              throw new Error("document preview transport unavailable");
            }
            const preview = await getDocumentPreview(
              sessionId,
              admitted.attachment_id,
              request.controller.signal,
            );
            if (preview.sha256 !== admitted.sha256) {
              throw new Error("document preview identity mismatch");
            }
            documentPreviews.current.set(admitted.attachment_id, preview);
          } else {
            previews.current.set(
              admitted.attachment_id,
              URL.createObjectURL(candidate.blob),
            );
          }
          setPreviewRevision((value) => value + 1);
        } catch {
          // The admitted identity remains sendable when this window cannot
          // render its private preview; preview availability is not authority.
        }
      }
    } catch (caught) {
      if (mutation.current === request && !request.controller.signal.aborted && request.generation === operationContext.current) {
        setError(attachmentError(caught));
      }
    } finally {
      if (mutation.current === request) {
        mutation.current = null;
        setBusy(false);
        onBusyChange(false);
      }
    }
  }

  async function remove(attachment: AgentAttachment) {
    const removeAttachment = transport.deleteAgentAttachment;
    if (removeAttachment === undefined || refreshing || mutation.current !== null || recorderStart.current !== null || recorder.current !== null) return;
    listRequest.current?.controller.abort();
    listRequest.current = null;
    setRefreshing(false);
    const request: MutationRequest = {
      controller: new AbortController(),
      generation: operationContext.current,
    };
    mutation.current = request;
    setBusy(true);
    onBusyChange(true);
    setError("");
    try {
      await removeAttachment(sessionId, attachment.attachment_id, request.controller.signal);
      if (mutation.current !== request || request.controller.signal.aborted || request.generation !== operationContext.current) return;
      replace(attachments.filter((item) => item.attachment_id !== attachment.attachment_id));
    } catch (caught) {
      if (mutation.current === request && !request.controller.signal.aborted && request.generation === operationContext.current) {
        setError(attachmentError(caught));
      }
    } finally {
      if (mutation.current === request) {
        mutation.current = null;
        setBusy(false);
        onBusyChange(false);
      }
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    if (!recordingAvailable || disabled || busy || refreshing || recorderStart.current !== null || mutation.current !== null) return;
    const request: RecorderStartRequest = { generation: operationContext.current };
    recorderStart.current = request;
    setBusy(true);
    setRecordingStarting(true);
    onBusyChange(true);
    setError("");
    try {
      const active = await startPcmWavRecorder();
      if (recorderStart.current !== request || request.generation !== operationContext.current) {
        active.cancel();
        return;
      }
      recorderStart.current = null;
      recorder.current = active;
      setBusy(false);
      setRecordingStarting(false);
      setRecording(true);
      void active.finished.then((blob) => {
        if (recorder.current === active) recorder.current = null;
        if (request.generation !== operationContext.current) return;
        setRecording(false);
        if (blob === null) {
          onBusyChange(false);
          return;
        }
        void upload([blob], "microphone", [recordingName()]).finally(() => {
          if (request.generation === operationContext.current && mutation.current === null) onBusyChange(false);
        });
      });
    } catch {
      if (recorderStart.current !== request || request.generation !== operationContext.current) return;
      recorderStart.current = null;
      setBusy(false);
      setRecordingStarting(false);
      onBusyChange(false);
      setRecording(false);
      setError("Microphone permission or local PCM recording is unavailable in this window.");
    }
  }

  return (
    <section
      aria-label="Message attachments"
      className={`agent-attachments${compact ? " agent-attachments--compact" : ""}`}
      data-has-attachments={attachments.length > 0 ? "true" : "false"}
      data-preview-revision={previewRevision}
    >
      <input
        accept="image/png,image/jpeg"
        aria-label="Choose images"
        disabled={disabled || busy || refreshing || recording || !available || !vision || attachments.length >= MAX_ATTACHMENTS}
        hidden
        multiple
        onChange={(event) => {
          const files = [...(event.currentTarget.files ?? [])];
          event.currentTarget.value = "";
          void upload(files, "file");
        }}
        ref={imageInput}
        type="file"
      />
      <input
        accept="audio/wav,.wav"
        aria-label="Choose WAV audio"
        disabled={disabled || busy || refreshing || recording || !available || !audio || attachments.length >= MAX_ATTACHMENTS}
        hidden
        multiple
        onChange={(event) => {
          const files = [...(event.currentTarget.files ?? [])];
          event.currentTarget.value = "";
          void upload(files, "file");
        }}
        ref={audioInput}
        type="file"
      />
      <input
        accept={DOCUMENT_ACCEPT}
        aria-label="Choose documents"
        disabled={disabled || busy || refreshing || recording || !available || !documentsAvailable || attachments.length >= MAX_ATTACHMENTS}
        hidden
        multiple
        onChange={(event) => {
          const files = [...(event.currentTarget.files ?? [])];
          event.currentTarget.value = "";
          void upload(files, "file");
        }}
        ref={documentInput}
        type="file"
      />
      <div className="agent-attachments__toolbar">
        <button
          aria-label={compact ? "Attach" : undefined}
          aria-controls={pickerId}
          aria-expanded={pickerOpen}
          className={`button button--ghost${compact ? " agent-attachments__icon-button" : ""}`}
          disabled={disabled || busy || refreshing || recording || !available || attachments.length >= MAX_ATTACHMENTS}
          onClick={() => setPickerOpen((value) => !value)}
          ref={pickerButton}
          title="Choose a locally validated document, image, WAV file, or microphone recording"
          type="button"
        >
          {compact ? (
            <>
              <Icon name="paperclip" />
              <span className="sr-only agent-attachments__forced-color-label">Attach</span>
            </>
          ) : "Attach"}
          <span aria-hidden="true" className="agent-attachments__count">{attachments.length}/{MAX_ATTACHMENTS}</span>
        </button>
        {!compact && (
          <button
            className="button button--ghost"
            disabled={busy || refreshing || recording || !available}
            onClick={() => setRefreshRevision((value) => value + 1)}
            title="Refresh attachments staged by this window or a connected external agent"
            type="button"
          >Refresh staged</button>
        )}
        {compact && (
          <button
            aria-label={recording ? "Stop audio recording" : "Record audio"}
            aria-pressed={recording}
            className={`${recording ? "button button--danger-ghost" : "button button--ghost"} agent-attachments__icon-button`}
            disabled={!recording && (disabled || busy || refreshing || recordingStarting || !available || !recordingAvailable || attachments.length >= MAX_ATTACHMENTS)}
            onClick={() => void toggleRecording()}
            title={recordingAvailable ? "Record local PCM WAV audio" : "Verified audio input and microphone access are required"}
            type="button"
          >
            <Icon name={recording ? "stop" : "microphone"} />
            <span className="sr-only agent-attachments__forced-color-label">
              {recording ? "Stop recording" : recordingStarting ? "Starting microphone…" : "Record audio"}
            </span>
          </button>
        )}
        <span aria-live="polite" className="agent-attachments__status" title={attachmentStatus}>{attachmentStatus}</span>
      </div>
      {pickerOpen && (
        <div
          aria-label="Attachment sources"
          className="agent-attachments__picker"
          id={pickerId}
          ref={pickerPanel}
          role="group"
        >
          <div className="agent-attachments__picker-actions">
            {compact && (
              <button
                className="button button--ghost"
                disabled={busy || refreshing || recording || !available}
                onClick={() => setRefreshRevision((value) => value + 1)}
                title="Refresh attachments staged by this window or a connected external agent"
                type="button"
              ><Icon name="refresh" /> Refresh staged</button>
            )}
            <button
              className="button button--ghost"
              disabled={disabled || busy || refreshing || recording || !available || !vision || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => {
                setPickerOpen(false);
                imageInput.current?.click();
              }}
              title={vision ? "Attach a locally structure-validated PNG or JPEG" : "The live model has not verified image input"}
              type="button"
            >Add image</button>
            <button
              className="button button--ghost"
              disabled={disabled || busy || refreshing || recording || !available || !audio || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => {
                setPickerOpen(false);
                audioInput.current?.click();
              }}
              title={audio ? "Attach validated PCM WAV audio" : "The live model has not verified audio input"}
              type="button"
            >Add audio</button>
            <button
              className="button button--ghost"
              disabled={disabled || busy || refreshing || recording || !available || !documentsAvailable || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => {
                setPickerOpen(false);
                documentInput.current?.click();
              }}
              title={documentsAvailable
                ? "Attach a bounded UTF-8, data, Office, or ODT document for local text projection"
                : "Verified text input and the private document-preview service are required"}
              type="button"
            >Add document</button>
            {!compact && (
              <button
                aria-pressed={recording}
                className={recording ? "button button--danger-ghost" : "button button--ghost"}
                disabled={!recording && (disabled || busy || refreshing || recordingStarting || !available || !recordingAvailable || attachments.length >= MAX_ATTACHMENTS)}
                onClick={() => void toggleRecording()}
                title={recordingAvailable ? "Record local PCM WAV audio" : "Verified audio input and microphone access are required"}
                type="button"
              >{recording ? "Stop recording" : recordingStarting ? "Starting microphone…" : "Record audio"}</button>
            )}
          </div>
          {!vision && !audio && !documentsAvailable && (
            <p className="agent-attachments__hint">Attachments are locked until the served model passes the matching live capability probe.</p>
          )}
          {documentsAvailable && <p className="agent-attachments__hint">Document text is extracted locally into a bounded, inert projection. Original Office bytes never reach the model. PDF input remains unavailable.</p>}
          {audio && <p className="agent-attachments__hint">Audio input is experimental in llama.cpp. This app admits validated PCM WAV only.</p>}
        </div>
      )}
      {refreshing && <p className="agent-attachments__recording" role="status">Refreshing staged attachments…</p>}
      {recordingStarting && <p className="agent-attachments__recording" role="status">Waiting for this window's microphone permission…</p>}
      {recording && <p className="agent-attachments__recording" role="status">Recording locally… maximum 2 minutes</p>}
      {busy && !recordingStarting && !recording && <p className="agent-attachments__recording" role="status">Updating staged attachments…</p>}
      {incompatibleAttachments.length > 0 && (
        <p className="agent-attachments__error" role="alert">
          {incompatibleAttachments.length === 1 ? "One staged attachment belongs" : `${incompatibleAttachments.length} staged attachments belong`} to a different model. Remove {incompatibleAttachments.length === 1 ? "it" : "them"} and add {incompatibleAttachments.length === 1 ? "it" : "them"} again before sending.
        </p>
      )}
      {attachments.length > 0 && (
        <ul className="agent-attachments__list">
          {attachments.map((attachment) => {
            const preview = previews.current.get(attachment.attachment_id);
            const documentPreview = documentPreviews.current.get(attachment.attachment_id);
            return (
              <li
                className={attachment.kind === "document" ? "agent-attachments__item--document" : undefined}
                key={attachment.attachment_id}
              >
                {preview && attachment.kind === "image" ? <img alt={`Preview ${attachment.display_name}`} src={preview} /> : null}
                {preview && attachment.kind === "audio" ? <audio aria-label={`Preview ${attachment.display_name}`} controls preload="metadata" src={preview} /> : null}
                {attachment.kind === "document" ? <span aria-hidden="true" className="agent-attachments__document-icon">DOC</span> : null}
                <span>
                  <strong>{attachment.display_name}</strong>
                  <small>
                    {attachment.kind === "document" ? attachment.document_format : attachment.kind} · {formatBytes(attachment.byte_size)}
                     {attachment.source === "external_agent" ? " · via external agent" : ""}
                    {modelAlias !== null && attachment.model_alias !== modelAlias ? " · different model" : ""}
                    {" · context cost unknown"}
                  </small>
                </span>
                <button
                  aria-label={`Remove ${attachment.display_name}`}
                  className="button button--ghost"
                  disabled={disabled || busy || refreshing || recording}
                  onClick={() => void remove(attachment)}
                  type="button"
                >Remove</button>
                {attachment.kind === "document" && documentPreview ? (
                  <details className="agent-attachments__document-preview">
                    <summary>
                      Extracted preview
                      {documentPreview.preview_truncated ? " · excerpt" : ""}
                    </summary>
                    <pre>{documentPreview.text}</pre>
                    <p>
                      {documentPreview.projected_characters.toLocaleString()} projected characters
                      {documentPreview.projection_truncated ? " · model projection truncated" : ""}
                      {documentPreview.omitted_features.length > 0
                        ? ` · omitted: ${documentPreview.omitted_features.join(", ")}`
                        : ""}
                    </p>
                  </details>
                ) : null}
                {attachment.kind === "document" && !documentPreview ? (
                  <p className="agent-attachments__preview-unavailable">Local text preview unavailable; the staged identity remains removable and sendable.</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {error && <p className="agent-attachments__error" role="alert">{error}</p>}
    </section>
  );
}
