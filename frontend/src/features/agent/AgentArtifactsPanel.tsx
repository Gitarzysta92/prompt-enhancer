import { lazy, Suspense, useEffect, useRef, useState } from "react";

import type {
  AgentArtifact,
  AgentArtifactContent,
  AgentArtifactDetail,
  AgentArtifactExport,
  AgentArtifactLifecycleCounts,
  AgentArtifactListView,
  AgentArtifactVersion,
  AgentDocumentPreview as DocumentPreview,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { Dialog } from "../../shared/ui/Dialog";
import { AgentDocumentPreview } from "./AgentDocumentPreview";
import { AgentMessageContent } from "./AgentMessageContent";
import "./AgentArtifactsPanel.css";

const AgentPdfPreview = lazy(async () => {
  const module = await import("./AgentPdfPreview");
  return { default: module.AgentPdfPreview };
});

const MAX_INLINE_TEXT_BYTES = 1024 * 1024;
const ARTIFACT_PAGE_SIZE = 50;
const SAFE_DOWNLOAD_FILENAME = /^agent-artifact-[0-9a-f]{8}(?:\.[A-Za-z0-9]{1,15})?$/u;
const SAFE_EXPORT_FILENAME = /^agent-artifact-[0-9a-f]{8}-v[1-9][0-9]{0,3}-lineage\.json$/u;
const MIN_IMAGE_ZOOM = 0.5;
const MAX_IMAGE_ZOOM = 3;
const IMAGE_ZOOM_STEP = 0.25;

type ArtifactTransport = Pick<
  PromptEnhancerTransport,
  "getAgentArtifact" | "getAgentArtifactContent" | "removeAgentArtifact" | "updateAgentArtifact"
> & Partial<Pick<PromptEnhancerTransport, "exportAgentArtifact" | "getAgentArtifactDocumentPreview">>;

export type AgentArtifactOpenRequest = {
  projectId: string;
  sessionId: string;
  artifactId: string;
  path: string;
  requestId: number;
};

type ViewerState =
  | { phase: "closed" }
  | { phase: "loading"; artifact: AgentArtifact }
  | { phase: "ready"; artifact: AgentArtifactDetail }
  | { phase: "error"; artifact: AgentArtifact; message: string };

type PreviewAvailability = AgentArtifactDetail["availability"] | "unavailable";

type PreviewState =
  | { phase: "idle" }
  | { phase: "loading"; version: AgentArtifactVersion }
  | {
      phase: "ready";
      version: AgentArtifactVersion;
      availability: PreviewAvailability;
      content: AgentArtifactContent | null;
      document: DocumentPreview | null;
      downloadable: boolean;
      text: string | null;
      objectUrl: string | null;
      message: string;
    };

type MediaPreviewKind = Extract<AgentArtifactVersion["preview_kind"], "image" | "pdf">;

type MediaRenderState =
  | { phase: "idle" }
  | { phase: "loading" | "ready" | "error"; versionId: string; kind: MediaPreviewKind };

type DownloadRequest = {
  artifactId: string;
  controller: AbortController;
  scopeKey: string;
  transport: ArtifactTransport;
  versionId: string;
};

type ExportRequest = {
  artifactId: string;
  controller: AbortController;
  scopeKey: string;
  transport: ArtifactTransport;
  versionId: string;
};

type LifecycleOperation = "rename" | "archive" | "restore" | "recover" | "remove";

type LifecycleDialogState = {
  artifact: AgentArtifact;
  busy: boolean;
  error: string;
  title: string;
};

const LIFECYCLE_VIEWS: Array<{
  label: string;
  value: Exclude<AgentArtifactListView, "all">;
}> = [
  { label: "Active", value: "active" },
  { label: "Archived", value: "archived" },
  { label: "Removed", value: "removed" },
];

class ArtifactContentMismatchError extends Error {
  constructor() {
    super("Artifact content did not match its recorded version");
    this.name = "ArtifactContentMismatchError";
  }
}

class ArtifactExportMismatchError extends Error {
  constructor() {
    super("Artifact lineage export did not match its recorded version");
    this.name = "ArtifactExportMismatchError";
  }
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function versionProvenance(version: AgentArtifactVersion): string {
  return version.provenance === "reviewed_write"
    ? typeof version.source_event_seq === "number"
      ? `Reviewed write · event ${version.source_event_seq}`
      : "Reviewed write"
    : version.provenance === "reviewed_move"
      ? "Reviewed move"
      : version.provenance === "verified_output"
      ? "Native capture"
      : "Unverified output";
}

function versionSource(version: AgentArtifactVersion): string {
  if (typeof version.source_turn_id === "string") {
    return `Turn ${version.source_turn_id.slice(0, 8)}…${typeof version.source_event_seq === "number" ? ` · event ${version.source_event_seq}` : ""}`;
  }
  return version.provenance === "reviewed_move"
    ? "Reviewed move · no new producing turn"
    : "Native capture · no producing turn claimed";
}

function byteDelta(value: number): string {
  if (value === 0) return "No size change";
  return `${value > 0 ? "+" : "−"}${bytes(Math.abs(value))}`;
}

function provenance(artifact: AgentArtifact): string {
  return versionProvenance(artifact.latest_version);
}

function lifecycleFailure(error: unknown): string {
  if (error instanceof TransportError) {
    if (error.reasonCode === "agent_artifact_revision_conflict") {
      return "This artifact changed in another view. Refresh the list, review its current state, and try again.";
    }
    if (error.reasonCode === "agent_artifact_archive_required") {
      return "Archive this artifact before moving its record to Removed.";
    }
    if (error.reasonCode === "agent_artifact_state_conflict") {
      return "That action no longer matches the artifact’s current lifecycle state. Refresh and try again.";
    }
    if (error.reasonCode === "agent_artifact_no_change") {
      return "The display name is already set to that value.";
    }
    if (error.reasonCode === "agent_artifact_removed") {
      return "This artifact is in Removed. Recover it to Archived before using it again.";
    }
    if (error.status === 503) {
      return "Native confirmation is unavailable. The artifact record was not moved and the workspace file was not changed.";
    }
  }
  return "The artifact lifecycle action could not be confirmed. Nothing was deleted or overwritten.";
}

function availabilityMessage(availability: PreviewAvailability, versionNumber: number): string {
  if (availability === "stale") return "The workspace file changed after this version was recorded. Its current bytes will not be shown as this artifact.";
  if (availability === "missing") return "The recorded workspace file no longer exists.";
  if (availability === "malformed") return "The current bytes do not match the validated preview type.";
  if (availability === "unavailable") return `Recorded v${versionNumber} could not be revalidated or previewed from the current workspace. It was not shown or downloaded.`;
  return `Recorded v${versionNumber} has not been revalidated against the current workspace bytes yet.`;
}

function previewFailure(error: unknown, versionNumber: number): {
  availability: PreviewAvailability;
  message: string;
} {
  if (error instanceof ArtifactExportMismatchError) {
    return {
      availability: "malformed",
      message: `The lineage export did not match recorded v${versionNumber} identity, revision, digest, size, or privacy flags. No export file was created.`,
    };
  }
  if (error instanceof ArtifactContentMismatchError) {
    return {
      availability: "malformed",
      message: `The bytes returned for recorded v${versionNumber} did not match its declared media type, size, or safe filename. They were not displayed or downloaded.`,
    };
  }
  const status = typeof error === "object" && error !== null && "status" in error
    && typeof error.status === "number"
    ? error.status
    : null;
  if (status === 409) {
    return {
      availability: "stale",
      message: `The current workspace bytes do not match recorded v${versionNumber}, so that historical content cannot be shown or downloaded.`,
    };
  }
  if (status === 404) return { availability: "missing", message: availabilityMessage("missing", versionNumber) };
  if (status === 422) return { availability: "malformed", message: availabilityMessage("malformed", versionNumber) };
  return { availability: "unavailable", message: availabilityMessage("unavailable", versionNumber) };
}

function isTerminalDownloadFailure(error: unknown): boolean {
  if (
    error instanceof ArtifactContentMismatchError
    || error instanceof ArtifactExportMismatchError
  ) return true;
  const status = typeof error === "object" && error !== null && "status" in error
    && typeof error.status === "number"
    ? error.status
    : null;
  return status === 404 || status === 409 || status === 422;
}

function assertArtifactContentMatches(
  content: AgentArtifactContent,
  version: AgentArtifactVersion,
  download: boolean,
): void {
  const expectedContentType = download
    ? "application/octet-stream"
    : version.preview_kind === "text"
      ? "text/plain; charset=utf-8"
      : version.media_type;
  if (
    content.contentType !== expectedContentType
    || content.byteSize !== version.byte_size
    || content.blob.size !== version.byte_size
    || !SAFE_DOWNLOAD_FILENAME.test(content.filename)
  ) {
    throw new ArtifactContentMismatchError();
  }
}

function assertArtifactExportMatches(
  exported: AgentArtifactExport,
  detail: AgentArtifactDetail,
  version: AgentArtifactVersion,
): void {
  if (
    exported.contract_version !== "agent-artifact-export.v1"
    || exported.artifact.artifact_id !== detail.artifact_id
    || exported.artifact.project_id !== detail.project_id
    || exported.artifact.session_id !== detail.session_id
    || exported.artifact.revision !== detail.revision
    || exported.selected_version.version_id !== version.version_id
    || exported.selected_version.sha256 !== version.sha256
    || exported.selected_version.byte_size !== version.byte_size
    || exported.evidence.verification !== "exact_current_workspace_readback"
    || exported.evidence.algorithm !== "sha256"
    || exported.evidence.sha256 !== version.sha256
    || exported.evidence.byte_size !== version.byte_size
    || exported.evidence.verified !== true
    || exported.content_included !== false
    || exported.absolute_path_included !== false
    || exported.sensitivity !== "sensitive_local_metadata"
  ) throw new ArtifactExportMismatchError();
}

export function AgentArtifactsPanel({
  artifacts,
  canLoadMore = false,
  counts,
  error,
  loading,
  onCaptureCurrent,
  onOpenFile,
  onOpenSourceTurn,
  onViewerReady,
  onLoadMore,
  onRevealFile,
  onRefresh,
  onReviewChanges,
  onViewChange,
  openRequest,
  pageError = "",
  pageLoading = false,
  projectId,
  sessionId,
  transport,
  userPresenceAvailable,
  view,
}: {
  artifacts: AgentArtifact[];
  canLoadMore?: boolean;
  counts: AgentArtifactLifecycleCounts | null;
  error: string;
  loading: boolean;
  onCaptureCurrent?: (path: string) => void;
  onOpenFile?: (path: string) => void;
  onOpenSourceTurn?: (turnId: string) => boolean;
  onViewerReady?: () => void;
  onLoadMore?: () => void;
  onRevealFile?: (path: string) => void;
  onRefresh: () => void;
  onReviewChanges?: (path: string) => void;
  onViewChange: (view: Exclude<AgentArtifactListView, "all">) => void;
  openRequest?: AgentArtifactOpenRequest | null;
  pageError?: string;
  pageLoading?: boolean;
  projectId: string;
  sessionId: string;
  transport: ArtifactTransport;
  userPresenceAvailable: boolean;
  view: Exclude<AgentArtifactListView, "all">;
}) {
  const [viewer, setViewer] = useState<ViewerState>({ phase: "closed" });
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [comparisonVersionId, setComparisonVersionId] = useState<string | null>(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewState>({ phase: "idle" });
  const [mediaRender, setMediaRender] = useState<MediaRenderState>({ phase: "idle" });
  const [imageZoom, setImageZoom] = useState(1);
  const [markdownMode, setMarkdownMode] = useState<"preview" | "source">("preview");
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState("");
  const onViewerReadyRef = useRef(onViewerReady);
  const reportedViewerKey = useRef<string | null>(null);
  const [exportNotice, setExportNotice] = useState("");
  const [sourceTurnNotice, setSourceTurnNotice] = useState("");
  const [lifecycleDialog, setLifecycleDialog] = useState<LifecycleDialogState | null>(null);
  const [lifecycleNotice, setLifecycleNotice] = useState("");
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const viewerRef = useRef<HTMLElement | null>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    onViewerReadyRef.current = onViewerReady;
  }, [onViewerReady]);
  const [viewerScope, setViewerScope] = useState<string | null>(null);
  const scopeKey = `${projectId}:${sessionId}`;
  const downloadRequest = useRef<DownloadRequest | null>(null);
  const exportRequest = useRef<ExportRequest | null>(null);
  const requestContext = useRef({ scopeKey, transport });
  const handledOpenRequest = useRef<AgentArtifactOpenRequest | null>(null);
  const lifecycleRequest = useRef<AbortController | null>(null);
  const renameRef = useRef<HTMLInputElement | null>(null);
  requestContext.current = { scopeKey, transport };
  const artifactPage = useBoundedListPage({
    itemCount: artifacts.length,
    pageSize: ARTIFACT_PAGE_SIZE,
    resetKey: `${scopeKey}:${view}`,
  });
  const visibleArtifacts = artifacts.slice(artifactPage.start, artifactPage.end);

  useEffect(() => {
    if (
      viewer.phase !== "ready"
      || preview.phase !== "ready"
      || viewerScope !== scopeKey
    ) return;
    const kind = preview.version.preview_kind;
    const previewReady = kind === "text"
      ? preview.availability === "available" && preview.text !== null
      : kind === "document"
        ? preview.availability === "available" && preview.document !== null
        : kind === "image" || kind === "pdf"
          ? mediaRender.phase === "ready"
            && mediaRender.versionId === preview.version.version_id
            && mediaRender.kind === kind
          : preview.message === ""
            && (preview.availability === "available" || preview.availability === "unchecked");
    if (!previewReady) return;
    const evidenceKey = `${scopeKey}:${viewer.artifact.artifact_id}:${viewer.artifact.revision}:${preview.version.version_id}`;
    if (reportedViewerKey.current === evidenceKey) return;
    reportedViewerKey.current = evidenceKey;
    onViewerReadyRef.current?.();
  }, [mediaRender, preview, scopeKey, viewer, viewerScope]);

  useEffect(() => () => {
    handledOpenRequest.current = null;
  }, [scopeKey, transport]);

  useEffect(() => {
    lifecycleRequest.current?.abort();
    lifecycleRequest.current = null;
    setLifecycleDialog(null);
    setLifecycleNotice("");
  }, [scopeKey, transport]);

  useEffect(() => () => lifecycleRequest.current?.abort(), []);

  useEffect(() => {
    setSourceTurnNotice("");
  }, [scopeKey, transport]);

  useEffect(() => {
    if (
      openRequest === null
      || openRequest === undefined
      || openRequest.projectId !== projectId
      || openRequest.sessionId !== sessionId
      || handledOpenRequest.current?.requestId === openRequest.requestId
    ) return;
    const artifact = artifacts.find((candidate) => (
      candidate.artifact_id === openRequest.artifactId
      && candidate.path === openRequest.path
    ));
    if (artifact === undefined) return;
    handledOpenRequest.current = openRequest;
    openViewer(artifact);
  }, [artifacts, openRequest, projectId, sessionId]);

  useEffect(() => {
    if (viewer.phase !== "closed" && viewerScope !== scopeKey) closeViewer();
  }, [scopeKey, viewer.phase, viewerScope]);

  useEffect(() => {
    setDownloadBusy(false);
    return () => {
      const request = downloadRequest.current;
      if (request === null) return;
      downloadRequest.current = null;
      request.controller.abort();
    };
  }, [scopeKey, transport]);

  useEffect(() => {
    setExportBusy(false);
    setExportError("");
    setExportNotice("");
    return () => {
      const request = exportRequest.current;
      if (request === null) return;
      exportRequest.current = null;
      request.controller.abort();
    };
  }, [scopeKey, transport]);

  useEffect(() => {
    if (viewer.phase === "closed" || viewerScope !== scopeKey) return;
    const controller = new AbortController();
    const source = viewer.artifact;
    void (async () => {
      const detail = await transport.getAgentArtifact(
        projectId,
        sessionId,
        source.artifact_id,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setSelectedVersionId(detail.latest_version.version_id);
      setComparisonVersionId(
        detail.versions.length > 1
          ? detail.versions[detail.versions.length - 2].version_id
          : null,
      );
      setViewer({ phase: "ready", artifact: detail });
    })().catch(() => {
      if (!controller.signal.aborted) {
        setViewer({
          phase: "error",
          artifact: source,
          message: "This artifact could not be revalidated or previewed. The workspace was not changed.",
        });
      }
    });
    return () => controller.abort();
  }, [
    viewer.phase === "closed" ? null : viewer.artifact.artifact_id,
    projectId,
    sessionId,
    transport,
    viewerScope,
    scopeKey,
  ]);

  useEffect(() => {
    if (
      viewer.phase !== "ready"
      || selectedVersionId === null
      || viewerScope !== scopeKey
    ) return;
    const detail = viewer.artifact;
    const version = detail.versions.find((candidate) => candidate.version_id === selectedVersionId);
    if (version === undefined) {
      setPreview({ phase: "idle" });
      return;
    }
    const controller = new AbortController();
    const isLatest = version.version_id === detail.latest_version.version_id;
    const knownAvailability: PreviewAvailability = isLatest ? detail.availability : "unchecked";
    let objectUrl: string | null = null;
    setMediaRender({ phase: "idle" });
    setImageZoom(1);
    setPreview({ phase: "loading", version });
    void (async () => {
      if (
        knownAvailability !== "available" && knownAvailability !== "unchecked"
        || version.preview_kind === "download_only"
        || (version.preview_kind === "text" && version.byte_size > MAX_INLINE_TEXT_BYTES)
      ) {
        setPreview({
          phase: "ready",
          version,
          availability: knownAvailability,
          content: null,
          document: null,
          downloadable: knownAvailability === "available" || knownAvailability === "unchecked",
          text: null,
          objectUrl: null,
          message: "",
        });
        return;
      }
      if (version.preview_kind === "document") {
        const loadDocumentPreview = transport.getAgentArtifactDocumentPreview;
        if (loadDocumentPreview === undefined) throw new Error("document_preview_unavailable");
        const document = await loadDocumentPreview(
          projectId,
          sessionId,
          detail.artifact_id,
          version,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setPreview({
            phase: "ready",
            version,
            availability: "available",
            content: null,
            document,
            downloadable: true,
            text: null,
            objectUrl: null,
            message: "",
          });
        }
        return;
      }
      const content = await transport.getAgentArtifactContent(
        projectId,
        sessionId,
        detail.artifact_id,
        version.version_id,
        false,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      assertArtifactContentMatches(content, version, false);
      if (version.preview_kind === "text") {
        const text = await content.blob.text();
        if (!controller.signal.aborted) {
          setPreview({
            phase: "ready",
            version,
            availability: "available",
            content,
            document: null,
            downloadable: true,
            text,
            objectUrl: null,
            message: "",
          });
        }
        return;
      }
      if (version.preview_kind === "pdf") {
        setMediaRender({
          phase: "loading",
          versionId: version.version_id,
          kind: "pdf",
        });
        setPreview({
          phase: "ready",
          version,
          availability: "available",
          content,
          document: null,
          downloadable: true,
          text: null,
          objectUrl: null,
          message: "",
        });
        return;
      }
      if (version.preview_kind !== "image") throw new ArtifactContentMismatchError();
      if (typeof URL.createObjectURL !== "function") {
        throw new Error("object_url_unavailable");
      }
      objectUrl = URL.createObjectURL(content.blob);
      setMediaRender({
        phase: "loading",
        versionId: version.version_id,
        kind: version.preview_kind,
      });
      setPreview({
        phase: "ready",
        version,
        availability: "available",
        content,
        document: null,
        downloadable: true,
        text: null,
        objectUrl,
        message: "",
      });
    })().catch((error: unknown) => {
      if (!controller.signal.aborted) {
        const failure = previewFailure(error, version.version_number);
        const status = typeof error === "object" && error !== null && "status" in error
          && typeof error.status === "number"
          ? error.status
          : null;
        const documentDownloadFallback = version.preview_kind === "document"
          && (knownAvailability === "available" || knownAvailability === "unchecked")
          && status !== 404
          && status !== 409;
        setMediaRender({ phase: "idle" });
        setPreview({
          phase: "ready",
          version,
          availability: failure.availability,
          content: null,
          document: null,
          downloadable: documentDownloadFallback,
          text: null,
          objectUrl: null,
          message: documentDownloadFallback
            ? `Recorded v${version.version_number} could not be rendered as a bounded document preview. Nothing was executed or fetched; the exact digest-verified file remains available for explicit download.`
            : failure.message,
        });
      }
    });
    return () => {
      controller.abort();
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    };
  }, [
    viewer.phase === "ready" ? viewer.artifact.revision : null,
    selectedVersionId,
    projectId,
    sessionId,
    transport,
    viewerScope,
    scopeKey,
  ]);

  useEffect(() => {
    if (viewer.phase === "closed") return;
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeViewer();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = viewerRef.current;
      if (dialog === null) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", keyboard);
    window.setTimeout(() => closeRef.current?.focus(), 0);
    return () => window.removeEventListener("keydown", keyboard);
  }, [viewer.phase === "closed"]);

  function openViewer(artifact: AgentArtifact): void {
    cancelDownload();
    cancelExport();
    previousFocus.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    setDownloadError("");
    setExportError("");
    setExportNotice("");
    setSourceTurnNotice("");
    setMarkdownMode("preview");
    setSelectedVersionId(null);
    setComparisonVersionId(null);
    setComparisonOpen(false);
    setPreview({ phase: "idle" });
    setMediaRender({ phase: "idle" });
    setImageZoom(1);
    reportedViewerKey.current = null;
    setViewerScope(scopeKey);
    setViewer({ phase: "loading", artifact });
  }

  function closeViewer(): void {
    cancelDownload();
    cancelExport();
    setViewer({ phase: "closed" });
    setSelectedVersionId(null);
    setComparisonVersionId(null);
    setComparisonOpen(false);
    setPreview({ phase: "idle" });
    setMediaRender({ phase: "idle" });
    setImageZoom(1);
    setViewerScope(null);
    setDownloadBusy(false);
    setDownloadError("");
    setExportError("");
    setExportNotice("");
    window.setTimeout(() => previousFocus.current?.focus(), 0);
  }

  function ownsDownload(request: DownloadRequest): boolean {
    return downloadRequest.current === request
      && !request.controller.signal.aborted
      && requestContext.current.scopeKey === request.scopeKey
      && requestContext.current.transport === request.transport;
  }

  function cancelDownload(): void {
    const request = downloadRequest.current;
    if (request === null) return;
    downloadRequest.current = null;
    request.controller.abort();
    setDownloadBusy(false);
  }

  function ownsExport(request: ExportRequest): boolean {
    return exportRequest.current === request
      && !request.controller.signal.aborted
      && requestContext.current.scopeKey === request.scopeKey
      && requestContext.current.transport === request.transport;
  }

  function cancelExport(): void {
    const request = exportRequest.current;
    if (request === null) return;
    exportRequest.current = null;
    request.controller.abort();
    setExportBusy(false);
  }

  async function download(detail: AgentArtifactDetail, version: AgentArtifactVersion): Promise<void> {
    if (downloadBusy || downloadRequest.current !== null) return;
    const request: DownloadRequest = {
      artifactId: detail.artifact_id,
      controller: new AbortController(),
      scopeKey,
      transport,
      versionId: version.version_id,
    };
    downloadRequest.current = request;
    setDownloadBusy(true);
    setDownloadError("");
    try {
      const content = await transport.getAgentArtifactContent(
        projectId,
        sessionId,
        detail.artifact_id,
        version.version_id,
        true,
        request.controller.signal,
      );
      if (!ownsDownload(request)) return;
      assertArtifactContentMatches(content, version, true);
      if (typeof URL.createObjectURL !== "function") throw new Error("object_url_unavailable");
      const url = URL.createObjectURL(content.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = content.filename;
      link.rel = "noopener noreferrer";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error: unknown) {
      if (!ownsDownload(request)) return;
      if (isTerminalDownloadFailure(error)) {
        const failure = previewFailure(error, version.version_number);
        setMediaRender({ phase: "idle" });
        setPreview((current) => current.phase === "ready" && current.version.version_id === version.version_id
          ? {
              ...current,
              availability: failure.availability,
              content: null,
              document: null,
              downloadable: false,
              text: null,
              objectUrl: null,
              message: failure.message,
            }
          : current);
        setDownloadError("");
      } else {
        setDownloadError("This verified version could not be prepared for download. The workspace was not changed.");
      }
    } finally {
      if (downloadRequest.current === request) {
        downloadRequest.current = null;
        setDownloadBusy(false);
      }
    }
  }

  async function exportLineage(
    detail: AgentArtifactDetail,
    version: AgentArtifactVersion,
  ): Promise<void> {
    if (exportBusy || exportRequest.current !== null) return;
    const exportArtifact = transport.exportAgentArtifact;
    if (exportArtifact === undefined) {
      setExportNotice("");
      setExportError("Lineage export is unavailable in this app transport. Preview and raw Download remain separate and usable.");
      return;
    }
    const request: ExportRequest = {
      artifactId: detail.artifact_id,
      controller: new AbortController(),
      scopeKey,
      transport,
      versionId: version.version_id,
    };
    exportRequest.current = request;
    setExportBusy(true);
    setExportError("");
    setExportNotice("");
    try {
      const exported = await exportArtifact(
        projectId,
        sessionId,
        detail.artifact_id,
        {
          expected_revision: detail.revision,
          version_id: version.version_id,
        },
        request.controller.signal,
      );
      if (!ownsExport(request)) return;
      assertArtifactExportMatches(exported, detail, version);
      if (typeof URL.createObjectURL !== "function") throw new Error("object_url_unavailable");
      const filename = `agent-artifact-${detail.artifact_id.slice(0, 8)}-v${version.version_number}-lineage.json`;
      if (!SAFE_EXPORT_FILENAME.test(filename)) throw new ArtifactExportMismatchError();
      const blob = new Blob([`${JSON.stringify(exported, null, 2)}\n`], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.rel = "noopener noreferrer";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setExportNotice(
        `Lineage JSON for v${version.version_number} was prepared locally. It contains sensitive metadata, but no artifact bytes or absolute workspace path.`,
      );
    } catch (error: unknown) {
      if (!ownsExport(request)) return;
      if (
        error instanceof TransportError
        && error.reasonCode === "agent_artifact_revision_conflict"
      ) {
        setExportError("This artifact changed in another view. Refresh its lineage before exporting.");
      } else if (isTerminalDownloadFailure(error)) {
        const failure = previewFailure(error, version.version_number);
        setMediaRender({ phase: "idle" });
        setPreview((current) => current.phase === "ready" && current.version.version_id === version.version_id
          ? {
              ...current,
              availability: failure.availability,
              content: null,
              document: null,
              downloadable: false,
              text: null,
              objectUrl: null,
              message: failure.message,
            }
          : current);
        setExportError("");
      } else {
        setExportError("The exact-readback lineage export could not be prepared. No artifact bytes were exported.");
      }
    } finally {
      if (exportRequest.current === request) {
        exportRequest.current = null;
        setExportBusy(false);
      }
    }
  }

  const selectedVersion = viewer.phase === "ready" && selectedVersionId !== null
    ? viewer.artifact.versions.find((version) => version.version_id === selectedVersionId) ?? null
    : null;
  const selectedIsLatest = viewer.phase === "ready" && selectedVersion !== null
    ? selectedVersion.version_id === viewer.artifact.latest_version.version_id
    : false;
  const comparisonVersion = viewer.phase === "ready" && comparisonVersionId !== null
    ? viewer.artifact.versions.find((version) => version.version_id === comparisonVersionId) ?? null
    : null;
  const comparisonPair = selectedVersion !== null
    && comparisonVersion !== null
    && selectedVersion.version_id !== comparisonVersion.version_id
    ? [...[selectedVersion, comparisonVersion]].sort((left, right) => left.version_number - right.version_number)
    : null;
  const canDownload = preview.phase === "ready" && preview.downloadable;
  const canExport = preview.phase === "ready"
    && preview.downloadable
    && transport.exportAgentArtifact !== undefined;
  const activeMediaPhase = preview.phase === "ready"
    && (preview.objectUrl !== null || (preview.version.preview_kind === "pdf" && preview.content !== null))
    && preview.version.preview_kind !== "text"
    && preview.version.preview_kind !== "download_only"
    && mediaRender.phase !== "idle"
    && mediaRender.versionId === preview.version.version_id
    && mediaRender.kind === preview.version.preview_kind
    ? mediaRender.phase
    : null;

  function setMediaPhase(
    version: AgentArtifactVersion,
    kind: MediaPreviewKind,
    phase: "loading" | "ready" | "error",
  ): void {
    setMediaRender((current) => (
      current.phase !== "idle"
      && current.versionId === version.version_id
      && current.kind === kind
        ? { phase, versionId: version.version_id, kind }
        : current
    ));
  }

  function openLifecycleDialog(artifact: AgentArtifact): void {
    setLifecycleNotice("");
    setLifecycleDialog({ artifact, busy: false, error: "", title: artifact.title });
  }

  function closeLifecycleDialog(): void {
    if (lifecycleDialog?.busy) return;
    setLifecycleDialog(null);
  }

  async function applyLifecycle(operation: LifecycleOperation): Promise<void> {
    const current = lifecycleDialog;
    if (current === null || current.busy) return;
    const title = current.title.trim();
    if (operation === "rename" && (title.length === 0 || Array.from(title).length > 120)) {
      setLifecycleDialog({
        ...current,
        error: "Enter a display name between 1 and 120 characters.",
      });
      return;
    }
    if (operation === "remove" && !userPresenceAvailable) {
      setLifecycleDialog({
        ...current,
        error: "Native confirmation is unavailable. The artifact remains Archived.",
      });
      return;
    }
    const controller = new AbortController();
    lifecycleRequest.current?.abort();
    lifecycleRequest.current = controller;
    setLifecycleDialog({ ...current, busy: true, error: "", title });
    try {
      if (operation === "remove") {
        await transport.removeAgentArtifact(
          projectId,
          sessionId,
          current.artifact.artifact_id,
          {
            expected_revision: current.artifact.revision,
            confirmation: "move_archived_artifact_record_to_removed",
          },
          controller.signal,
        );
      } else {
        await transport.updateAgentArtifact(
          projectId,
          sessionId,
          current.artifact.artifact_id,
          {
            expected_revision: current.artifact.revision,
            operation,
            ...(operation === "rename" ? { title } : {}),
          },
          controller.signal,
        );
      }
      if (
        controller.signal.aborted
        || requestContext.current.scopeKey !== scopeKey
        || requestContext.current.transport !== transport
        || lifecycleRequest.current !== controller
      ) return;
      setLifecycleDialog(null);
      setLifecycleNotice(operation === "rename"
        ? "Display name updated. The workspace path and version lineage were not changed."
        : operation === "archive"
          ? "Moved to Archived. The workspace file and every recorded version were kept."
          : operation === "restore"
            ? "Restored to Active."
            : operation === "recover"
              ? "Recovered to Archived. Restore it once more when you want it back in Active."
              : "Moved to Removed. The record is recoverable and no workspace file was deleted.");
      onRefresh();
    } catch (error) {
      if (
        controller.signal.aborted
        || requestContext.current.scopeKey !== scopeKey
        || requestContext.current.transport !== transport
        || lifecycleRequest.current !== controller
      ) return;
      setLifecycleDialog((state) => state?.artifact.artifact_id === current.artifact.artifact_id
        ? { ...state, busy: false, error: lifecycleFailure(error) }
        : state);
    } finally {
      if (lifecycleRequest.current === controller) lifecycleRequest.current = null;
    }
  }

  return (
    <section aria-labelledby="agent-artifacts-title" className="agent-artifacts">
      <header className="agent-artifacts__head">
        <span>
          <small>Workspace output</small>
          <strong id="agent-artifacts-title">Artifacts{counts !== null && counts.total > 0 ? ` · ${counts.total}` : ""}</strong>
        </span>
        <button className="button button--ghost" disabled={loading} onClick={onRefresh} type="button">
          {loading ? "Checking…" : "Refresh"}
        </button>
      </header>
      <div aria-label="Artifact lifecycle views" className="agent-artifacts__views" role="tablist">
        {LIFECYCLE_VIEWS.map((candidate) => (
          <button
            aria-label={`${candidate.label} ${counts === null ? "count unavailable" : counts[candidate.value]}`}
            aria-controls="agent-artifacts-lifecycle-panel"
            aria-selected={view === candidate.value}
            className="agent-artifacts__view"
            data-active={view === candidate.value ? "true" : "false"}
            id={`agent-artifacts-view-${candidate.value}`}
            key={candidate.value}
            onClick={() => onViewChange(candidate.value)}
            role="tab"
            type="button"
          >
            <span>{candidate.label}</span>
            <strong aria-label={counts === null ? `${candidate.label} count unavailable` : undefined}>
              {counts === null ? "—" : counts[candidate.value]}
            </strong>
          </button>
        ))}
      </div>
      <div aria-labelledby={`agent-artifacts-view-${view}`} id="agent-artifacts-lifecycle-panel" role="tabpanel">
        {error ? <p className="agent-artifacts__message" role="alert">{error}</p> : artifacts.length === 0 ? (
          <p className="agent-artifacts__message" role="status">
            {loading
              ? `Checking ${view} artifacts…`
              : view === "active"
                ? "No verified workspace output is recorded in Active. A model statement alone is not a created file; reviewed writes will appear here."
                : view === "archived"
                  ? "No archived artifacts. Archiving hides a record from Active without changing its workspace file or version history."
                  : "No removed artifact records. Removed records stay recoverable and their workspace files are never deleted by this action."}
          </p>
        ) : (
          <div className="agent-artifacts__list">
          {visibleArtifacts.map((artifact) => (
            <article className="agent-artifacts__card" data-kind={artifact.kind} data-lifecycle={artifact.lifecycle_state} key={artifact.artifact_id}>
              <div className="agent-artifacts__type">{artifact.kind}</div>
              <div className="agent-artifacts__copy">
                <span className="agent-artifacts__title-line">
                  <strong title={artifact.title}>{artifact.title}</strong>
                  <small>{artifact.lifecycle_state}</small>
                </span>
                <code title={artifact.path}>{artifact.path}</code>
                <span>
                  {provenance(artifact)} · v{artifact.version_count} · rev {artifact.revision} · {bytes(artifact.latest_version.byte_size)}
                </span>
              </div>
              <div className="agent-artifacts__card-actions">
                {typeof artifact.latest_version.source_turn_id === "string" && onOpenSourceTurn !== undefined && (
                  <button
                    aria-label={`Go to producing turn for ${artifact.title}`}
                    className="button button--ghost"
                    onClick={() => {
                      const turnId = artifact.latest_version.source_turn_id;
                      if (typeof turnId !== "string") return;
                      setSourceTurnNotice(onOpenSourceTurn(turnId)
                        ? ""
                        : "The producing turn is recorded, but it is not available in the loaded chat history.");
                    }}
                    type="button"
                  >Source turn</button>
                )}
                {artifact.lifecycle_state !== "removed" && onCaptureCurrent !== undefined && ["stale", "missing", "malformed"].includes(artifact.availability) && (
                  <button
                    aria-label={`Review current workspace file for ${artifact.title}`}
                    className="button button--ghost"
                    onClick={() => onCaptureCurrent(artifact.path)}
                    type="button"
                  >Review current</button>
                )}
                {artifact.lifecycle_state !== "removed" && (
                  <button
                    aria-label={`Preview ${artifact.title}`}
                    className="button button--ghost"
                    onClick={() => openViewer(artifact)}
                    type="button"
                  >Preview</button>
                )}
                <button
                  aria-label={`Manage ${artifact.title}`}
                  className="button button--ghost"
                  onClick={() => openLifecycleDialog(artifact)}
                  type="button"
                >Manage</button>
              </div>
            </article>
          ))}
          </div>
        )}
        <BoundedListPager label="Artifact pages" page={artifactPage} />
        {counts !== null && (
          <div className="agent-artifacts__server-page" aria-live="polite">
            <span>{artifacts.length} of {counts[view]} {view} artifacts loaded</span>
            {pageError && <span role="alert">{pageError}</span>}
            {canLoadMore && !pageError && onLoadMore !== undefined && (
              <button
                className="button button--ghost"
                disabled={pageLoading}
                onClick={onLoadMore}
                type="button"
              >{pageLoading ? "Loading…" : "Load more artifacts"}</button>
            )}
            {pageError && (
              <button className="button button--ghost" onClick={onRefresh} type="button">
                Reload artifacts
              </button>
            )}
          </div>
        )}
      </div>
      {sourceTurnNotice && <p className="agent-artifacts__message" role="status">{sourceTurnNotice}</p>}
      {lifecycleNotice && <p className="agent-artifacts__message agent-artifacts__message--success" role="status">{lifecycleNotice}</p>}

      <Dialog
        description="Lifecycle actions change this saved artifact record only. They never rename, overwrite, or delete the workspace file or its immutable version lineage."
        initialFocusRef={renameRef}
        onClose={closeLifecycleDialog}
        open={lifecycleDialog !== null}
        title={lifecycleDialog === null ? "Manage artifact" : `Manage ${lifecycleDialog.artifact.title}`}
      >
        {lifecycleDialog !== null && (
          <div className="agent-artifacts__manage">
            <div className="agent-artifacts__manage-summary">
              <span data-lifecycle={lifecycleDialog.artifact.lifecycle_state}>{lifecycleDialog.artifact.lifecycle_state}</span>
              <code>{lifecycleDialog.artifact.path}</code>
              <small>Revision {lifecycleDialog.artifact.revision} · {lifecycleDialog.artifact.version_count} immutable {lifecycleDialog.artifact.version_count === 1 ? "version" : "versions"}</small>
            </div>
            {lifecycleDialog.artifact.lifecycle_state !== "removed" && (
              <div className="agent-artifacts__rename">
                <label htmlFor="agent-artifact-display-name">Display name</label>
                <input
                  autoComplete="off"
                  disabled={lifecycleDialog.busy}
                  id="agent-artifact-display-name"
                  maxLength={120}
                  onChange={(event) => setLifecycleDialog((state) => state === null
                    ? null
                    : { ...state, error: "", title: event.target.value })}
                  ref={renameRef}
                  value={lifecycleDialog.title}
                />
                <small>The recorded relative path stays {lifecycleDialog.artifact.path}.</small>
                <button
                  className="button button--ghost"
                  disabled={lifecycleDialog.busy || lifecycleDialog.title.trim() === lifecycleDialog.artifact.title}
                  onClick={() => void applyLifecycle("rename")}
                  type="button"
                >{lifecycleDialog.busy ? "Applying…" : "Save display name"}</button>
              </div>
            )}
            <div className="agent-artifacts__manage-actions">
              {lifecycleDialog.artifact.lifecycle_state === "active" && (
                <button className="button button--ghost" disabled={lifecycleDialog.busy} onClick={() => void applyLifecycle("archive")} type="button">
                  Archive record
                </button>
              )}
              {lifecycleDialog.artifact.lifecycle_state === "archived" && (
                <>
                  <button className="button button--primary" disabled={lifecycleDialog.busy} onClick={() => void applyLifecycle("restore")} type="button">
                    Restore to Active
                  </button>
                  <button
                    className="button button--danger-ghost"
                    disabled={lifecycleDialog.busy || !userPresenceAvailable}
                    onClick={() => void applyLifecycle("remove")}
                    type="button"
                  >Move record to Removed</button>
                </>
              )}
              {lifecycleDialog.artifact.lifecycle_state === "removed" && (
                <button className="button button--primary" disabled={lifecycleDialog.busy} onClick={() => void applyLifecycle("recover")} type="button">
                  Recover to Archived
                </button>
              )}
            </div>
            {lifecycleDialog.artifact.lifecycle_state === "archived" && (
              <p className="agent-artifacts__manage-note" data-available={userPresenceAvailable ? "true" : "false"}>
                {userPresenceAvailable
                  ? "Moving this record to Removed needs a separate native confirmation. It remains recoverable, and its workspace file is untouched."
                  : "Moving to Removed is disabled because native confirmation is unavailable. Restore and rename remain available."}
              </p>
            )}
            {lifecycleDialog.error && <p className="agent-artifacts__manage-error" role="alert">{lifecycleDialog.error}</p>}
            <button className="button button--ghost" disabled={lifecycleDialog.busy} onClick={closeLifecycleDialog} type="button">Close</button>
          </div>
        )}
      </Dialog>

      {viewer.phase !== "closed" && viewerScope === scopeKey && (
        <div className="agent-artifacts__backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeViewer();
        }}>
          <section aria-labelledby="agent-artifact-viewer-title" aria-modal="true" className="agent-artifacts__viewer" ref={viewerRef} role="dialog">
            <header>
              <div>
                <small>Artifact viewer</small>
                <h2 id="agent-artifact-viewer-title">{viewer.artifact.title}</h2>
                <code>{viewer.artifact.path}</code>
              </div>
              <div className="agent-artifacts__viewer-actions">
                {viewer.phase === "ready" && viewer.artifact.version_count > 1 && selectedVersionId !== null && (
                  <label className="agent-artifacts__version-select">
                    <span>Version</span>
                    <select
                      aria-label="Artifact version"
                      onChange={(event) => {
                        const version = viewer.artifact.versions.find((candidate) => candidate.version_id === event.target.value);
                        if (version === undefined) return;
                        cancelDownload();
                        cancelExport();
                        setDownloadError("");
                        setExportError("");
                        setExportNotice("");
                        setMarkdownMode("preview");
                        setPreview({ phase: "loading", version });
                        setMediaRender({ phase: "idle" });
                        setImageZoom(1);
                        setSelectedVersionId(version.version_id);
                        setComparisonVersionId((current) => (
                          current !== null && current !== version.version_id
                            ? current
                            : viewer.artifact.versions.find((candidate) => candidate.version_id !== version.version_id)?.version_id ?? null
                        ));
                      }}
                      value={selectedVersionId}
                    >
                      {[...viewer.artifact.versions].reverse().map((version) => (
                        <option key={version.version_id} value={version.version_id}>
                          v{version.version_number} · {bytes(version.byte_size)} · {versionProvenance(version)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button aria-label="Close artifact viewer" className="button button--ghost" onClick={closeViewer} ref={closeRef} type="button">Close</button>
              </div>
            </header>
            <div className="agent-artifacts__viewer-body">
              {viewer.phase === "loading" && <p role="status">Loading recorded artifact lineage…</p>}
              {viewer.phase === "error" && <p role="alert">{viewer.message}</p>}
              {viewer.phase === "ready" && selectedVersion !== null && (
                <div className="agent-artifacts__version-summary">
                  <span>v{selectedVersion.version_number} of {viewer.artifact.version_count}</span>
                  <span>{versionProvenance(selectedVersion)}</span>
                  <span>{bytes(selectedVersion.byte_size)}</span>
                  <code title={selectedVersion.sha256}>SHA-256 {selectedVersion.sha256.slice(0, 12)}…</code>
                </div>
              )}
              {viewer.phase === "ready" && selectedVersion !== null && viewer.artifact.version_count > 1 && (
                <div className="agent-artifacts__comparison-controls">
                  <button
                    aria-controls="agent-artifact-version-comparison"
                    aria-expanded={comparisonOpen}
                    className="button button--ghost"
                    onClick={() => setComparisonOpen((current) => !current)}
                    type="button"
                  >{comparisonOpen ? "Hide comparison" : "Compare versions"}</button>
                  {comparisonOpen && (
                    <label>
                      <span>Compare selected v{selectedVersion.version_number} with</span>
                      <select
                        aria-label="Comparison artifact version"
                        onChange={(event) => setComparisonVersionId(event.target.value)}
                        value={comparisonVersionId ?? ""}
                      >
                        {viewer.artifact.versions
                          .filter((version) => version.version_id !== selectedVersion.version_id)
                          .map((version) => (
                            <option key={version.version_id} value={version.version_id}>v{version.version_number}</option>
                          ))}
                      </select>
                    </label>
                  )}
                </div>
              )}
              {comparisonOpen && comparisonPair !== null && (
                <section aria-label="Artifact version metadata comparison" className="agent-artifacts__comparison" id="agent-artifact-version-comparison">
                  <header>
                    <span>
                      <strong>Recorded lineage comparison</strong>
                      <small>v{comparisonPair[0].version_number} → v{comparisonPair[1].version_number}</small>
                    </span>
                    <span data-changed={comparisonPair[0].sha256 === comparisonPair[1].sha256 ? "false" : "true"}>
                      {comparisonPair[0].sha256 === comparisonPair[1].sha256 ? "Same digest" : "Digest changed"}
                    </span>
                  </header>
                  <dl>
                    <div>
                      <dt>Workspace path</dt>
                      <dd><code>{comparisonPair[0].path}</code><span aria-hidden="true">→</span><code>{comparisonPair[1].path}</code></dd>
                    </div>
                    <div>
                      <dt>Recorded size</dt>
                      <dd>{bytes(comparisonPair[0].byte_size)} → {bytes(comparisonPair[1].byte_size)} <span>({byteDelta(comparisonPair[1].byte_size - comparisonPair[0].byte_size)})</span></dd>
                    </div>
                    <div>
                      <dt>Evidence source</dt>
                      <dd>{versionSource(comparisonPair[0])} → {versionSource(comparisonPair[1])}</dd>
                    </div>
                    <div>
                      <dt>Provenance</dt>
                      <dd>{versionProvenance(comparisonPair[0])} → {versionProvenance(comparisonPair[1])}</dd>
                    </div>
                    <div>
                      <dt>SHA-256</dt>
                      <dd><code title={comparisonPair[0].sha256}>{comparisonPair[0].sha256.slice(0, 12)}…</code><span aria-hidden="true">→</span><code title={comparisonPair[1].sha256}>{comparisonPair[1].sha256.slice(0, 12)}…</code></dd>
                    </div>
                  </dl>
                  <p>Metadata comparison only. Historical bytes are not copied into app storage, so this does not claim a content diff. Each preview or download still requires the exact recorded digest to match the current workspace file.</p>
                </section>
              )}
              {viewer.phase === "ready" && selectedVersion !== null && !selectedIsLatest && (
                <p className="agent-artifacts__history-note">
                  Historical bytes are not copied into the app. Preview and download revalidate recorded v{selectedVersion.version_number} against the current workspace file.
                </p>
              )}
              {preview.phase === "loading" && <p role="status">Revalidating v{preview.version.version_number} against the exact workspace bytes…</p>}
              {preview.phase === "ready" && preview.availability !== "available" && preview.availability !== "unchecked" && (
                <p className="agent-artifacts__warning" role="alert">
                  {preview.message || availabilityMessage(preview.availability, preview.version.version_number)}
                </p>
              )}
              {preview.phase === "ready" && preview.availability === "unchecked" && (
                <p className="agent-artifacts__history-note">
                  {availabilityMessage(preview.availability, preview.version.version_number)} Downloading will perform the exact digest check.
                </p>
              )}
              {preview.phase === "ready" && (preview.availability === "available" || preview.availability === "unchecked") && preview.version.preview_kind === "download_only" && (
                <p>This format stays inert in the app. Download the digest-verified version to open it with a trusted local application.</p>
              )}
              {preview.phase === "ready" && (preview.availability === "available" || preview.availability === "unchecked") && preview.version.preview_kind === "text" && preview.version.byte_size > MAX_INLINE_TEXT_BYTES && (
                <p>This text artifact is larger than the 1 MB inline-view limit. Download the verified version instead.</p>
              )}
              {viewer.phase === "ready" && preview.phase === "ready" && preview.text !== null && viewer.artifact.kind === "markdown" && (
                <>
                  <div aria-label="Markdown view" className="agent-artifacts__view-switch" role="group">
                    <button
                      aria-pressed={markdownMode === "preview"}
                      className="button button--ghost"
                      onClick={() => setMarkdownMode("preview")}
                      type="button"
                    >Preview</button>
                    <button
                      aria-pressed={markdownMode === "source"}
                      className="button button--ghost"
                      onClick={() => setMarkdownMode("source")}
                      type="button"
                    >Source</button>
                    <span>Verified bytes · links and remote images stay inert</span>
                  </div>
                  {markdownMode === "preview" ? (
                    <article aria-label="Rendered Markdown artifact" className="agent-artifacts__markdown-preview">
                      <AgentMessageContent content={preview.text} linkPolicy="inert" variant="artifact" />
                    </article>
                  ) : (
                    <pre aria-label="Markdown source" className="agent-artifacts__text-preview">{preview.text}</pre>
                  )}
                </>
              )}
              {viewer.phase === "ready" && preview.phase === "ready" && preview.text !== null && viewer.artifact.kind !== "markdown" && (
                <pre className="agent-artifacts__text-preview">{preview.text}</pre>
              )}
              {viewer.phase === "ready" && preview.phase === "ready" && preview.objectUrl !== null && preview.version.preview_kind === "image" && (
                <section
                  aria-label={`Image preview of ${viewer.artifact.title} v${preview.version.version_number}`}
                  className="agent-artifacts__media-preview"
                  data-kind="image"
                  data-state={activeMediaPhase ?? "loading"}
                >
                  <header className="agent-artifacts__media-toolbar">
                    <span>
                      <strong>Image preview</strong>
                      <small>Digest-verified local bytes · no remote source</small>
                    </span>
                    <div aria-label="Image zoom" role="group">
                      <button
                        aria-label="Zoom out image"
                        className="button button--ghost"
                        disabled={activeMediaPhase !== "ready" || imageZoom <= MIN_IMAGE_ZOOM}
                        onClick={() => setImageZoom((current) => Math.max(MIN_IMAGE_ZOOM, current - IMAGE_ZOOM_STEP))}
                        type="button"
                      >−</button>
                      <button
                        aria-label="Fit image to viewer"
                        className="button button--ghost"
                        disabled={activeMediaPhase !== "ready" || imageZoom === 1}
                        onClick={() => setImageZoom(1)}
                        type="button"
                      >Fit · {Math.round(imageZoom * 100)}%</button>
                      <button
                        aria-label="Zoom in image"
                        className="button button--ghost"
                        disabled={activeMediaPhase !== "ready" || imageZoom >= MAX_IMAGE_ZOOM}
                        onClick={() => setImageZoom((current) => Math.min(MAX_IMAGE_ZOOM, current + IMAGE_ZOOM_STEP))}
                        type="button"
                      >+</button>
                    </div>
                  </header>
                  <div className="agent-artifacts__media-stage">
                    {activeMediaPhase === "loading" && (
                      <p className="agent-artifacts__media-state" role="status">Decoding the verified image preview…</p>
                    )}
                    {activeMediaPhase === "error" && (
                      <p className="agent-artifacts__media-state agent-artifacts__media-state--error" role="alert">
                        This digest-verified image could not be decoded in the viewer. It was not substituted or sent anywhere. Download it explicitly to inspect it with a trusted local application.
                      </p>
                    )}
                    <img
                      alt={`Preview of ${viewer.artifact.title} v${preview.version.version_number}`}
                      className="agent-artifacts__image-preview"
                      data-state={activeMediaPhase ?? "loading"}
                      draggable={false}
                      hidden={activeMediaPhase === "error"}
                      onError={() => setMediaPhase(preview.version, "image", "error")}
                      onLoad={() => setMediaPhase(preview.version, "image", "ready")}
                      src={preview.objectUrl}
                      style={{ width: `${Math.round(imageZoom * 100)}%` }}
                    />
                  </div>
                </section>
              )}
              {viewer.phase === "ready" && preview.phase === "ready" && preview.content !== null && preview.version.preview_kind === "pdf" && (
                <Suspense fallback={<p role="status">Loading the local PDF renderer…</p>}>
                  <AgentPdfPreview
                    blob={preview.content.blob}
                    key={preview.version.version_id}
                    onStateChange={(phase) => setMediaPhase(preview.version, "pdf", phase)}
                    title={viewer.artifact.title}
                    versionNumber={preview.version.version_number}
                  />
                </Suspense>
              )}
              {viewer.phase === "ready" && preview.phase === "ready" && preview.document !== null && preview.version.preview_kind === "document" && (
                <AgentDocumentPreview
                  key={preview.document.version_id}
                  preview={preview.document}
                  title={viewer.artifact.title}
                  versionNumber={preview.version.version_number}
                />
              )}
              {downloadError && <p className="agent-artifacts__download-error" role="alert">{downloadError}</p>}
              {exportError && <p className="agent-artifacts__download-error" role="alert">{exportError}</p>}
              {exportNotice && <p className="agent-artifacts__export-notice" role="status">{exportNotice}</p>}
            </div>
            {viewer.phase === "ready" && selectedVersion !== null && (
              <footer>
                <span data-state={activeMediaPhase === "error" ? "unavailable" : preview.phase === "ready" ? preview.availability : "checking"}>
                  {activeMediaPhase === "error" ? "preview failed" : preview.phase === "ready" ? preview.availability : "checking"} · {bytes(selectedVersion.byte_size)} · v{selectedVersion.version_number}
                </span>
                <div>
                  {onOpenFile !== undefined && selectedIsLatest && selectedVersion.preview_kind === "text" && (
                    <button className="button button--ghost" onClick={() => {
                      onOpenFile(viewer.artifact.path);
                      closeViewer();
                    }} type="button">Open current file</button>
                  )}
                  {onRevealFile !== undefined && selectedIsLatest && (
                    <button className="button button--ghost" onClick={() => {
                      onRevealFile(viewer.artifact.path);
                      closeViewer();
                    }} type="button">Reveal in files</button>
                  )}
                  {onReviewChanges !== undefined && selectedIsLatest && ["reviewed_write", "reviewed_move"].includes(selectedVersion.provenance) && (
                    <button className="button button--ghost" onClick={() => {
                      onReviewChanges(viewer.artifact.path);
                      closeViewer();
                    }} type="button">Review changes</button>
                  )}
                  {onCaptureCurrent !== undefined && selectedIsLatest && preview.phase === "ready" && ["stale", "missing", "malformed", "unavailable"].includes(preview.availability) && (
                    <button className="button button--ghost" onClick={() => {
                      onCaptureCurrent(viewer.artifact.path);
                      closeViewer();
                    }} type="button">Review current as new version</button>
                  )}
                  <button
                    className="button button--ghost"
                    disabled={!canExport || exportBusy || downloadBusy}
                    onClick={() => void exportLineage(viewer.artifact, selectedVersion)}
                    title={transport.exportAgentArtifact === undefined
                      ? "Lineage export is unavailable in this app transport."
                      : "Export sensitive lineage metadata only; artifact bytes remain a separate Download action."}
                    type="button"
                  >{exportBusy ? "Exporting…" : `Export lineage v${selectedVersion.version_number}`}</button>
                  <button className="button button--primary" disabled={!canDownload || downloadBusy || exportBusy} onClick={() => void download(viewer.artifact, selectedVersion)} type="button">
                    {downloadBusy ? "Preparing…" : `Download v${selectedVersion.version_number}`}
                  </button>
                </div>
              </footer>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
