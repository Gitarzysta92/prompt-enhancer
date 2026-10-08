import { useEffect, useRef, useState } from "react";

import type {
  AgentArtifactCapturePreview,
  AgentArtifactDetail,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Dialog } from "../../shared/ui/Dialog";
import "./AgentArtifactCaptureDialog.css";

type ArtifactCaptureTransport = Pick<
  PromptEnhancerTransport,
  "previewAgentArtifactCapture" | "captureAgentArtifact"
>;

function safeWorkspacePath(value: string): boolean {
  return value.length > 0
    && value.length <= 1024
    && !value.startsWith("/")
    && !value.includes("\\")
    && !value.includes("\0")
    && !/^[A-Za-z]:/u.test(value)
    && value.split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

function captureError(error: unknown): string {
  if (error instanceof TransportError) {
    if (error.reasonCode === "agent_artifact_revision_changed") {
      return "The file changed after review. Nothing was captured; review the current revision again.";
    }
    if (error.reasonCode === "agent_artifact_missing") {
      return "That workspace file no longer exists. Nothing was captured.";
    }
    if (error.reasonCode === "agent_artifact_too_large" || error.status === 413) {
      return "This file exceeds the 24 MB artifact limit and was not captured.";
    }
    if (error.status === 403) {
      return "Native confirmation was declined, expired, or is unavailable. Nothing was captured.";
    }
    if (error.status === 409) {
      return "The reviewed file or chat changed. Nothing was captured; create a fresh review.";
    }
    if (error.status === 404) return "That retained chat or workspace file is no longer available.";
    if (error.status === 200) return "The local service returned an invalid capture review. Nothing was captured.";
  }
  return "The generated output could not be reviewed. Nothing was captured.";
}

/** Only these receipt codes prove the capture service did not reach storage. */
function definiteCaptureError(error: unknown): string | null {
  if (!(error instanceof TransportError)) return null;
  if (error.reasonCode === "agent_artifact_revision_changed") {
    return "The file changed after review. Nothing was captured; review the current revision again.";
  }
  if (error.reasonCode === "agent_artifact_missing") {
    return "That workspace file no longer exists. Nothing was captured.";
  }
  if (error.reasonCode === "agent_artifact_too_large") {
    return "This file exceeds the 24 MB artifact limit and was not captured.";
  }
  if (error.reasonCode === "native_confirmation_declined_before_dispatch") {
    return "Native confirmation was declined. Nothing was captured.";
  }
  return null;
}

function previewLabel(preview: AgentArtifactCapturePreview): string {
  if (preview.preview_kind === "document") return "Inert document viewer";
  if (preview.preview_kind === "download_only") return "Download only";
  if (preview.preview_kind === "pdf") return "Local PDF viewer";
  if (preview.preview_kind === "image") return "Local image viewer";
  return preview.kind === "markdown" ? "Rendered Markdown and source" : "Bounded text viewer";
}

export function AgentArtifactCaptureDialog({
  initialPath,
  onCaptured,
  onCaptureUncertain,
  onClose,
  open,
  projectId,
  sessionId,
  transport,
  userPresenceAvailable,
}: {
  initialPath: string;
  onCaptured: (artifact: AgentArtifactDetail) => void;
  /** Requests one read-only list refresh; it does not claim a capture succeeded. */
  onCaptureUncertain?: () => void;
  onClose: () => void;
  open: boolean;
  projectId: string;
  sessionId: string;
  transport: ArtifactCaptureTransport;
  userPresenceAvailable: boolean;
}) {
  const [path, setPath] = useState(initialPath);
  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<AgentArtifactCapturePreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "capture" | null>(null);
  const [error, setError] = useState("");
  const [captureUncertain, setCaptureUncertain] = useState(false);
  const pathRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const requestRevision = useRef(0);

  useEffect(() => {
    requestRevision.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;
    setPath(initialPath);
    setTitle("");
    setPreview(null);
    setBusy(null);
    setError("");
    setCaptureUncertain(false);
  }, [initialPath, open, projectId, sessionId, transport]);

  useEffect(() => () => requestRef.current?.abort(), []);

  function changePath(value: string) {
    requestRevision.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;
    setPath(value);
    setPreview(null);
    setBusy(null);
    setError("");
    setCaptureUncertain(false);
  }

  function changeTitle(value: string) {
    requestRevision.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;
    setTitle(value);
    setPreview(null);
    setBusy(null);
    setError("");
    setCaptureUncertain(false);
  }

  async function inspect() {
    const inspectedPath = path.trim();
    const inspectedTitle = title.trim();
    if (!safeWorkspacePath(inspectedPath) || inspectedTitle.length > 120) return;
    const revision = ++requestRevision.current;
    const controller = new AbortController();
    requestRef.current = controller;
    setPreview(null);
    setError("");
    setBusy("preview");
    try {
      const result = await transport.previewAgentArtifactCapture(
        projectId,
        sessionId,
        {
          path: inspectedPath,
          ...(inspectedTitle ? { title: inspectedTitle } : {}),
        },
        controller.signal,
      );
      if (controller.signal.aborted || revision !== requestRevision.current) return;
      setPath(inspectedPath);
      setTitle(inspectedTitle);
      setPreview(result);
    } catch (caught) {
      if (!controller.signal.aborted && revision === requestRevision.current) {
        setError(captureError(caught));
      }
    } finally {
      if (!controller.signal.aborted && revision === requestRevision.current) {
        setBusy(null);
        requestRef.current = null;
      }
    }
  }

  async function capture() {
    // ``busy`` is React state, so also use the controller ref to reject a
    // same-tick double click before the render that disables the button.
    if (preview === null || !userPresenceAvailable || captureUncertain || busy !== null || requestRef.current !== null) return;
    const revision = ++requestRevision.current;
    const controller = new AbortController();
    requestRef.current = controller;
    setError("");
    setBusy("capture");
    let result: AgentArtifactDetail;
    try {
      result = await transport.captureAgentArtifact(
        projectId,
        sessionId,
        {
          path: preview.path,
          title: preview.title,
          expected_sha256: preview.sha256,
          expected_byte_size: preview.byte_size,
        },
        controller.signal,
      );
    } catch (caught) {
      if (!controller.signal.aborted && revision === requestRevision.current) {
        const definite = definiteCaptureError(caught);
        if (caught instanceof TransportError && caught.reasonCode === "agent_artifact_revision_changed") {
          setPreview(null);
        }
        if (definite !== null) {
          setError(definite);
        } else {
          setCaptureUncertain(true);
          setError("The capture may have completed, but confirmation was not received. Do not submit it again; close this dialog and inspect saved artifacts.");
          onCaptureUncertain?.();
        }
      }
      return;
    } finally {
      if (!controller.signal.aborted && revision === requestRevision.current) {
        setBusy(null);
        requestRef.current = null;
      }
    }
    if (controller.signal.aborted || revision !== requestRevision.current) return;
    // The receipt was parsed and scope-checked above. UI callback failures are
    // deliberately not reclassified as a transport-ambiguous mutation.
    onCaptured(result);
    onClose();
  }

  const pathValid = safeWorkspacePath(path.trim());
  const titleValid = title.trim().length <= 120;
  return (
    <Dialog
      description="Register an existing workspace file as a version-bound chat artifact. Review reads the file locally and returns metadata only; adding it requires a separate native confirmation."
      footer={(
        <>
          <button className="button button--ghost" disabled={busy !== null} onClick={onClose} type="button">{captureUncertain ? "Close and inspect saved artifacts" : "Cancel"}</button>
          {preview === null ? (
            <button className="button button--primary" disabled={!pathValid || !titleValid || busy !== null} onClick={() => void inspect()} type="button">
              {busy === "preview" ? "Reviewing…" : "Review output"}
            </button>
          ) : (
            <button className="button button--primary" disabled={busy !== null || captureUncertain || !userPresenceAvailable} onClick={() => void capture()} type="button">
              {busy === "capture" ? "Waiting for confirmation…" : "Add verified output"}
            </button>
          )}
        </>
      )}
      initialFocusRef={pathRef}
      onClose={busy === null ? onClose : () => undefined}
      open={open}
      title="Add generated output"
    >
      <div className="agent-artifact-capture">
        <label>
          Workspace-relative file path
          <input
            aria-invalid={path.length > 0 && !pathValid ? "true" : undefined}
            autoComplete="off"
            disabled={busy !== null}
            onChange={(event) => changePath(event.currentTarget.value)}
            placeholder="reports/result.pdf"
            ref={pathRef}
            spellCheck={false}
            value={path}
          />
        </label>
        <label>
          Display title <span>optional</span>
          <input
            aria-invalid={!titleValid ? "true" : undefined}
            autoComplete="off"
            disabled={busy !== null}
            maxLength={120}
            onChange={(event) => changeTitle(event.currentTarget.value)}
            placeholder="Uses the file name"
            value={title}
          />
        </label>
        {!pathValid && path.length > 0 && <p className="agent-artifact-capture__hint">Use a file path inside this workspace without a drive, leading slash, backslash, or parent traversal.</p>}
        {preview && (
          <section aria-label="Generated output review" className="agent-artifact-capture__review">
            <header>
              <span data-kind={preview.kind}>{preview.kind}</span>
              <strong>{preview.title}</strong>
            </header>
            <dl>
              <div><dt>Exact path</dt><dd><code>{preview.path}</code></dd></div>
              <div><dt>Viewer</dt><dd>{previewLabel(preview)}</dd></div>
              <div><dt>Revision</dt><dd><code>{preview.sha256.slice(0, 12)}</code></dd></div>
              <div><dt>Size</dt><dd>{preview.byte_size.toLocaleString()} bytes</dd></div>
            </dl>
            <p>No file bytes are included in this review. The capture rechecks this digest and fails if the file changes.</p>
            {!userPresenceAvailable && <p role="status">Adding this output is unavailable because native user-presence confirmation is not available in this window.</p>}
          </section>
        )}
        {error && <p className="agent-artifact-capture__error" role="alert">{error}</p>}
      </div>
    </Dialog>
  );
}
