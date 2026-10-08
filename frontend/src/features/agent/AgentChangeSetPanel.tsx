import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentChangeDiff,
  AgentChangedFile,
  AgentChangeRestoreApplyResult,
  AgentChangeRestorePreview,
  AgentChangeSet,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { AgentDiffViewer } from "./AgentDiffViewer";
import "./AgentChangeSetPanel.css";

type ChangeTransport = Partial<Pick<
  PromptEnhancerTransport,
  "getAgentChangeSet" | "getAgentChangeDiff" | "previewAgentChangeRestore" | "applyAgentChangeRestore"
>>;
type LoadState = "loading" | "ready" | "error" | "unavailable";
type RestoreState =
  | { phase: "idle" }
  | { phase: "previewing"; path: string }
  | { phase: "review"; preview: AgentChangeRestorePreview }
  | { phase: "applying"; preview: AgentChangeRestorePreview }
  | { phase: "success"; result: AgentChangeRestoreApplyResult }
  | { phase: "error"; path: string; message: string };

export type AgentChangeReviewRequest = {
  sessionId: string;
  path: string;
  requestId: number;
};

const EFFECT_LABEL: Record<AgentChangedFile["net_effect"], string> = {
  created: "Created",
  modified: "Modified",
  deleted: "Deleted outside reviewed writes",
  reverted: "Back at session baseline",
  unknown: "Current effect unknown",
};

const REASON_LABEL: Record<NonNullable<AgentChangedFile["reason"]>, string> = {
  publication_unverified: "Publication outcome needs inspection",
  current_revision_changed: "Current file changed after the latest reviewed write",
  review_chain_gap: "An unreviewed revision entered this path",
  current_file_missing: "The reviewed path is currently missing",
  current_file_unavailable: "The current path cannot be inspected safely",
  baseline_not_retained: "The session baseline exceeded the retained diff budget",
};

const RESTORE_OPERATION_LABEL: Record<AgentChangeRestorePreview["operation"], string> = {
  edit: "Restore the retained file bytes",
  recreate: "Recreate the missing baseline file",
  trash_created: "Move the session-created file to the Recycle Bin",
};

function restoreError(caught: unknown): string {
  if (caught instanceof TransportError) {
    if (caught.reasonCode === "change_already_reverted") {
      return "This path already matches its retained session baseline. Refresh the change set.";
    }
    if (caught.reasonCode === "change_restore_baseline_unavailable") {
      return "The original bytes were not retained within the bounded session budget, so this path cannot be restored automatically.";
    }
    if (caught.reasonCode === "change_restore_unavailable") {
      return "This path cannot be restored safely from the retained evidence. Inspect the current file and workspace history.";
    }
    if ([
      "workspace_preview_expired",
      "workspace_preview_not_found",
      "workspace_preview_mismatch",
      "change_restore_mismatch",
      "workspace_revision_changed",
    ].includes(caught.reasonCode ?? "")) {
      return "The path changed or this review expired. Nothing was claimed as restored; create a fresh preview.";
    }
    if (caught.reasonCode === "change_restore_verification_failed") {
      return "The restore outcome could not be verified. Inspect the current file before attempting another workspace change.";
    }
  }
  return "The baseline restore could not be completed. No successful restore is claimed; refresh and review the path again.";
}

function plural(value: number, one: string, many = `${one}s`): string {
  return `${value} ${value === 1 ? one : many}`;
}

function currentChangeCount(changeSet: AgentChangeSet): number {
  return changeSet.files.filter((file) => ["created", "modified", "deleted"].includes(file.net_effect)).length;
}

function restoreAvailability(file: AgentChangedFile, transport: ChangeTransport): { available: boolean; label: string } {
  if (transport.previewAgentChangeRestore === undefined || transport.applyAgentChangeRestore === undefined) {
    return { available: false, label: "Recovery unavailable in this transport" };
  }
  if (file.net_effect === "reverted") {
    return { available: false, label: "Already at the retained baseline" };
  }
  if (file.reason === "baseline_not_retained") {
    return { available: false, label: "Recovery unavailable · baseline not retained" };
  }
  if (file.reason === "current_file_unavailable") {
    return { available: false, label: "Recovery unavailable · path cannot be reobserved safely" };
  }
  return {
    available: true,
    label: file.net_effect === "created"
      ? "Recovery review available · Recycle Bin"
      : file.net_effect === "deleted"
        ? "Recovery review available · recreate baseline"
        : "Recovery review available · restore baseline",
  };
}

function restoreButtonLabel(file: AgentChangedFile): string {
  if (file.net_effect === "created") return "Review Recycle Bin recovery";
  if (file.net_effect === "deleted") return "Review baseline recreation";
  return "Restore baseline";
}

export function AgentChangeSetPanel({
  sessionId,
  transport,
  refreshKey,
  fileActionsDisabled,
  onOpenFile,
  artifactPaths,
  onOpenArtifact,
  onAddArtifact,
  onRestored,
  userPresenceAvailable = true,
  reviewRequest,
}: {
  sessionId: string;
  transport: ChangeTransport;
  refreshKey: string | number;
  fileActionsDisabled: boolean;
  onOpenFile?: (path: string) => void;
  artifactPaths?: ReadonlySet<string>;
  onOpenArtifact?: (path: string) => void;
  onAddArtifact?: (path: string) => void;
  onRestored?: (result: AgentChangeRestoreApplyResult) => void;
  userPresenceAvailable?: boolean;
  reviewRequest?: AgentChangeReviewRequest | null;
}) {
  const [state, setState] = useState<LoadState>(transport.getAgentChangeSet ? "loading" : "unavailable");
  const [changeSet, setChangeSet] = useState<AgentChangeSet | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [diffState, setDiffState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [changeDiff, setChangeDiff] = useState<AgentChangeDiff | null>(null);
  const [actionError, setActionError] = useState("");
  const [restoreState, setRestoreState] = useState<RestoreState>({ phase: "idle" });
  const diffRequest = useRef<AbortController | null>(null);
  const restoreRequest = useRef<AbortController | null>(null);
  const diffSectionRef = useRef<HTMLElement | null>(null);
  const restoreSectionRef = useRef<HTMLElement | null>(null);
  const handledReviewRequest = useRef<AgentChangeReviewRequest | null>(null);

  useEffect(() => {
    const load = transport.getAgentChangeSet;
    diffRequest.current?.abort();
    diffRequest.current = null;
    setSelectedPath(null);
    setChangeDiff(null);
    setDiffState("idle");
    setActionError("");
    if (!load) {
      setState("unavailable");
      setChangeSet(null);
      return undefined;
    }
    const controller = new AbortController();
    setState("loading");
    void Promise.resolve(load(sessionId, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || value.session_id !== sessionId) return;
        setChangeSet(value);
        setState("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setChangeSet(null);
        setState("error");
      });
    return () => controller.abort();
  }, [refreshKey, retryNonce, sessionId, transport]);

  useEffect(() => () => {
    diffRequest.current?.abort();
    restoreRequest.current?.abort();
    handledReviewRequest.current = null;
  }, [sessionId, transport]);

  useEffect(() => {
    restoreRequest.current?.abort();
    restoreRequest.current = null;
    setRestoreState({ phase: "idle" });
  }, [sessionId, transport]);

  useEffect(() => {
    if (
      reviewRequest === null
      || reviewRequest === undefined
      || reviewRequest.sessionId !== sessionId
      || state !== "ready"
      || changeSet === null
      || handledReviewRequest.current?.requestId === reviewRequest.requestId
    ) return;
    handledReviewRequest.current = reviewRequest;
    const file = changeSet.files.find((candidate) => candidate.path === reviewRequest.path);
    if (file === undefined) {
      setActionError("This artifact has no retained net-diff entry in the current reviewed change set.");
      return;
    }
    if (fileActionsDisabled) {
      setActionError("Change review is temporarily unavailable while this chat is closing or disconnected.");
      return;
    }
    if (!file.diff_available || transport.getAgentChangeDiff === undefined) {
      setActionError("No bounded net diff is available for this artifact path. Reveal the current file instead.");
      return;
    }
    setActionError("");
    reviewDiff(file.path);
  }, [changeSet, fileActionsDisabled, reviewRequest, sessionId, state, transport]);

  useEffect(() => {
    if (diffState !== "ready" && diffState !== "error") return;
    diffSectionRef.current?.scrollIntoView?.({ block: "nearest" });
    diffSectionRef.current?.focus({ preventScroll: true });
  }, [diffState, selectedPath]);

  useEffect(() => {
    if (!["review", "success", "error"].includes(restoreState.phase)) return;
    restoreSectionRef.current?.scrollIntoView?.({ block: "nearest" });
    restoreSectionRef.current?.focus({ preventScroll: true });
  }, [restoreState]);

  const totals = useMemo(() => changeSet ? {
    current: currentChangeCount(changeSet),
    reverted: changeSet.files.filter((file) => file.net_effect === "reverted").length,
    attention: changeSet.files.filter((file) => file.verification !== "verified").length,
  } : null, [changeSet]);

  function reviewDiff(path: string): void {
    const load = transport.getAgentChangeDiff;
    if (!load || fileActionsDisabled) return;
    diffRequest.current?.abort();
    const controller = new AbortController();
    diffRequest.current = controller;
    setSelectedPath(path);
    setActionError("");
    setChangeDiff(null);
    setDiffState("loading");
    void Promise.resolve(load(sessionId, path, controller.signal))
      .then((value) => {
        if (controller.signal.aborted || value.session_id !== sessionId || value.summary.path !== path) return;
        setChangeDiff(value);
        setDiffState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setDiffState("error");
      });
  }

  function previewRestore(path: string): void {
    const load = transport.previewAgentChangeRestore;
    if (!load || fileActionsDisabled) return;
    restoreRequest.current?.abort();
    const controller = new AbortController();
    restoreRequest.current = controller;
    setActionError("");
    setRestoreState({ phase: "previewing", path });
    void Promise.resolve(load(sessionId, { path }, controller.signal))
      .then((preview) => {
        if (controller.signal.aborted || restoreRequest.current !== controller) return;
        if (preview.session_id !== sessionId || preview.path !== path) return;
        setRestoreState({ phase: "review", preview });
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted && restoreRequest.current === controller) {
          setRestoreState({ phase: "error", path, message: restoreError(caught) });
        }
      });
  }

  function applyRestore(preview: AgentChangeRestorePreview): void {
    const apply = transport.applyAgentChangeRestore;
    if (!apply || fileActionsDisabled) return;
    restoreRequest.current?.abort();
    const controller = new AbortController();
    restoreRequest.current = controller;
    setRestoreState({ phase: "applying", preview });
    void Promise.resolve(apply(sessionId, preview.preview_id, {
      path: preview.path,
      operation: preview.operation,
      expected_revision: preview.expected_revision ?? null,
      restored_revision: preview.restored_revision ?? null,
      confirmation: "apply_reviewed_change_restore",
    }, controller.signal))
      .then((result) => {
        if (controller.signal.aborted || restoreRequest.current !== controller) return;
        if (result.session_id !== sessionId || result.path !== preview.path) return;
        setRestoreState({ phase: "success", result });
        onRestored?.(result);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted && restoreRequest.current === controller) {
          setRestoreState({ phase: "error", path: preview.path, message: restoreError(caught) });
        }
      });
  }

  function closeRestore(): void {
    restoreRequest.current?.abort();
    restoreRequest.current = null;
    setRestoreState({ phase: "idle" });
  }

  return <section aria-label="Reviewed session change set" className="agent-change-set">
    <header className="agent-change-set__header">
      <span>
        <small>WORKSPACE · LIVE REVIEWED PATHS</small>
        <strong>Reviewed change set</strong>
      </span>
      <button
        className="button button--ghost"
        disabled={state === "loading" || transport.getAgentChangeSet === undefined}
        onClick={() => setRetryNonce((value) => value + 1)}
        type="button"
      >Refresh</button>
    </header>

    {state === "loading" && <p role="status">Comparing retained baselines with current reviewed paths…</p>}
    {state === "unavailable" && <p>The current transport cannot load a reviewed change set.</p>}
    {state === "error" && <div className="agent-change-set__error" role="alert">
      <span>The reviewed change set could not be refreshed. No previous result is presented as current.</span>
      <button className="button button--ghost" onClick={() => setRetryNonce((value) => value + 1)} type="button">Try again</button>
    </div>}
    {actionError && <p className="agent-change-set__action-error" role="alert">{actionError}</p>}

    {state === "ready" && changeSet && totals && <>
      <div className="agent-change-set__summary">
        <span data-coverage={changeSet.coverage}>
          {changeSet.coverage === "complete" ? "Complete reviewed-path coverage" : "Partial reviewed-path coverage"}
        </span>
        <p>
          {plural(totals.current, "current change")}
          {totals.reverted > 0 ? ` · ${plural(totals.reverted, "reverted path")}` : ""}
          {` · ${plural(changeSet.reviewed_writes, "reviewed write")}`}
          {totals.attention > 0 ? ` · ${plural(totals.attention, "path")} needs attention` : ""}
        </p>
      </div>

      {changeSet.coverage === "partial" && <div className="agent-change-set__warnings" role="status">
        {!changeSet.settled && <span>The session is active, closing, or its cleanup is unconfirmed; this inventory is not final.</span>}
        {changeSet.command_attempts > 0 && <span>{plural(changeSet.command_attempts, "approved command attempt")} may have uninventoried file effects.</span>}
        {changeSet.unverified_writes > 0 && <span>{plural(changeSet.unverified_writes, "write publication")} remain{changeSet.unverified_writes === 1 ? "s" : ""} unverified.</span>}
        {changeSet.omitted_write_receipts > 0 && <span>{plural(changeSet.omitted_write_receipts, "write receipt")} exceeded the session inventory limit.</span>}
        {changeSet.tracking_failed && <span>The in-memory change tracker lost evidence; reopen paths before relying on this inventory.</span>}
      </div>}

      {changeSet.files.length === 0 ? <p className="agent-change-set__empty">
        {changeSet.reviewed_noops > 0
          ? `${plural(changeSet.reviewed_noops, "reviewed no-op")} recorded; no path differs from its retained session baseline.`
          : "No reviewed file publication has entered this session change set."}
      </p> : <ul aria-label="Current reviewed path inventory" className="agent-change-set__files">
        {changeSet.files.map((file) => {
          const recovery = restoreAvailability(file, transport);
          return <li data-verification={file.verification} key={file.path}>
          <div className="agent-change-set__file-main">
            <code>{file.path}</code>
            <span>{EFFECT_LABEL[file.net_effect]}</span>
            <small>
              {plural(file.reviewed_writes, "reviewed write")}
              {file.agent_writes > 0 ? ` · ${file.agent_writes} Agent` : ""}
              {file.manual_writes > 0 ? ` · ${file.manual_writes} manual` : ""}
            </small>
            {file.reason && <small className="agent-change-set__reason">{REASON_LABEL[file.reason]}</small>}
            <small className="agent-change-set__recovery" data-available={recovery.available}>{recovery.label}</small>
          </div>
          <div className="agent-change-set__actions">
            <button
              className="button button--ghost"
              disabled={fileActionsDisabled || !file.diff_available || transport.getAgentChangeDiff === undefined}
              onClick={() => reviewDiff(file.path)}
              type="button"
            >Review net diff</button>
            {onOpenFile && <button
              className="button button--ghost"
              disabled={fileActionsDisabled || file.current_byte_size === null}
              onClick={() => onOpenFile(file.path)}
              type="button"
            >Open current file</button>}
            {artifactPaths?.has(file.path) && onOpenArtifact ? <button
              className="button button--ghost"
              disabled={fileActionsDisabled}
              onClick={() => onOpenArtifact(file.path)}
              type="button"
            >Open artifact</button> : onAddArtifact && <button
              className="button button--ghost"
              disabled={fileActionsDisabled || file.current_byte_size === null}
              onClick={() => onAddArtifact(file.path)}
              title={file.current_byte_size === null ? "Only a currently readable file can be added as an artifact." : undefined}
              type="button"
            >Add as artifact</button>}
            <button
              className="button button--ghost"
              disabled={
                fileActionsDisabled
                || !recovery.available
              }
              onClick={() => previewRestore(file.path)}
              title={file.net_effect === "reverted"
                ? "This path already matches its retained session baseline."
                : file.reason === "baseline_not_retained"
                  ? "The retained baseline bytes are unavailable."
                  : file.reason === "current_file_unavailable"
                    ? "The current path cannot be reobserved safely."
                    : undefined}
              type="button"
            >{restoreButtonLabel(file)}</button>
          </div>
        </li>;
        })}
      </ul>}

      <p className="agent-change-set__scope">
        Net effects compare each retained first-reviewed baseline with the live file. This is not a whole-workspace or Git scan; commands and external changes cannot gain reviewed authority.
      </p>
    </>}

    {selectedPath && <section
      aria-label={`Net diff for ${selectedPath}`}
      className="agent-change-set__diff"
      ref={diffSectionRef}
      tabIndex={-1}
    >
      <header>
        <span><small>NET DIFF</small><strong>{selectedPath}</strong></span>
        <button className="button button--ghost" onClick={() => { diffRequest.current?.abort(); setSelectedPath(null); setChangeDiff(null); setDiffState("idle"); }} type="button">Close diff</button>
      </header>
      {diffState === "loading" && <p role="status">Reading the current reviewed path…</p>}
      {diffState === "error" && <div role="alert">
        <span>The current net diff could not be loaded.</span>
        <button className="button button--ghost" onClick={() => reviewDiff(selectedPath)} type="button">Try diff again</button>
      </div>}
      {diffState === "ready" && changeDiff && <>
        {changeDiff.diff_state === "available" && typeof changeDiff.diff === "string" && <AgentDiffViewer
          addedLines={changeDiff.added_lines}
          diff={changeDiff.diff}
          label={`Net diff for ${selectedPath}`}
          removedLines={changeDiff.removed_lines}
        />}
        {changeDiff.diff_state === "available" && typeof changeDiff.diff !== "string" && <p role="alert">The diff response was incomplete, so no review is displayed.</p>}
        {changeDiff.diff_state === "no_change" && <p>The current file matches its retained session baseline.</p>}
        {changeDiff.diff_state === "line_ending_only" && <p>Only the on-disk line-ending representation differs from the retained session baseline.</p>}
        {changeDiff.diff_state === "too_large" && <p>The net diff exceeds the bounded review payload. Open the current file and inspect it directly.</p>}
        {changeDiff.diff_state === "unavailable" && <p>The baseline or current file is unavailable, so no net diff is claimed.</p>}
        {onOpenFile && changeDiff.summary.current_byte_size !== null && <button
          className="button button--ghost agent-change-set__inspect"
          disabled={fileActionsDisabled}
          onClick={() => onOpenFile(changeDiff.summary.path)}
          type="button"
        >Inspect current file</button>}
      </>}
    </section>}

    {restoreState.phase !== "idle" && <section
      aria-label="Baseline restore review"
      className="agent-change-set__restore"
      ref={restoreSectionRef}
      tabIndex={-1}
    >
      <header>
        <span>
          <small>RECOVERY · RETAINED SESSION BASELINE</small>
          <strong>{restoreState.phase === "previewing" || restoreState.phase === "error"
            ? restoreState.path
            : restoreState.phase === "success"
              ? restoreState.result.path
              : restoreState.preview.path}</strong>
        </span>
        <button className="button button--ghost" disabled={restoreState.phase === "applying"} onClick={closeRestore} type="button">Close</button>
      </header>
      {restoreState.phase === "previewing" && <p role="status">Reobserving the exact path and preparing an inverse review…</p>}
      {restoreState.phase === "error" && <div className="agent-change-set__restore-error" role="alert">
        <span>{restoreState.message}</span>
        <button className="button button--ghost" onClick={() => previewRestore(restoreState.path)} type="button">Create fresh preview</button>
      </div>}
      {(restoreState.phase === "review" || restoreState.phase === "applying") && <>
        <div className="agent-change-set__restore-summary">
          <strong>{RESTORE_OPERATION_LABEL[restoreState.preview.operation]}</strong>
          <span>
            {restoreState.preview.operation === "trash_created"
              ? "Recoverable through the Windows Recycle Bin"
              : `${restoreState.preview.restored_byte_size?.toLocaleString() ?? "Unknown"} baseline bytes`}
          </span>
        </div>
        {restoreState.preview.diff_state === "available" && typeof restoreState.preview.diff === "string" && <AgentDiffViewer
          addedLines={restoreState.preview.added_lines}
          diff={restoreState.preview.diff}
          label={`Baseline restore diff for ${restoreState.preview.path}`}
          removedLines={restoreState.preview.removed_lines}
        />}
        {restoreState.preview.diff_state === "available" && typeof restoreState.preview.diff !== "string" && <p role="alert">The restore diff response was incomplete, so this review cannot be applied.</p>}
        {restoreState.preview.diff_state === "line_ending_only" && <p>
          The text is unchanged; applying this review restores only the retained on-disk line-ending representation.
        </p>}
        {restoreState.preview.diff_state === "too_large" && <p>
          The inverse diff exceeds the bounded payload. The exact retained revision and byte count are still revision-bound, but no text diff is displayed.
        </p>}
        <p className="agent-change-set__restore-warning">
          Applying asks for native confirmation, rechecks the current revision, and then verifies the filesystem result. This preview is single-use and cannot grant authority to another path.
        </p>
        {!userPresenceAvailable && <p className="agent-change-set__restore-error" role="alert">
          Native confirmation is unavailable in this window. Keep the protected Agent window open and retry there.
        </p>}
        <div className="agent-change-set__restore-actions">
          {onOpenFile && restoreState.preview.operation !== "recreate" && <button
            className="button button--ghost"
            disabled={restoreState.phase === "applying" || fileActionsDisabled}
            onClick={() => onOpenFile(restoreState.preview.path)}
            type="button"
          >Inspect current file</button>}
          <button className="button button--ghost" disabled={restoreState.phase === "applying"} onClick={closeRestore} type="button">Keep current file</button>
          <button
            className="button button--primary"
            disabled={
              restoreState.phase === "applying"
              || fileActionsDisabled
              || !userPresenceAvailable
              || (restoreState.preview.diff_state === "available" && typeof restoreState.preview.diff !== "string")
            }
            onClick={() => applyRestore(restoreState.preview)}
            type="button"
          >{restoreState.phase === "applying" ? "Confirming and verifying…" : "Apply baseline restore"}</button>
        </div>
      </>}
      {restoreState.phase === "success" && <div className="agent-change-set__restore-success" role="status">
        <strong>Baseline restored and verified on disk.</strong>
        <span>{restoreState.result.operation === "trash_created"
          ? "The session-created file was moved to the Windows Recycle Bin."
          : `The path now matches the retained revision ${restoreState.result.current_revision?.slice(0, 12)}….`}</span>
        {restoreState.result.change_set_verification !== "verified" && <small>
          Filesystem verification succeeded, but the reviewed-path inventory remains {restoreState.result.change_set_verification.replaceAll("_", " ")}
          {restoreState.result.change_set_reason ? ` (${restoreState.result.change_set_reason.replaceAll("_", " ")})` : ""}. Refresh before relying on the inventory.
        </small>}
        {artifactPaths?.has(restoreState.result.path) && onOpenArtifact ? <button
          className="button button--ghost"
          onClick={() => onOpenArtifact(restoreState.result.path)}
          type="button"
        >Open resulting artifact</button> : restoreState.result.baseline_state === "present" && onAddArtifact && <button
          className="button button--ghost"
          disabled={fileActionsDisabled}
          onClick={() => onAddArtifact(restoreState.result.path)}
          type="button"
        >Add restored file as artifact</button>}
      </div>}
    </section>}
  </section>;
}
