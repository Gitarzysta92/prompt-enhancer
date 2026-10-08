import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { QualityMetricProfile, QualitySnapshotKind } from "./qualityProfile";
import {
  browserShareCardRuntime,
  createSafeShareSnapshot,
  type ShareCardAsset,
  type ShareCardRuntime,
} from "./qualityShareCard";
import "./QualityProfileView.css";

const SAFE_METRIC_LABELS = new Set([
  "Goal cue coverage",
  "Expected constraint cues",
  "Checkability cue coverage",
  "Expected output-detail cues",
  "Choice-marker density",
  "Requirement-to-action traceability",
  "Plan-state accounting",
  "Decision-rationale coverage",
  "Scoped consistency candidates",
  "Conversation-loop closure",
  "Task definition coverage",
  "Problem evidence quality",
  "Context cue checks",
  "Constraint precision candidates",
  "Acceptance testability cues",
  "Deliverable contract cues",
  "Ambiguity-resolution candidates",
  "Clarification yield candidates",
  "Exploration-to-plan conversion",
  "Scope-change acknowledgement",
  "Rework-candidate rate",
  "Requirement-to-plan coverage",
  "Hypothesis-to-test linkage",
  "Open-loop closure candidates",
  "Agent claim grounding",
  "Verification-strategy coverage",
  "First-pass verification",
  "Verified requirement coverage",
]);

interface ProfileShareDialogProps {
  profile: QualityMetricProfile;
  snapshotKind: QualitySnapshotKind;
  onClose: () => void;
  runtime?: ShareCardRuntime;
}

function shareOwnerIdentity(
  profile: QualityMetricProfile,
  snapshotKind: QualitySnapshotKind,
): string {
  try {
    return JSON.stringify(createSafeShareSnapshot(profile, snapshotKind));
  } catch {
    const snapshot = snapshotKind === "initial" ? profile.initial : profile.latest;
    return JSON.stringify({
      kind: profile.kind,
      snapshotKind,
      integrity: snapshot.integrity,
      pack: snapshot.metricPackVersion,
    });
  }
}

function safeSnapshot(
  profile: QualityMetricProfile,
  snapshotKind: QualitySnapshotKind,
) {
  const snapshot = createSafeShareSnapshot(profile, snapshotKind);
  if (
    snapshot.metrics.length === 0 ||
    snapshot.metrics.some((metric) => !SAFE_METRIC_LABELS.has(metric.label))
  ) {
    throw new TypeError("Share metric definition is not allowlisted.");
  }
  return snapshot;
}

function isSafeAsset(
  asset: ShareCardAsset,
  profile: QualityMetricProfile,
): boolean {
  const expectedFilename =
    profile.kind === "prompt"
      ? "prompt-enhancer-prompt-profile.png"
      : "prompt-enhancer-logic-profile.png";
  return (
    asset.blob instanceof Blob &&
    asset.blob.type === "image/png" &&
    asset.blob.size > 0 &&
    asset.blob.size <= 10_000_000 &&
    asset.previewUrl.startsWith("blob:") &&
    asset.filename === expectedFilename
  );
}

export function ProfileShareDialog(props: ProfileShareDialogProps) {
  const ownerIdentity = shareOwnerIdentity(props.profile, props.snapshotKind);
  return <ProfileShareDialogOwned key={ownerIdentity} {...props} />;
}

function ProfileShareDialogOwned({
  profile,
  snapshotKind,
  onClose,
  runtime = browserShareCardRuntime,
}: ProfileShareDialogProps) {
  const [asset, setAsset] = useState<ShareCardAsset | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingAction, setPendingAction] = useState<"copy" | "share" | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const assetRef = useRef<ShareCardAsset | null>(asset);
  assetRef.current = asset;
  const mountedRef = useRef(true);
  const openRef = useRef(true);
  const closeNotifiedRef = useRef(false);
  const renderEpochRef = useRef(0);
  const revokedAssetsRef = useRef(new WeakSet<object>());
  const initialRuntimeRef = useRef(runtime);
  const onCloseRef = useRef(onClose);
  const ownsRuntime = runtime === initialRuntimeRef.current;
  const ownsRuntimeRef = useRef(ownsRuntime);
  ownsRuntimeRef.current = ownsRuntime;
  const ownerIdentity = shareOwnerIdentity(profile, snapshotKind);
  const id = useId();
  const titleId = `${id}-share-profile-title`;

  function revokeOnce(nextAsset: ShareCardAsset) {
    if (revokedAssetsRef.current.has(nextAsset)) return;
    revokedAssetsRef.current.add(nextAsset);
    try {
      initialRuntimeRef.current.revoke(nextAsset);
    } catch {
      // Revocation is best effort; raw runtime errors never enter UI copy.
    }
  }

  function canInteract(): boolean {
    return mountedRef.current && openRef.current && ownsRuntimeRef.current;
  }

  function close() {
    if (!openRef.current) return;
    openRef.current = false;
    renderEpochRef.current += 1;
    const currentAsset = assetRef.current;
    assetRef.current = null;
    setAsset(null);
    if (currentAsset) revokeOnce(currentAsset);
    if (!closeNotifiedRef.current) {
      closeNotifiedRef.current = true;
      onCloseRef.current();
    }
  }

  useLayoutEffect(() => {
    if (!ownsRuntime) close();
  }, [ownsRuntime]);

  useLayoutEffect(() => {
    mountedRef.current = true;
    if (!closeNotifiedRef.current) openRef.current = true;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const appShell = document.querySelector<HTMLElement>(".app-shell");
    const wasInert = appShell?.inert ?? false;
    if (appShell) appShell.inert = true;
    closeRef.current?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", keydown);
    return () => {
      window.removeEventListener("keydown", keydown);
      mountedRef.current = false;
      openRef.current = false;
      renderEpochRef.current += 1;
      if (appShell) appShell.inert = wasInert;
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  useEffect(() => {
    if (!canInteract()) return undefined;
    const epoch = ++renderEpochRef.current;
    let current: ShareCardAsset | null = null;
    let cancelled = false;
    setError("");
    setNotice("");
    setAsset(null);
    let snapshot: ReturnType<typeof createSafeShareSnapshot>;
    try {
      snapshot = safeSnapshot(profile, snapshotKind);
    } catch {
      setError("This profile cannot be shared because its metric provenance is not coherent.");
      return () => {
        cancelled = true;
      };
    }
    void initialRuntimeRef.current
      .render(snapshot)
      .then((nextAsset) => {
        if (
          cancelled ||
          !canInteract() ||
          renderEpochRef.current !== epoch ||
          !isSafeAsset(nextAsset, profile)
        ) {
          revokeOnce(nextAsset);
          if (!cancelled && canInteract() && renderEpochRef.current === epoch) {
            setError("The minimized local PNG preview did not satisfy the safe image contract.");
          }
          return;
        }
        current = nextAsset;
        assetRef.current = nextAsset;
        setAsset(nextAsset);
      })
      .catch(() => {
        if (!cancelled && canInteract() && renderEpochRef.current === epoch) {
          setError("The minimized local PNG preview could not be created.");
        }
      });
    return () => {
      cancelled = true;
      if (current) revokeOnce(current);
    };
  }, [ownerIdentity]);

  async function perform(action: "copy" | "share") {
    const selectedAsset = asset;
    if (
      !canInteract() ||
      !selectedAsset ||
      assetRef.current !== selectedAsset ||
      pendingAction !== null
    ) {
      return;
    }
    const epoch = renderEpochRef.current;
    setError("");
    setNotice("");
    setPendingAction(action);
    try {
      if (action === "copy") await initialRuntimeRef.current.copy(selectedAsset);
      else await initialRuntimeRef.current.share(selectedAsset);
      if (
        canInteract() &&
        renderEpochRef.current === epoch &&
        assetRef.current === selectedAsset
      ) {
        setNotice(action === "copy" ? "PNG copied to the clipboard." : "System share opened.");
      }
    } catch {
      if (
        canInteract() &&
        renderEpochRef.current === epoch &&
        assetRef.current === selectedAsset
      ) {
        setError(action === "copy" ? "The PNG could not be copied." : "The system share was cancelled or unavailable.");
      }
    } finally {
      if (
        canInteract() &&
        renderEpochRef.current === epoch &&
        assetRef.current === selectedAsset
      ) {
        setPendingAction(null);
      }
    }
  }

  function download() {
    const selectedAsset = asset;
    if (!canInteract() || !selectedAsset || assetRef.current !== selectedAsset) {
      return;
    }
    setError("");
    setNotice("");
    try {
      initialRuntimeRef.current.download(selectedAsset);
      if (canInteract() && assetRef.current === selectedAsset) {
        setNotice("PNG download started.");
      }
    } catch {
      if (canInteract() && assetRef.current === selectedAsset) {
        setError("The PNG could not be downloaded.");
      }
    }
  }

  let copyAvailable = false;
  let shareAvailable = false;
  if (asset && canInteract()) {
    try {
      copyAvailable = initialRuntimeRef.current.canCopy() === true;
    } catch {
      copyAvailable = false;
    }
    try {
      shareAvailable = initialRuntimeRef.current.canShare(asset) === true;
    } catch {
      shareAvailable = false;
    }
  }

  if (!ownsRuntime) return null;

  return createPortal(
    <div aria-labelledby={titleId} aria-modal="true" className="share-dialog" role="dialog">
      <div className="share-dialog__scrim" onPointerDown={close} />
      <section className="share-dialog__panel" ref={panelRef}>
        <header>
          <div>
            <p className="eyebrow">Privacy preview</p>
            <h2 id={titleId}>Share this metric profile</h2>
          </div>
          <button className="share-dialog__close" onClick={close} ref={closeRef} type="button">Close</button>
        </header>
        <div className="share-dialog__warning" role="note">
          <strong>Derived metrics can still be sensitive.</strong>
          <span>Review before sharing. The image excludes project and session names, IDs, evidence text, prompts, paths, and model-cache details.</span>
        </div>
        <div className="share-dialog__preview">
          {error ? (
            <p role="alert">{error}</p>
          ) : asset ? (
            <img
              alt={`Minimized local ${profile.kind === "prompt" ? "prompt" : "logic"} metric share card preview`}
              src={asset.previewUrl}
            />
          ) : (
            <p role="status">Creating local PNG preview…</p>
          )}
        </div>
        <p aria-live="polite" className="share-dialog__notice">{notice}</p>
        <footer>
          <button className="button button--secondary" onClick={close} type="button">Cancel</button>
          <button
            className="button button--secondary"
            disabled={!asset || !copyAvailable || pendingAction !== null}
            onClick={() => void perform("copy")}
            title={copyAvailable ? undefined : "Clipboard image copy is not supported by this browser"}
            type="button"
          >
            Copy image
          </button>
          <button
            className="button button--secondary"
            disabled={!asset || !shareAvailable || pendingAction !== null}
            onClick={() => void perform("share")}
            title={shareAvailable ? undefined : "System image sharing is not supported by this browser"}
            type="button"
          >
            Share…
          </button>
          <button
            className="button button--primary"
            disabled={!asset || pendingAction !== null}
            onClick={download}
            type="button"
          >
            Download PNG
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
