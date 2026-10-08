import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentEvent,
  AgentWorkspaceCreatePreview,
  AgentWorkspaceDirectoryCreatePreview,
  AgentWorkspaceDirectoryMovePreview,
  AgentWorkspaceEditPreview,
  AgentWorkspaceFile,
  AgentWorkspaceFileTrashPreview,
  AgentWorkspaceMovePreview,
  AgentWorkspaceTransactionPreview,
  AgentWorkspaceTree,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { AGENT_WORKSPACE_MAX_FILE_BYTES } from "../../shared/api/agentWorkspaceContract";
import { TransportError } from "../../shared/api/httpTransport";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";
import { AgentWorkspaceDiscoveryPanel } from "./AgentWorkspaceDiscoveryPanel";
import { AgentArtifactCaptureDialog } from "./AgentArtifactCaptureDialog";
import { AgentDiffViewer } from "./AgentDiffViewer";

type WorkspaceTransport = Pick<
  PromptEnhancerTransport,
  | "getAgentWorkspaceTree"
  | "getAgentWorkspaceFile"
  | "previewAgentWorkspaceEdit"
  | "applyAgentWorkspaceEdit"
> & Partial<Pick<
  PromptEnhancerTransport,
  | "getAgentWorkspaceDiscovery"
  | "getAgentWorkspaceSearch"
  | "previewAgentWorkspaceTransaction"
  | "applyAgentWorkspaceTransaction"
  | "previewAgentWorkspaceCreate"
  | "applyAgentWorkspaceCreate"
  | "previewAgentWorkspaceDirectoryCreate"
  | "applyAgentWorkspaceDirectoryCreate"
  | "previewAgentWorkspaceDirectoryMove"
  | "applyAgentWorkspaceDirectoryMove"
  | "previewAgentWorkspaceMove"
  | "applyAgentWorkspaceMove"
  | "previewAgentWorkspaceFileTrash"
  | "applyAgentWorkspaceFileTrash"
  | "previewAgentArtifactCapture"
  | "captureAgentArtifact"
>>;

const WORKSPACE_TREE_PAGE_SIZE = 50;

type TransactionDraftBase = {
  path: string;
  content: string;
  line_ending: AgentWorkspaceFile["line_ending"];
};

type TransactionEditDraft = TransactionDraftBase & {
  operation: "edit";
  expected_revision: string;
};

type TransactionCreateDraft = TransactionDraftBase & {
  operation: "create";
  expected_revision: null;
};

type TransactionDraft = TransactionEditDraft | TransactionCreateDraft;

type DiscardPrompt = {
  message: string;
  confirmLabel: string;
};

const APPLY_CONFIRMATION = "apply_reviewed_workspace_edit" as const;
const CREATE_CONFIRMATION = "apply_reviewed_workspace_create" as const;
const DIRECTORY_CREATE_CONFIRMATION = "apply_reviewed_workspace_directory_create" as const;
const DIRECTORY_MOVE_CONFIRMATION = "apply_reviewed_workspace_directory_move" as const;
const FILE_TRASH_CONFIRMATION = "apply_reviewed_workspace_file_trash" as const;
const MOVE_CONFIRMATION = "apply_reviewed_workspace_move" as const;
const TRANSACTION_CONFIRMATION = "apply_reviewed_workspace_transaction" as const;
const MAX_TRANSACTION_FILES = 8;
const ROOT_CHANGED = "The workspace folder was moved or replaced. Copy any draft you need, then start a new session with the intended folder. This editor is read-only.";

export type AgentFileOpenRequest = {
  sessionId: string;
  path: string;
  requestId: number;
  intent?: "open" | "reveal" | "capture";
};

function parentFolder(path: string): string {
  if (path === ".") return ".";
  const index = path.lastIndexOf("/");
  return index < 0 ? "." : path.slice(0, index);
}

function isWorkspaceRelativePath(path: string): boolean {
  return path.length > 0
    && path.length <= 1024
    && path !== "."
    && !path.startsWith("/")
    && !path.includes("\\")
    && !path.includes("\0")
    && !/^[A-Za-z]:/u.test(path)
    && path.split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

function compareUtf8(left: string, right: string): number {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function transactionFingerprint(drafts: readonly TransactionDraft[]): string {
  return JSON.stringify(
    [...drafts]
      .sort((left, right) => compareUtf8(left.path, right.path))
      .map(({ operation, path, content, expected_revision, line_ending }) => [operation, path, content, expected_revision, line_ending]),
  );
}

function workspacePathKey(path: string): string {
  return path.toLocaleLowerCase("en-US");
}

function transactionDraftByteSize(draft: TransactionDraft): number {
  const diskContent = draft.line_ending === "crlf"
    ? draft.content.replaceAll("\n", "\r\n")
    : draft.content;
  return new TextEncoder().encode(diskContent).byteLength;
}

function friendlyError(caught: unknown): string {
  if (caught instanceof TransportError && caught.reasonCode === "workspace_root_changed") return ROOT_CHANGED;
  if (caught instanceof TransportError && caught.reasonCode === "workspace_parent_unavailable") {
    return "The parent folder must already exist and remain an ordinary accessible workspace folder.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_path_not_found") {
    return "The reviewed source path no longer exists. Refresh the folder and create a new review.";
  }
  if (caught instanceof TransportError && (
    caught.reasonCode === "workspace_directory_unavailable"
    || caught.reasonCode === "workspace_not_a_directory"
  )) {
    return "The reviewed source is not an ordinary accessible folder. Refresh the workspace before trying another folder operation.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_revision_changed") {
    return "The reviewed path or one of its parent folders changed. Nothing was claimed as applied; create a fresh review.";
  }
  if (caught instanceof TransportError && (
    caught.reasonCode === "path_invalid"
    || caught.reasonCode === "path_outside_workspace"
    || caught.reasonCode === "workspace_link_or_reparse_refused"
  )) {
    return "Use an ordinary workspace-relative path without traversal, a drive, a link, or a reparse point.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_lifecycle_target_exists") {
    return "That destination already exists. Choose another workspace-relative path; nothing was overwritten.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_lifecycle_same_path") {
    return "The new path must differ from the current path.";
  }
  if (caught instanceof TransportError && (
    caught.reasonCode === "workspace_lifecycle_preview_expired"
    || caught.reasonCode === "workspace_lifecycle_preview_not_found"
  )) {
    return "This workspace operation review is no longer available. Review the exact paths and any applicable content again.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_lifecycle_preview_mismatch") {
    return "The workspace operation changed after review. Create a fresh review before applying it.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_move_unsupported") {
    return "Safe no-overwrite moves are unavailable on this local filesystem. No path was changed.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_move_failed") {
    return "The reviewed move was rejected and no move was claimed. Inspect both paths before retrying.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_create_failed") {
    return "The reviewed folder could not be created. No existing destination was replaced.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_create_unverified") {
    return "The folder creation outcome is unverified. Further lifecycle changes are locked; inspect the path and start a new session.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_move_into_self") {
    return "A folder cannot be moved into itself or one of its own descendants.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_move_unsupported") {
    return "Safe no-overwrite folder moves are unavailable on this local filesystem. No path was changed.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_move_failed") {
    return "The reviewed folder move was rejected and no move was claimed. Inspect both paths before retrying.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_directory_move_unverified") {
    return "The folder move outcome is unverified. Further lifecycle changes are locked; inspect both paths and start a new session.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_move_unverified") {
    return "The file move outcome is unverified. Further lifecycle changes are locked; inspect both paths and start a new session.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_file_trash_unsupported") {
    return "Reviewed Recycle Bin removal is available only for an ordinary file on a local Windows drive. No file was changed.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_file_trash_failed") {
    return "The reviewed Recycle Bin move was rejected. The exact reviewed file was restored before failure was reported.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_file_trash_unverified") {
    return "The Recycle Bin outcome is unverified. Further lifecycle changes are locked; inspect the original path and Windows Recycle Bin, then start a new session.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_lifecycle_unverified") {
    return "A previous workspace lifecycle outcome is unverified. Further lifecycle changes are locked; inspect the affected path or paths and start a new session.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_transaction_expired") {
    return "This multi-file review expired. Create a fresh review before applying the staged drafts.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_transaction_not_found") {
    return "This multi-file review is no longer available. Create a fresh review before applying the staged drafts.";
  }
  if (caught instanceof TransportError && (
    caught.reasonCode === "workspace_transaction_changed"
    || caught.reasonCode === "workspace_transaction_mismatch"
  )) {
    return "At least one staged file or review changed. Reopen the affected files, reconcile the drafts, and review the full transaction again.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_transaction_no_change") {
    return "Every staged file must contain a real change before the transaction can be reviewed.";
  }
  if (caught instanceof TransportError && (
    caught.reasonCode === "workspace_transaction_too_large"
    || caught.reasonCode === "workspace_transaction_diff_too_large"
  )) {
    return "This multi-file change is too large for one bounded review. Split it into smaller transactions.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_inspection_timeout") {
    return "Folder inspection reached its time limit. No complete listing is available; retry when the folder is responsive.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_write_failed") {
    return "The reviewed edit was not applied; the previous file was preserved. Your draft is still available for another review.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_cleanup_failed") {
    return "The edit was not published, but private staging cleanup is unconfirmed. Keep the draft and inspect the workspace before retrying.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "workspace_verification_failed") {
    return "The write result is unverified. Keep this draft and reload the file before making another edit.";
  }
  if (caught instanceof TransportError && caught.reasonCode === "command_cleanup_unconfirmed") {
    return "Command cleanup is unconfirmed. Inspect the command processes before restarting; do not apply more edits yet.";
  }
  const status = caught instanceof TransportError ? caught.status : null;
  if (status === 404) return "That file or folder is no longer available.";
  if (status === 409) return "The file or preview changed. Reopen the file and review a fresh diff.";
  if (status === 413) return "This edit is too large for one safe review.";
  if (status === 415) return "Only strict UTF-8 text files can be edited here.";
  if (status === 403) return "The request was declined, expired, or the path is protected.";
  if (status === 503) return "The local workspace or native confirmation is unavailable.";
  if (status === 200) return "The local service returned an invalid workspace response.";
  if (status === 422) return "This file cannot be safely edited in the current workspace.";
  return "The local workspace operation did not complete.";
}

function nonEditableReason(byteSize: number | null | undefined): string {
  return byteSize !== null && byteSize !== undefined && byteSize > AGENT_WORKSPACE_MAX_FILE_BYTES
    ? `too large to edit (${AGENT_WORKSPACE_MAX_FILE_BYTES / 1000} KB limit)`
    : "not editable in the bounded editor";
}

export function AgentWorkspacePane({
  sessionId,
  transport,
  pendingWrite,
  refreshKey = 0,
  onApplied,
  onArtifactCaptured,
  onCaptureUncertain,
  onDirtyChange,
  userPresenceAvailable = true,
  blockedReason,
  fileRequest,
  projectId,
  onClose,
}: {
  sessionId: string;
  transport: WorkspaceTransport;
  pendingWrite: AgentEvent | null;
  refreshKey?: string | number;
  onApplied?: (path: string) => void;
  onArtifactCaptured?: () => void;
  onCaptureUncertain?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  userPresenceAvailable?: boolean;
  blockedReason?: string;
  fileRequest?: AgentFileOpenRequest | null;
  projectId?: string | null;
  onClose?: () => void;
}) {
  const [folder, setFolder] = useState(".");
  const [tree, setTree] = useState<AgentWorkspaceTree | null>(null);
  const [opened, setOpened] = useState<AgentWorkspaceFile | null>(null);
  const [draft, setDraft] = useState("");
  const [preview, setPreview] = useState<AgentWorkspaceEditPreview | null>(null);
  const [previewDraft, setPreviewDraft] = useState("");
  const [transactionDrafts, setTransactionDrafts] = useState<TransactionDraft[]>([]);
  const [transactionPreview, setTransactionPreview] = useState<AgentWorkspaceTransactionPreview | null>(null);
  const [transactionPreviewFingerprint, setTransactionPreviewFingerprint] = useState("");
  const [transactionBlocked, setTransactionBlocked] = useState(false);
  const [lifecycleMode, setLifecycleMode] = useState<"create" | "directory" | "directory-move" | "move" | "trash" | null>(null);
  const [createPath, setCreatePath] = useState("");
  const [createContent, setCreateContent] = useState("");
  const [createLineEnding, setCreateLineEnding] = useState<"lf" | "crlf">("lf");
  const [createTransactionSourcePath, setCreateTransactionSourcePath] = useState<string | null>(null);
  const [createFilePreview, setCreateFilePreview] = useState<AgentWorkspaceCreatePreview | null>(null);
  const [createPreviewFingerprint, setCreatePreviewFingerprint] = useState("");
  const [directoryPath, setDirectoryPath] = useState("");
  const [directoryPreview, setDirectoryPreview] = useState<AgentWorkspaceDirectoryCreatePreview | null>(null);
  const [directoryPreviewFingerprint, setDirectoryPreviewFingerprint] = useState("");
  const [directoryMoveTarget, setDirectoryMoveTarget] = useState("");
  const [directoryMovePreview, setDirectoryMovePreview] = useState<AgentWorkspaceDirectoryMovePreview | null>(null);
  const [directoryMovePreviewFingerprint, setDirectoryMovePreviewFingerprint] = useState("");
  const [moveTarget, setMoveTarget] = useState("");
  const [movePreview, setMovePreview] = useState<AgentWorkspaceMovePreview | null>(null);
  const [movePreviewFingerprint, setMovePreviewFingerprint] = useState("");
  const [trashPreview, setTrashPreview] = useState<AgentWorkspaceFileTrashPreview | null>(null);
  const [trashPreviewFingerprint, setTrashPreviewFingerprint] = useState("");
  const [lifecycleBlocked, setLifecycleBlocked] = useState(false);
  const [operationLoading, setLoading] = useState(false);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeMessage, setTreeMessage] = useState("");
  const [treeRetry, setTreeRetry] = useState(0);
  const [rootChanged, setRootChanged] = useState(false);
  const [needsFileReload, setNeedsFileReload] = useState(false);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [revealedPath, setRevealedPath] = useState<string | null>(null);
  const treeEntries = tree?.entries ?? [];
  const revealedIndex = revealedPath === null
    ? null
    : treeEntries.findIndex((entry) => entry.path === revealedPath);
  const treePage = useBoundedListPage({
    itemCount: treeEntries.length,
    pageSize: WORKSPACE_TREE_PAGE_SIZE,
    preferredIndex: revealedIndex !== null && revealedIndex >= 0 ? revealedIndex : null,
    resetKey: `${sessionId}:${folder}:${treeRetry}`,
  });
  const [discardPrompt, setDiscardPrompt] = useState<DiscardPrompt | null>(null);
  const [artifactCapturePath, setArtifactCapturePath] = useState<string | null>(null);
  const activeSession = useRef(sessionId);
  const activeTransport = useRef(transport);
  const operationVersion = useRef(0);
  const operationRequest = useRef<AbortController | null>(null);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  const revealedEntryRef = useRef<HTMLLIElement | null>(null);
  const focusAfterLoad = useRef<number | null>(null);
  const openRequestedFile = useRef<(path: string) => void>(() => {});
  const revealRequestedFile = useRef<(path: string) => void>(() => {});
  const handledFileRequest = useRef<AgentFileOpenRequest | null>(null);
  const discardAction = useRef<(() => void) | null>(null);
  const keepDraftRef = useRef<HTMLButtonElement | null>(null);

  if (activeSession.current !== sessionId || activeTransport.current !== transport) {
    activeSession.current = sessionId;
    activeTransport.current = transport;
    operationVersion.current += 1;
    focusAfterLoad.current = null;
  }

  const loading = operationLoading || treeLoading;
  const dirty = opened !== null && draft !== opened.content;
  const transactionSupported = Boolean(
    transport.previewAgentWorkspaceTransaction && transport.applyAgentWorkspaceTransaction,
  );
  const createLifecycleSupported = Boolean(
    transport.previewAgentWorkspaceCreate
    && transport.applyAgentWorkspaceCreate,
  );
  const moveLifecycleSupported = Boolean(
    transport.previewAgentWorkspaceMove
    && transport.applyAgentWorkspaceMove,
  );
  const createSupported = createLifecycleSupported || transactionSupported;
  const directoryLifecycleSupported = Boolean(
    transport.previewAgentWorkspaceDirectoryCreate
    && transport.applyAgentWorkspaceDirectoryCreate,
  );
  const directoryMoveSupported = Boolean(
    transport.previewAgentWorkspaceDirectoryMove
    && transport.applyAgentWorkspaceDirectoryMove,
  );
  const fileTrashSupported = Boolean(
    transport.previewAgentWorkspaceFileTrash
    && transport.applyAgentWorkspaceFileTrash,
  );
  const artifactCaptureSupported = Boolean(
    projectId
    && transport.previewAgentArtifactCapture
    && transport.captureAgentArtifact,
  );
  const currentTransactionDraft = opened
    ? transactionDrafts.find((item): item is TransactionEditDraft => (
      item.operation === "edit" && item.path === opened.path
    )) ?? null
    : null;
  const currentDraftMatchesStage = currentTransactionDraft !== null
    && draft === currentTransactionDraft.content;
  const unstagedDirty = dirty && !currentDraftMatchesStage;
  const transactionStageNeedsUpdate = opened !== null && dirty && (
    currentTransactionDraft === null
    || currentTransactionDraft.content !== draft
    || currentTransactionDraft.expected_revision !== opened.revision
    || currentTransactionDraft.line_ending !== opened.line_ending
  );
  const transactionIsDirty = transactionDrafts.length > 0;
  const effectiveCreateLineEnding = createContent.includes("\n") ? createLineEnding : "none";
  const currentCreateTransactionDraft = createTransactionSourcePath === null
    ? null
    : transactionDrafts.find((item): item is TransactionCreateDraft => (
      item.operation === "create" && item.path === createTransactionSourcePath
    )) ?? null;
  const createDraftMatchesStage = currentCreateTransactionDraft !== null
    && createPath === currentCreateTransactionDraft.path
    && createContent === currentCreateTransactionDraft.content
    && effectiveCreateLineEnding === currentCreateTransactionDraft.line_ending;
  const createTransactionStageNeedsUpdate = lifecycleMode === "create"
    && (createPath !== "" || createContent !== "")
    && !createDraftMatchesStage;
  const lifecycleDraftDirty = lifecycleMode === "create"
    ? (createPath !== "" || createContent !== "") && !createDraftMatchesStage
    : lifecycleMode === "directory"
      ? directoryPath !== ""
      : lifecycleMode === "directory-move"
        ? directoryMoveTarget !== "" && directoryMoveTarget !== folder
        : lifecycleMode === "move"
          ? opened !== null && moveTarget !== "" && moveTarget !== opened.path
          : lifecycleMode === "trash";
  const hasUnsavedWork = unstagedDirty || transactionIsDirty || lifecycleDraftDirty;
  const currentTransactionFingerprint = transactionFingerprint(transactionDrafts);
  const transactionPreviewIsCurrent = transactionPreview !== null
    && transactionPreviewFingerprint === currentTransactionFingerprint;
  const previewIsCurrent = preview !== null && previewDraft === draft;
  const createFingerprint = JSON.stringify([
    createPath,
    createContent,
    effectiveCreateLineEnding,
  ]);
  const createPreviewIsCurrent = createFilePreview !== null
    && createPreviewFingerprint === createFingerprint;
  const transactionCreateCount = transactionDrafts.filter((item) => item.operation === "create").length;
  const transactionEditCount = transactionDrafts.length - transactionCreateCount;
  const directoryFingerprint = JSON.stringify([directoryPath]);
  const directoryPreviewIsCurrent = directoryPreview !== null
    && directoryPreviewFingerprint === directoryFingerprint;
  const directoryMoveFingerprint = JSON.stringify([folder, directoryMoveTarget]);
  const directoryMovePreviewIsCurrent = directoryMovePreview !== null
    && directoryMovePreviewFingerprint === directoryMoveFingerprint;
  const moveFingerprint = JSON.stringify([
    opened?.path ?? "",
    moveTarget,
    opened?.revision ?? "",
  ]);
  const movePreviewIsCurrent = movePreview !== null
    && movePreviewFingerprint === moveFingerprint;
  const trashFingerprint = JSON.stringify([
    opened?.path ?? "",
    opened?.revision ?? "",
    opened?.byte_size ?? -1,
  ]);
  const trashPreviewIsCurrent = trashPreview !== null
    && trashPreviewFingerprint === trashFingerprint;
  const editBlockedReason = blockedReason
    || (rootChanged ? ROOT_CHANGED : undefined)
    || (lifecycleBlocked
      ? "A reviewed workspace lifecycle operation is unverified. Inspect the affected paths and start a new session before any further workspace mutation."
      : undefined);
  const pendingPaths = pendingWrite?.tool === "write_file"
    ? typeof pendingWrite.arguments?.path === "string"
      ? [pendingWrite.arguments.path]
      : Array.isArray(pendingWrite.arguments?.paths)
        ? pendingWrite.arguments.paths.filter((path): path is string => typeof path === "string")
        : []
    : [];
  const markRootChanged = useCallback(() => {
    setRootChanged(true);
    setTree(null);
    setTreeMessage(ROOT_CHANGED);
  }, []);

  useEffect(() => {
    onDirtyChange?.(hasUnsavedWork);
  }, [hasUnsavedWork, onDirtyChange]);

  useEffect(() => {
    discardAction.current = null;
    setDiscardPrompt(null);
    setArtifactCapturePath(null);
    return () => {
      discardAction.current = null;
    };
  }, [projectId, sessionId, transport]);

  useEffect(() => {
    if (!hasUnsavedWork) return undefined;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsavedWork]);

  useEffect(() => {
    return () => {
      operationVersion.current += 1;
      operationRequest.current?.abort();
      focusAfterLoad.current = null;
      // Strict Mode replays mount effects. A cancelled initial read is not a
      // consumed receipt request and must be retried by the replacement effect.
      handledFileRequest.current = null;
    };
  }, [sessionId, transport]);

  useEffect(() => {
    setFolder(".");
    setTree(null);
    setOpened(null);
    setDraft("");
    setPreview(null);
    setPreviewDraft("");
    setTransactionDrafts([]);
    setTransactionPreview(null);
    setTransactionPreviewFingerprint("");
    setTransactionBlocked(false);
    setLifecycleMode(null);
    setCreatePath("");
    setCreateContent("");
    setCreateLineEnding("lf");
    setCreateTransactionSourcePath(null);
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setTrashPreview(null);
    setTrashPreviewFingerprint("");
    setLifecycleBlocked(false);
    setMessage("");
    setNotice("");
    setRevealedPath(null);
    setTreeMessage("");
    setRootChanged(false);
    setNeedsFileReload(false);
    setLoading(false);
  }, [sessionId, transport]);

  useEffect(() => {
    if (rootChanged) {
      setTreeLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    const requestedSession = sessionId;
    setTreeLoading(true);
    setTree(null);
    setTreeMessage("");
    transport.getAgentWorkspaceTree(sessionId, folder, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted && activeSession.current === requestedSession) {
          setTree(value);
          setTreeMessage("");
        }
      })
      .catch((caught) => {
        if (!controller.signal.aborted && activeSession.current === requestedSession) {
          setTree(null);
          setTreeMessage(inspectError(caught));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && activeSession.current === requestedSession) {
          setTreeLoading(false);
        }
      });
    return () => controller.abort();
  }, [folder, sessionId, transport, treeRetry, rootChanged]);

  useEffect(() => {
    if (!rootChanged) return;
    operationVersion.current += 1;
    operationRequest.current?.abort();
    focusAfterLoad.current = null;
    setPreview(null);
    setTransactionPreview(null);
    setTransactionPreviewFingerprint("");
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setTrashPreview(null);
    setTrashPreviewFingerprint("");
    setLoading(false);
  }, [rootChanged]);

  function inspectError(caught: unknown): string {
    if (caught instanceof TransportError && caught.reasonCode === "workspace_root_changed") setRootChanged(true);
    return friendlyError(caught);
  }

  // Receipt links use the same draft protection and request ownership as the
  // file tree. A stale request must never open a file in a replacement session.
  openRequestedFile.current = (path) => { void openFile(path); };
  revealRequestedFile.current = (path) => revealFile(path);
  useEffect(() => {
    if (!fileRequest || fileRequest.sessionId !== sessionId || handledFileRequest.current === fileRequest) return;
    handledFileRequest.current = fileRequest;
    if (fileRequest.intent === "capture") startArtifactCapture(fileRequest.path);
    else if (fileRequest.intent === "reveal") revealRequestedFile.current(fileRequest.path);
    else openRequestedFile.current(fileRequest.path);
  }, [fileRequest, sessionId]);

  useEffect(() => {
    if (revealedPath === null || tree === null || tree.path !== parentFolder(revealedPath)) return;
    const present = tree.entries.some((entry) => entry.path === revealedPath);
    if (!present) {
      setMessage(tree.complete
        ? "The recorded artifact path is not present in the current workspace folder."
        : "The recorded artifact path is outside this bounded folder page. Refresh or navigate manually to inspect it.");
      return;
    }
    revealedEntryRef.current?.scrollIntoView?.({ block: "nearest" });
    revealedEntryRef.current?.focus({ preventScroll: true });
  }, [revealedPath, tree]);

  useEffect(() => {
    if (loading || focusAfterLoad.current === null) return;
    const ownsFocus = focusAfterLoad.current === operationVersion.current;
    focusAfterLoad.current = null;
    if (ownsFocus) {
      const editor = editorRef.current;
      editor?.scrollIntoView?.({ block: "nearest" });
      // A tall editor can be considered "nearest" while still sitting just
      // outside a nested drawer's visible scrollport. Centering it makes a
      // receipt-opened file immediately reviewable in compact windows.
      editor?.scrollIntoView?.({ block: "center", inline: "nearest" });
      editor?.focus({ preventScroll: true });
    }
  }, [loading, opened]);

  function beginOperation() {
    operationRequest.current?.abort();
    focusAfterLoad.current = null;
    const controller = new AbortController();
    operationRequest.current = controller;
    return { controller, version: ++operationVersion.current };
  }

  function resetLifecycleDraft(): void {
    setLifecycleMode(null);
    setCreatePath("");
    setCreateContent("");
    setCreateTransactionSourcePath(null);
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setTrashPreview(null);
    setTrashPreviewFingerprint("");
  }

  function draftDiscardMessage(): string | null {
    if (unstagedDirty && lifecycleDraftDirty) {
      return "Discard the unsaved manual edit and pending workspace operation draft?";
    }
    if (unstagedDirty) return "Discard the unsaved manual edit?";
    if (lifecycleDraftDirty) return "Discard the pending workspace operation draft?";
    return null;
  }

  function allWorkDiscardMessage(): string | null {
    if (!hasUnsavedWork) return null;
    if (lifecycleDraftDirty && (unstagedDirty || transactionIsDirty)) {
      return "Discard all unsaved editor, transaction, and workspace operation drafts?";
    }
    if (unstagedDirty && transactionIsDirty) {
      return "Discard the unsaved manual edit and all staged multi-file drafts?";
    }
    if (transactionIsDirty) return "Discard all staged multi-file drafts?";
    if (lifecycleDraftDirty) return "Discard the pending workspace operation draft?";
    return "Discard the unsaved manual edit?";
  }

  function requestDiscard(message: string | null, confirmLabel: string, action: () => void): void {
    if (message === null) {
      action();
      return;
    }
    discardAction.current = action;
    setDiscardPrompt({ message, confirmLabel });
  }

  function finishDiscard(confirmed: boolean): void {
    const action = discardAction.current;
    discardAction.current = null;
    setDiscardPrompt(null);
    if (confirmed) action?.();
  }

  function openFile(path: string, keepNotice = false): void {
    if (rootChanged) return;
    requestDiscard(draftDiscardMessage(), "Discard and open file", () => {
      void openFileAfterDiscard(path, keepNotice);
    });
  }

  async function openFileAfterDiscard(path: string, keepNotice = false) {
    if (lifecycleMode) resetLifecycleDraft();
    const requestedSession = sessionId;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    if (!keepNotice) setNotice("");
    try {
      const file = await transport.getAgentWorkspaceFile(sessionId, path, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      focusAfterLoad.current = version;
      setOpened(file);
      const staged = transactionDrafts.find((item): item is TransactionEditDraft => (
        item.operation === "edit" && item.path === file.path
      ));
      const stagedCreate = transactionDrafts.find((item) => (
        item.operation === "create" && workspacePathKey(item.path) === workspacePathKey(file.path)
      ));
      setDraft(staged?.content ?? file.content);
      setPreview(null);
      setPreviewDraft("");
      setNeedsFileReload(false);
      if (stagedCreate) {
        invalidateTransactionPreview();
        setMessage("This path is staged as a new file but now exists on disk. The creation draft is preserved; remove it or choose a different path before reviewing the transaction.");
      } else if (staged && staged.expected_revision !== file.revision) {
        invalidateTransactionPreview();
        setMessage("This staged file changed on disk. Its draft is preserved; reconcile it with the latest file and stage it again before reviewing the transaction.");
      } else if (staged && !keepNotice) {
        setNotice("Loaded the draft already staged in the multi-file transaction.");
      }
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) {
        setLoading(false);
      }
    }
  }

  function revealFile(path: string): void {
    if (rootChanged) return;
    if (!isWorkspaceRelativePath(path)) {
      setMessage("The artifact path is not a safe workspace-relative path.");
      return;
    }
    if (lifecycleMode !== null) {
      setMessage("Finish or cancel the pending workspace operation before revealing another path. No draft was discarded.");
      return;
    }
    operationVersion.current += 1;
    operationRequest.current?.abort();
    setLoading(false);
    setMessage("");
    setNotice(`Revealing ${path} in the bounded workspace tree. The file was not opened or executed.`);
    setRevealedPath(path);
    setFolder(parentFolder(path));
  }

  function openFolder(path: string): void {
    requestDiscard(draftDiscardMessage(), "Discard and open folder", () => {
      if (lifecycleMode) resetLifecycleDraft();
      operationVersion.current += 1;
      operationRequest.current?.abort();
      setLoading(false);
      setOpened(null);
      setDraft("");
      setPreview(null);
      setPreviewDraft("");
      setNeedsFileReload(false);
      setRevealedPath(null);
      setFolder(path);
    });
  }

  function invalidateTransactionPreview(): void {
    setTransactionPreview(null);
    setTransactionPreviewFingerprint("");
  }

  function stageTransactionDraft(): void {
    if (!opened || !transactionStageNeedsUpdate || loading || needsFileReload || transactionBlocked || editBlockedReason || !transactionSupported) return;
    const conflictingCreate = transactionDrafts.find((item) => (
      item.operation === "create" && workspacePathKey(item.path) === workspacePathKey(opened.path)
    ));
    if (conflictingCreate) {
      setMessage(`${conflictingCreate.path} is already staged as a new file. Remove that creation draft before staging an edit at the same path.`);
      return;
    }
    if (!currentTransactionDraft && transactionDrafts.length >= MAX_TRANSACTION_FILES) {
      setMessage(`A transaction can review at most ${MAX_TRANSACTION_FILES} files.`);
      return;
    }
    const staged: TransactionEditDraft = {
      operation: "edit",
      path: opened.path,
      content: draft,
      expected_revision: opened.revision,
      line_ending: opened.line_ending,
    };
    const next = [
      ...transactionDrafts.filter((item) => item.path !== opened.path),
      staged,
    ].sort((left, right) => compareUtf8(left.path, right.path));
    setTransactionDrafts(next);
    invalidateTransactionPreview();
    setPreview(null);
    setPreviewDraft("");
    setDraft(opened.content);
    setMessage("");
    setNotice(
      `${opened.path} is staged in the multi-file transaction (${next.length}/${MAX_TRANSACTION_FILES}).`,
    );
  }

  function stageCreateTransactionDraft(): void {
    if (
      lifecycleMode !== "create"
      || !transactionSupported
      || !createTransactionStageNeedsUpdate
      || loading
      || transactionBlocked
      || editBlockedReason
    ) return;
    if (!isWorkspaceRelativePath(createPath)) {
      setMessage("Enter one workspace-relative file path without a drive, leading slash, backslash, or traversal segment.");
      return;
    }
    const diskContent = effectiveCreateLineEnding === "crlf"
      ? createContent.replaceAll("\n", "\r\n")
      : createContent;
    if (new TextEncoder().encode(diskContent).byteLength > AGENT_WORKSPACE_MAX_FILE_BYTES) {
      setMessage(`The new file exceeds the ${AGENT_WORKSPACE_MAX_FILE_BYTES / 1000} KB review limit.`);
      return;
    }
    const sourceKey = createTransactionSourcePath === null
      ? null
      : workspacePathKey(createTransactionSourcePath);
    const targetKey = workspacePathKey(createPath);
    const conflict = transactionDrafts.find((item) => (
      workspacePathKey(item.path) === targetKey && workspacePathKey(item.path) !== sourceKey
    ));
    if (conflict) {
      setMessage(`${conflict.path} is already staged for ${conflict.operation}. Every transaction path must be unique.`);
      return;
    }
    if (currentCreateTransactionDraft === null && transactionDrafts.length >= MAX_TRANSACTION_FILES) {
      setMessage(`A transaction can review at most ${MAX_TRANSACTION_FILES} files.`);
      return;
    }
    const staged: TransactionCreateDraft = {
      operation: "create",
      path: createPath,
      content: createContent,
      expected_revision: null,
      line_ending: effectiveCreateLineEnding,
    };
    const next = [
      ...transactionDrafts.filter((item) => (
        sourceKey === null || workspacePathKey(item.path) !== sourceKey
      )),
      staged,
    ].sort((left, right) => compareUtf8(left.path, right.path));
    setTransactionDrafts(next);
    invalidateTransactionPreview();
    resetLifecycleDraft();
    setMessage("");
    setNotice(`${createPath} is staged for creation in the multi-file transaction (${next.length}/${MAX_TRANSACTION_FILES}).`);
  }

  function openTransactionDraft(item: TransactionDraft): void {
    if (item.operation === "edit") {
      void openFile(item.path);
      return;
    }
    if (rootChanged) return;
    requestDiscard(draftDiscardMessage(), "Discard and open draft", () => {
      operationVersion.current += 1;
      operationRequest.current?.abort();
      setLoading(false);
      resetLifecycleDraft();
      setLifecycleMode("create");
      setCreatePath(item.path);
      setCreateContent(item.content);
      setCreateLineEnding(item.line_ending === "crlf" ? "crlf" : "lf");
      setCreateTransactionSourcePath(item.path);
      setMessage("");
      setNotice("Loaded the new-file draft already staged in the multi-file transaction.");
    });
  }

  function removeTransactionDraft(path: string): void {
    const staged = transactionDrafts.find((item) => item.path === path);
    const remainsInEditor = staged?.operation === "edit" && opened?.path === path;
    const remainsInCreateEditor = staged?.operation === "create"
      && lifecycleMode === "create"
      && createTransactionSourcePath === path;
    const remainsInDraftEditor = remainsInEditor || remainsInCreateEditor;
    requestDiscard(
      remainsInDraftEditor
        ? `Remove ${path} from the transaction? Its current text will remain in the editor as an unsaved draft.`
        : `Remove ${path} from the transaction and discard its staged draft?`,
      "Remove staged draft",
      () => {
        if (remainsInEditor && staged?.operation === "edit") {
          setDraft(staged.content);
          setPreview(null);
          setPreviewDraft("");
        }
        setTransactionDrafts((items) => items.filter((item) => item.path !== path));
        if (remainsInCreateEditor) setCreateTransactionSourcePath(null);
        invalidateTransactionPreview();
        setMessage("");
        setNotice(remainsInDraftEditor
          ? `${path} was removed from the transaction and remains in the editor; no workspace file changed.`
          : `${path} was removed from the transaction; no workspace file changed.`);
      },
    );
  }

  function clearTransactionDrafts(): void {
    requestDiscard(
      transactionDrafts.length > 0 ? "Discard all staged multi-file drafts?" : null,
      "Clear staged drafts",
      () => {
        if (opened && currentDraftMatchesStage) setDraft(opened.content);
        if (lifecycleMode === "create" && createDraftMatchesStage) resetLifecycleDraft();
        else if (lifecycleMode === "create" && createTransactionSourcePath !== null) setCreateTransactionSourcePath(null);
        setTransactionDrafts([]);
        invalidateTransactionPreview();
        setMessage("");
        setNotice("Cleared the transaction drafts; no workspace file changed.");
      },
    );
  }

  async function createTransactionPreview() {
    const previewTransaction = transport.previewAgentWorkspaceTransaction;
    if (
      !previewTransaction
      || transactionDrafts.length < 2
      || loading
      || transactionBlocked
      || unstagedDirty
      || lifecycleDraftDirty
      || editBlockedReason
    ) return;
    const requestedSession = sessionId;
    const fingerprint = currentTransactionFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewTransaction(
        sessionId,
        {
          changes: transactionDrafts.map(
            ({ operation, path, content, expected_revision, line_ending }) => ({
              operation,
              path,
              content,
              expected_revision,
              line_ending,
            }),
          ),
        },
        controller.signal,
      );
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setTransactionPreview(value);
      setTransactionPreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      invalidateTransactionPreview();
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) {
        setLoading(false);
      }
    }
  }

  async function applyTransaction() {
    const applyTransaction = transport.applyAgentWorkspaceTransaction;
    if (
      !applyTransaction
      || !transactionPreview
      || !transactionPreviewIsCurrent
      || loading
      || transactionBlocked
      || unstagedDirty
      || lifecycleDraftDirty
      || !userPresenceAvailable
      || editBlockedReason
    ) return;
    const requestedSession = sessionId;
    const { controller, version } = beginOperation();
    const drafts = new Map(transactionDrafts.map((item) => [item.path, item]));
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const result = await applyTransaction(
        sessionId,
        transactionPreview,
        {
          changes: transactionPreview.files.map((item) => {
            const staged = drafts.get(item.path);
            if (!staged) throw new Error("transaction draft missing");
            return {
              operation: item.operation,
              path: item.path,
              content: staged.content,
              expected_revision: item.expected_revision,
              proposed_revision: item.proposed_revision,
              line_ending: item.line_ending,
            };
          }),
          confirmation: TRANSACTION_CONFIRMATION,
        },
        controller.signal,
      );
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      invalidateTransactionPreview();
      if (result.state === "committed") {
        const paths = result.files.map((item) => item.path);
        setTransactionDrafts([]);
        setTransactionBlocked(false);
        if (lifecycleMode === "create" && createTransactionSourcePath !== null) resetLifecycleDraft();
        const committedCreates = transactionPreview.files.filter((item) => item.operation === "create").length;
        const committedEdits = result.file_count - committedCreates;
        setNotice(`Committed and verified ${result.file_count} reviewed files as one transaction (${committedCreates} created, ${committedEdits} edited).`);
        if (committedCreates > 0) setTreeRetry((value) => value + 1);
        paths.forEach((path) => onApplied?.(path));
        if (opened && paths.includes(opened.path)) {
          setNeedsFileReload(true);
          try {
            const refreshed = await transport.getAgentWorkspaceFile(sessionId, opened.path, controller.signal);
            if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
            setOpened(refreshed);
            setDraft(refreshed.content);
            setNeedsFileReload(false);
          } catch (caught) {
            if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
            setMessage(caught instanceof TransportError && caught.reasonCode === "workspace_root_changed"
              ? inspectError(caught)
              : "The transaction committed, but the open file could not be read back. Reload it before editing again.");
          }
        }
      } else if (result.state === "unverified") {
        setTransactionBlocked(true);
        setNeedsFileReload(Boolean(opened && result.files.some((item) => item.path === opened.path)));
        setMessage("The transaction outcome is unverified. The staged drafts are preserved for copying; inspect every listed path before any further write.");
      } else {
        setTransactionBlocked(false);
        const restored = result.files.filter((item) => item.state === "restored").length;
        const removed = result.files.filter((item) => item.state === "removed").length;
        const rollbackEvidence = [
          restored > 0 ? `${restored} earlier edit${restored === 1 ? " was" : "s were"} restored` : "",
          removed > 0 ? `${removed} earlier creation${removed === 1 ? " was" : "s were"} removed` : "",
        ].filter(Boolean).join(" and ");
        setMessage(result.state === "rolled_back"
          ? `The transaction did not commit. ${rollbackEvidence}; the staged drafts remain available for review.`
          : "The transaction was rejected before a complete commit. No reviewed file was claimed as changed; the staged drafts remain available.");
      }
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      invalidateTransactionPreview();
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) {
        setLoading(false);
      }
    }
  }

  function startCreate(): void {
    if (!createSupported || loading || unstagedDirty || lifecycleDraftDirty || editBlockedReason || lifecycleBlocked || transactionBlocked) return;
    setLifecycleMode("create");
    setCreatePath(folder === "." ? "" : `${folder}/`);
    setCreateContent("");
    setCreateLineEnding("lf");
    setCreateTransactionSourcePath(null);
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setMessage("");
    setNotice("");
  }

  function startDirectory(): void {
    if (!directoryLifecycleSupported || loading || hasUnsavedWork || editBlockedReason || lifecycleBlocked) return;
    setLifecycleMode("directory");
    setDirectoryPath(folder === "." ? "" : `${folder}/`);
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setCreatePath("");
    setCreateContent("");
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setMessage("");
    setNotice("");
  }

  function startDirectoryMove(): void {
    if (!directoryMoveSupported || folder === "." || loading || hasUnsavedWork || editBlockedReason || lifecycleBlocked) return;
    setLifecycleMode("directory-move");
    setDirectoryMoveTarget(folder);
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setCreatePath("");
    setCreateContent("");
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setMessage("");
    setNotice("");
  }

  function startMove(): void {
    if (!moveLifecycleSupported || !opened || loading || hasUnsavedWork || needsFileReload || editBlockedReason || lifecycleBlocked) return;
    setLifecycleMode("move");
    setMoveTarget(opened.path);
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setCreatePath("");
    setCreateContent("");
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMessage("");
    setNotice("");
  }

  function startTrash(): void {
    if (!fileTrashSupported || !opened || loading || hasUnsavedWork || needsFileReload || editBlockedReason || lifecycleBlocked) return;
    setLifecycleMode("trash");
    setTrashPreview(null);
    setTrashPreviewFingerprint("");
    setCreatePath("");
    setCreateContent("");
    setCreateFilePreview(null);
    setCreatePreviewFingerprint("");
    setDirectoryPath("");
    setDirectoryPreview(null);
    setDirectoryPreviewFingerprint("");
    setDirectoryMoveTarget("");
    setDirectoryMovePreview(null);
    setDirectoryMovePreviewFingerprint("");
    setMoveTarget("");
    setMovePreview(null);
    setMovePreviewFingerprint("");
    setMessage("");
    setNotice("");
  }

  function closeLifecycle(): void {
    requestDiscard(
      lifecycleDraftDirty ? "Discard the pending workspace operation draft?" : null,
      "Discard operation draft",
      resetLifecycleDraft,
    );
  }

  async function reviewCreate(): Promise<void> {
    const previewCreate = transport.previewAgentWorkspaceCreate;
    if (!previewCreate || lifecycleMode !== "create" || loading || lifecycleBlocked || editBlockedReason || unstagedDirty || transactionIsDirty) return;
    if (!isWorkspaceRelativePath(createPath)) {
      setMessage("Enter one workspace-relative file path without a drive, leading slash, backslash, or traversal segment.");
      return;
    }
    const diskContent = effectiveCreateLineEnding === "crlf"
      ? createContent.replaceAll("\n", "\r\n")
      : createContent;
    if (new TextEncoder().encode(diskContent).byteLength > AGENT_WORKSPACE_MAX_FILE_BYTES) {
      setMessage(`The new file exceeds the ${AGENT_WORKSPACE_MAX_FILE_BYTES / 1000} KB review limit.`);
      return;
    }
    const requestedSession = sessionId;
    const fingerprint = createFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewCreate(sessionId, {
        path: createPath,
        content: createContent,
        line_ending: effectiveCreateLineEnding,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setCreateFilePreview(value);
      setCreatePreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setCreateFilePreview(null);
      setCreatePreviewFingerprint("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function applyCreate(): Promise<void> {
    const applyCreate = transport.applyAgentWorkspaceCreate;
    if (!applyCreate || !createFilePreview || !createPreviewIsCurrent || lifecycleMode !== "create" || loading || lifecycleBlocked || transactionIsDirty || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const reviewed = createFilePreview;
    const reviewedContent = createContent;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await applyCreate(sessionId, reviewed, {
        path: reviewed.path,
        content: reviewedContent,
        proposed_revision: reviewed.proposed_revision,
        line_ending: reviewed.line_ending,
        confirmation: CREATE_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      const optimistic: AgentWorkspaceFile = {
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: applied.path,
        content: reviewedContent,
        revision: applied.revision,
        byte_size: applied.byte_size,
        line_ending: reviewed.line_ending,
        editable: true,
      };
      setOpened(optimistic);
      setDraft(reviewedContent);
      setNeedsFileReload(true);
      setFolder(parentFolder(applied.path));
      setTreeRetry((value) => value + 1);
      resetLifecycleDraft();
      setNotice(`Created and verified ${applied.path}. The exact reviewed bytes were published without replacing an existing path.`);
      onApplied?.(applied.path);
      try {
        const refreshed = await transport.getAgentWorkspaceFile(sessionId, applied.path, controller.signal);
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setOpened(refreshed);
        setDraft(refreshed.content);
        setNeedsFileReload(false);
      } catch (caught) {
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setMessage(caught instanceof TransportError && caught.reasonCode === "workspace_root_changed"
          ? inspectError(caught)
          : "The new file was created and verified, but readback failed. Reload it before editing further.");
      }
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setCreateFilePreview(null);
      setCreatePreviewFingerprint("");
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_verification_failed" || reason === "workspace_lifecycle_unverified") {
        setLifecycleBlocked(true);
      }
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function reviewDirectory(): Promise<void> {
    const previewDirectory = transport.previewAgentWorkspaceDirectoryCreate;
    if (!previewDirectory || lifecycleMode !== "directory" || loading || lifecycleBlocked || editBlockedReason || unstagedDirty || transactionIsDirty) return;
    if (!isWorkspaceRelativePath(directoryPath)) {
      setMessage("Enter one workspace-relative folder path without a drive, leading slash, backslash, or traversal segment.");
      return;
    }
    const requestedSession = sessionId;
    const fingerprint = directoryFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewDirectory(sessionId, { path: directoryPath }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryPreview(value);
      setDirectoryPreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryPreview(null);
      setDirectoryPreviewFingerprint("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function applyDirectory(): Promise<void> {
    const applyDirectoryCreate = transport.applyAgentWorkspaceDirectoryCreate;
    if (!applyDirectoryCreate || !directoryPreview || !directoryPreviewIsCurrent || lifecycleMode !== "directory" || loading || lifecycleBlocked || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const reviewed = directoryPreview;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await applyDirectoryCreate(sessionId, reviewed, {
        path: reviewed.path,
        confirmation: DIRECTORY_CREATE_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setFolder(parentFolder(applied.path));
      setTreeRetry((value) => value + 1);
      resetLifecycleDraft();
      setNotice(`Created and verified folder ${applied.path}. Its parent already existed and no existing destination was replaced.`);
      onApplied?.(applied.path);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryPreview(null);
      setDirectoryPreviewFingerprint("");
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_directory_create_unverified" || reason === "workspace_lifecycle_unverified") {
        setLifecycleBlocked(true);
      }
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function reviewDirectoryMove(): Promise<void> {
    const previewDirectoryMove = transport.previewAgentWorkspaceDirectoryMove;
    if (!previewDirectoryMove || lifecycleMode !== "directory-move" || folder === "." || loading || lifecycleBlocked || editBlockedReason || unstagedDirty || transactionIsDirty) return;
    if (!isWorkspaceRelativePath(directoryMoveTarget)) {
      setMessage("Enter one workspace-relative destination without a drive, leading slash, backslash, or traversal segment.");
      return;
    }
    if (directoryMoveTarget === folder) {
      setMessage("Enter a different destination path before reviewing the folder move.");
      return;
    }
    if (directoryMoveTarget.startsWith(`${folder}/`)) {
      setMessage("A folder cannot be moved into itself or one of its own descendants.");
      return;
    }
    const requestedSession = sessionId;
    const fingerprint = directoryMoveFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewDirectoryMove(sessionId, {
        source_path: folder,
        target_path: directoryMoveTarget,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryMovePreview(value);
      setDirectoryMovePreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryMovePreview(null);
      setDirectoryMovePreviewFingerprint("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function applyDirectoryMove(): Promise<void> {
    const applyMove = transport.applyAgentWorkspaceDirectoryMove;
    if (!applyMove || !directoryMovePreview || !directoryMovePreviewIsCurrent || lifecycleMode !== "directory-move" || loading || lifecycleBlocked || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const reviewed = directoryMovePreview;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await applyMove(sessionId, reviewed, {
        source_path: reviewed.source_path,
        target_path: reviewed.target_path,
        confirmation: DIRECTORY_MOVE_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setOpened(null);
      setDraft("");
      setPreview(null);
      setPreviewDraft("");
      setNeedsFileReload(false);
      setFolder(applied.target_path);
      setTreeRetry((value) => value + 1);
      resetLifecycleDraft();
      setNotice(`Moved and verified folder ${applied.source_path} to ${applied.target_path} without overwrite. Its contents moved with the directory but were not enumerated or reviewed.`);
      onApplied?.(applied.target_path);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setDirectoryMovePreview(null);
      setDirectoryMovePreviewFingerprint("");
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_directory_move_unverified" || reason === "workspace_lifecycle_unverified") {
        setLifecycleBlocked(true);
      }
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function reviewMove(): Promise<void> {
    const previewMove = transport.previewAgentWorkspaceMove;
    if (!previewMove || !opened || lifecycleMode !== "move" || loading || lifecycleBlocked || editBlockedReason || unstagedDirty || transactionIsDirty || needsFileReload) return;
    if (!isWorkspaceRelativePath(moveTarget)) {
      setMessage("Enter one workspace-relative destination without a drive, leading slash, backslash, or traversal segment.");
      return;
    }
    if (moveTarget === opened.path) {
      setMessage("Enter a different destination path before reviewing the move.");
      return;
    }
    const requestedSession = sessionId;
    const fingerprint = moveFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewMove(sessionId, {
        source_path: opened.path,
        target_path: moveTarget,
        expected_revision: opened.revision,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setMovePreview(value);
      setMovePreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setMovePreview(null);
      setMovePreviewFingerprint("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function applyMove(): Promise<void> {
    const applyMoveOperation = transport.applyAgentWorkspaceMove;
    if (!applyMoveOperation || !opened || !movePreview || !movePreviewIsCurrent || lifecycleMode !== "move" || loading || lifecycleBlocked || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const reviewed = movePreview;
    const currentContent = opened.content;
    const currentLineEnding = opened.line_ending;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await applyMoveOperation(sessionId, reviewed, {
        source_path: reviewed.source_path,
        target_path: reviewed.target_path,
        expected_revision: reviewed.expected_revision,
        confirmation: MOVE_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setOpened({
        contract_version: "local-agent-workspace.v1",
        session_id: sessionId,
        path: applied.target_path,
        content: currentContent,
        revision: applied.revision,
        byte_size: applied.byte_size,
        line_ending: currentLineEnding,
        editable: true,
      });
      setDraft(currentContent);
      setNeedsFileReload(true);
      setFolder(parentFolder(applied.target_path));
      setTreeRetry((value) => value + 1);
      resetLifecycleDraft();
      setNotice(`Moved and verified ${applied.source_path} → ${applied.target_path}. No existing destination was replaced.`);
      onApplied?.(applied.target_path);
      try {
        const refreshed = await transport.getAgentWorkspaceFile(sessionId, applied.target_path, controller.signal);
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setOpened(refreshed);
        setDraft(refreshed.content);
        setNeedsFileReload(false);
      } catch (caught) {
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setMessage(caught instanceof TransportError && caught.reasonCode === "workspace_root_changed"
          ? inspectError(caught)
          : "The move was applied and verified, but the destination readback failed. Reload it before editing further.");
      }
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setMovePreview(null);
      setMovePreviewFingerprint("");
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_move_unverified" || reason === "workspace_lifecycle_unverified") {
        setLifecycleBlocked(true);
        setNeedsFileReload(true);
      }
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function reviewTrash(): Promise<void> {
    const previewTrash = transport.previewAgentWorkspaceFileTrash;
    if (!previewTrash || !opened || lifecycleMode !== "trash" || loading || lifecycleBlocked || editBlockedReason || unstagedDirty || transactionIsDirty || needsFileReload) return;
    const requestedSession = sessionId;
    const fingerprint = trashFingerprint;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await previewTrash(sessionId, {
        path: opened.path,
        expected_revision: opened.revision,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setTrashPreview(value);
      setTrashPreviewFingerprint(fingerprint);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setTrashPreview(null);
      setTrashPreviewFingerprint("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function applyTrash(): Promise<void> {
    const applyTrashOperation = transport.applyAgentWorkspaceFileTrash;
    if (!applyTrashOperation || !opened || !trashPreview || !trashPreviewIsCurrent || lifecycleMode !== "trash" || loading || lifecycleBlocked || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const reviewed = trashPreview;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await applyTrashOperation(sessionId, reviewed, {
        path: reviewed.path,
        expected_revision: reviewed.expected_revision,
        confirmation: FILE_TRASH_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setOpened(null);
      setDraft("");
      setPreview(null);
      setPreviewDraft("");
      setNeedsFileReload(false);
      setFolder(parentFolder(applied.path));
      setTreeRetry((value) => value + 1);
      resetLifecycleDraft();
      setNotice(`Moved the reviewed bytes from ${applied.path} to Windows Recycle Bin and verified them. Windows may show an app-generated private staging name; permanent deletion was not used.`);
      onApplied?.(applied.path);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setTrashPreview(null);
      setTrashPreviewFingerprint("");
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_file_trash_unverified" || reason === "workspace_lifecycle_unverified") {
        setLifecycleBlocked(true);
        setNeedsFileReload(true);
      }
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) setLoading(false);
    }
  }

  async function createPreview() {
    if (editBlockedReason || transactionBlocked || transactionIsDirty) return;
    if (!opened || !unstagedDirty || loading || needsFileReload) return;
    const requestedSession = sessionId;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const value = await transport.previewAgentWorkspaceEdit(sessionId, {
        path: opened.path,
        content: draft,
        expected_revision: opened.revision,
        line_ending: opened.line_ending,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setPreview(value);
      setPreviewDraft(draft);
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setPreview(null);
      setPreviewDraft("");
      setMessage(inspectError(caught));
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) {
        setLoading(false);
      }
    }
  }

  async function applyPreview() {
    if (!opened || !preview || !previewIsCurrent || loading || needsFileReload || transactionBlocked || transactionIsDirty || !userPresenceAvailable || editBlockedReason) return;
    const requestedSession = sessionId;
    const { controller, version } = beginOperation();
    setLoading(true);
    setMessage("");
    setNotice("");
    try {
      const applied = await transport.applyAgentWorkspaceEdit(sessionId, preview.preview_id, {
        path: preview.path,
        content: draft,
        expected_revision: preview.expected_revision,
        proposed_revision: preview.proposed_revision,
        line_ending: preview.line_ending,
        confirmation: APPLY_CONFIRMATION,
      }, controller.signal);
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      // The validated receipt confirms this exact draft/revision was written.
      // Keep that fact even if the independent readback fails afterwards.
      setOpened({ ...opened, content: draft, revision: applied.revision, byte_size: applied.byte_size });
      setPreview(null);
      setPreviewDraft("");
      setNotice("Applied the reviewed edit. The server atomically published and verified the exact reviewed revision.");
      setNeedsFileReload(true);
      onApplied?.(applied.path);
      try {
        const refreshed = await transport.getAgentWorkspaceFile(sessionId, preview.path, controller.signal);
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setOpened(refreshed);
        setDraft(refreshed.content);
        setNeedsFileReload(false);
      } catch (caught) {
        if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
        setMessage(caught instanceof TransportError && caught.reasonCode === "workspace_root_changed"
          ? inspectError(caught)
          : "The edit was applied, but the current file could not be read back. Reload the file before further edits.");
      }
    } catch (caught) {
      if (activeSession.current !== requestedSession || operationVersion.current !== version) return;
      setPreview(null);
      setPreviewDraft("");
      const status = caught instanceof TransportError ? caught.status : null;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "workspace_write_failed") {
        setNeedsFileReload(false);
        setMessage(friendlyError(caught));
      } else if (reason === "workspace_verification_failed" || reason === "workspace_cleanup_failed" || status === null || status === 200 || status >= 500) {
        setNeedsFileReload(true);
        setMessage(reason === "workspace_verification_failed" || reason === "workspace_cleanup_failed"
          ? friendlyError(caught)
          : "Could not confirm whether the edit was applied. Your draft is kept here; reload the file before another edit.");
      } else {
        setMessage(inspectError(caught));
      }
    } finally {
      if (activeSession.current === requestedSession && operationVersion.current === version) {
        setLoading(false);
      }
    }
  }

  const folderLabel = folder === "." ? "Workspace root" : folder;
  const agentDiffForOpened = opened && pendingPaths.includes(opened.path) ? pendingWrite?.preview : null;
  const summary = useMemo(() => {
    if (!opened) return "Choose an editable UTF-8 file.";
    return `${opened.byte_size.toLocaleString()} bytes · ${opened.line_ending.toUpperCase()} · revision ${opened.revision.slice(0, 8)}`;
  }, [opened]);

  function startArtifactCapture(path: string) {
    if (!artifactCaptureSupported) {
      setMessage("Verified artifact capture is unavailable for this chat or transport.");
      return;
    }
    if (rootChanged) {
      setMessage(ROOT_CHANGED);
      return;
    }
    if (loading) {
      setMessage("Wait for the current workspace read or review to finish before adding an artifact.");
      return;
    }
    if (hasUnsavedWork) {
      setMessage("Save, apply, or discard workspace drafts before capturing the exact on-disk artifact revision.");
      return;
    }
    if (path !== "" && path.endsWith("/")) {
      setMessage("Choose one ordinary workspace file to add as an artifact.");
      return;
    }
    setMessage("");
    setNotice("");
    setArtifactCapturePath(path);
  }

  return (
    <section aria-labelledby="agent-workspace-title" className="agent-workspace">
      <header className="agent-workspace__head">
        <div>
          <p className="eyebrow">Workspace · manual editor</p>
          <h2 id="agent-workspace-title">Files and reviewed changes</h2>
        </div>
        {createSupported && (
          <button
            className="button button--secondary"
            disabled={loading || rootChanged || lifecycleBlocked || transactionBlocked || Boolean(editBlockedReason) || unstagedDirty || lifecycleDraftDirty || lifecycleMode !== null}
            onClick={startCreate}
            type="button"
          >
            New file
          </button>
        )}
        {directoryLifecycleSupported && (
          <button
            className="button button--secondary"
            disabled={loading || rootChanged || lifecycleBlocked || Boolean(editBlockedReason) || hasUnsavedWork || lifecycleMode !== null}
            onClick={startDirectory}
            type="button"
          >
            New folder
          </button>
        )}
        {directoryMoveSupported && folder !== "." && (
          <button
            className="button button--secondary"
            disabled={loading || rootChanged || lifecycleBlocked || Boolean(editBlockedReason) || hasUnsavedWork || lifecycleMode !== null}
            onClick={startDirectoryMove}
            type="button"
          >
            Move folder
          </button>
        )}
        {artifactCaptureSupported && (
          <button
            className="button button--secondary"
            disabled={loading || rootChanged || hasUnsavedWork}
            onClick={() => startArtifactCapture(opened?.path ?? (folder === "." ? "" : `${folder}/`))}
            title={hasUnsavedWork ? "Save or discard workspace drafts before capturing the on-disk revision." : undefined}
            type="button"
          >
            Add output
          </button>
        )}
        <button
          className="button button--ghost"
          disabled={folder === "." || loading || rootChanged}
          onClick={() => openFolder(parentFolder(folder))}
          type="button"
        >
          Up
        </button>
        <button className="button button--ghost" disabled={loading || rootChanged} onClick={() => setTreeRetry((value) => value + 1)} type="button">
          {treeMessage ? "Retry folder" : "Refresh folder"}
        </button>
        {onClose && (
          <button
            className="button button--ghost"
            type="button"
            onClick={() => requestDiscard(allWorkDiscardMessage(), "Discard and hide", onClose)}
          >
            Hide workspace
          </button>
        )}
      </header>
      <details className="agent-workspace__support">
        <summary>
          <span>Workspace tools &amp; safety</span>
          <small>Discovery · content search · Git · reviewed-change limits</small>
        </summary>
        <div className="agent-workspace__support-body">
          <p className="agent-workspace__truth">
            Manual edits, new files, folders, no-overwrite moves, recoverable single-file Recycle Bin removal, and adding an exact generated output require native user-presence confirmation and do not depend on whether the model may write. Output review returns metadata only; artifact capture rechecks the exact file revision. Permanent deletion and directory removal are not available. UTF-8 text editing is bounded to {AGENT_WORKSPACE_MAX_FILE_BYTES / 1000} KB.
          </p>
          <AgentWorkspaceDiscoveryPanel
            fileActionsDisabled={loading || rootChanged}
            onOpenFile={(path) => { void openFile(path); }}
            onRootChanged={markRootChanged}
            refreshKey={refreshKey}
            sessionId={sessionId}
            transport={transport}
          />
        </div>
      </details>

      <div className="agent-workspace__tree" aria-busy={loading} aria-label={folderLabel}>
        <div className="agent-workspace__path"><code>{folderLabel}</code></div>
        {treeLoading && <p className="agent__note" role="status">Loading folder…</p>}
        {treeMessage && <p className="agent__error" role="alert">{treeMessage}</p>}
        {tree?.entries.length === 0 && <p className="agent__note">{tree.complete ? "This folder is empty." : "No entries could be shown; this does not establish that the folder is empty."}</p>}
        {tree && (
          <ul>
            {treeEntries.slice(treePage.start, treePage.end).map((entry) => (
              <li
                aria-current={entry.path === revealedPath ? "location" : undefined}
                data-kind={entry.kind}
                data-revealed={entry.path === revealedPath ? "true" : undefined}
                key={entry.path}
                ref={entry.path === revealedPath ? revealedEntryRef : undefined}
                tabIndex={entry.path === revealedPath ? -1 : undefined}
              >
                {entry.kind === "directory" ? (
                  <button disabled={loading || rootChanged} onClick={() => openFolder(entry.path)} type="button"><Icon name="folder" /><span>{entry.name}</span></button>
                ) : entry.kind === "file" ? (
                  <button
                    aria-label={entry.editable_candidate
                      ? undefined
                      : artifactCaptureSupported
                        ? `${entry.name} — add as generated output; ${nonEditableReason(entry.byte_size)}`
                        : `${entry.name} — ${nonEditableReason(entry.byte_size)}`}
                    disabled={loading || rootChanged || (!entry.editable_candidate && !artifactCaptureSupported)}
                    onClick={() => entry.editable_candidate
                      ? void openFile(entry.path)
                      : startArtifactCapture(entry.path)}
                    type="button"
                  >
                    <Icon name="file" /><span>{entry.name}</span>
                    {!entry.editable_candidate && <small>{artifactCaptureSupported ? "Add as output" : nonEditableReason(entry.byte_size)}</small>}
                  </button>
                ) : (
                  <span role="note"><Icon name="lock" /><span>{entry.name}</span><small>Unavailable — not opened or followed</small></span>
                )}
              </li>
            ))}
          </ul>
        )}
        <BoundedListPager label="Workspace folder pages" page={treePage} />
        {tree && !tree.complete && <p className="agent__note" role="status">This bounded folder view is incomplete; at most the first 400 representable entries are shown.</p>}
      </div>

      {lifecycleMode === "create" && (
        <section aria-label="Create workspace file" className="agent-workspace__lifecycle">
          <header>
            <div>
              <p className="eyebrow">Reviewed creation</p>
              <h3>New UTF-8 text file</h3>
            </div>
            <button className="button button--ghost" disabled={loading} onClick={closeLifecycle} type="button">Cancel</button>
          </header>
          <p>The parent folder must already exist. Review one file directly, or stage it with edits and other creations for one failure-atomic approval. Any destination collision fails closed.</p>
          <label>
            Workspace-relative new file path
            <input
              aria-label="Workspace-relative new file path"
              autoComplete="off"
              disabled={loading || lifecycleBlocked}
              onChange={(event) => { setCreatePath(event.currentTarget.value); setNotice(""); }}
              placeholder={folder === "." ? "src/example.ts" : `${folder}/example.ts`}
              spellCheck={false}
              value={createPath}
            />
          </label>
          <label>
            New file content
            <textarea
              aria-label="New file content"
              disabled={loading || lifecycleBlocked}
              onChange={(event) => { setCreateContent(event.currentTarget.value); setNotice(""); }}
              placeholder="Enter the complete file content"
              rows={8}
              spellCheck={false}
              value={createContent}
            />
          </label>
          <div className="agent-workspace__lifecycle-meta">
            <label>
              Disk line endings
              <select
                aria-label="New file line endings"
                disabled={loading || lifecycleBlocked || !createContent.includes("\n")}
                onChange={(event) => setCreateLineEnding(event.currentTarget.value as "lf" | "crlf")}
                value={createLineEnding}
              >
                <option value="lf">LF</option>
                <option value="crlf">CRLF</option>
              </select>
            </label>
            <small>{new TextEncoder().encode(effectiveCreateLineEnding === "crlf" ? createContent.replaceAll("\n", "\r\n") : createContent).byteLength.toLocaleString()} / {AGENT_WORKSPACE_MAX_FILE_BYTES.toLocaleString()} bytes{effectiveCreateLineEnding === "none" ? " · no line-ending style yet" : ""}</small>
          </div>
          <div className="agent-workspace__actions">
            {createLifecycleSupported && <button className="button button--primary" disabled={!isWorkspaceRelativePath(createPath) || loading || lifecycleBlocked || transactionIsDirty || Boolean(editBlockedReason)} onClick={() => void reviewCreate()} type="button">Review new file</button>}
            {transactionSupported && (
              <button
                className="button button--secondary"
                disabled={!createTransactionStageNeedsUpdate || loading || lifecycleBlocked || transactionBlocked || Boolean(editBlockedReason) || (currentCreateTransactionDraft === null && transactionDrafts.length >= MAX_TRANSACTION_FILES)}
                onClick={stageCreateTransactionDraft}
                type="button"
              >
                {currentCreateTransactionDraft ? "Update staged new file" : "Stage new file in transaction"}
              </button>
            )}
          </div>
          {createDraftMatchesStage && <p className="agent-workspace__inline-note">This new-file draft is already staged. Change it to update the plan, or return to the combined review.</p>}
          {transactionIsDirty && <p className="agent-workspace__inline-note">Single-file creation is paused while a multi-file plan is staged. Stage this file too, or clear the plan first.</p>}
          {createFilePreview && (
            <section aria-label="New file review" className="agent-workspace__review">
              <h3>Review complete creation</h3>
              <AgentDiffViewer diff={createFilePreview.diff} label={`New file diff for ${createFilePreview.path}`} />
              {!createPreviewIsCurrent && <p role="status">The path, content, or line-ending choice changed after this review. Review it again.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--primary" disabled={!createPreviewIsCurrent || loading || lifecycleBlocked || transactionIsDirty || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyCreate()} type="button">Create reviewed file</button>
            </section>
          )}
        </section>
      )}

      {lifecycleMode === "directory" && (
        <section aria-label="Create workspace folder" className="agent-workspace__lifecycle">
          <header>
            <div>
              <p className="eyebrow">Reviewed folder creation</p>
              <h3>New workspace folder</h3>
            </div>
            <button className="button button--ghost" disabled={loading} onClick={closeLifecycle} type="button">Cancel</button>
          </header>
          <p>Create exactly one folder. The parent folder must already exist, and an existing destination is never replaced.</p>
          <label>
            Workspace-relative new folder path
            <input
              aria-label="Workspace-relative new folder path"
              autoComplete="off"
              disabled={loading || lifecycleBlocked}
              onChange={(event) => { setDirectoryPath(event.currentTarget.value); setNotice(""); }}
              placeholder={folder === "." ? "src/new-folder" : `${folder}/new-folder`}
              spellCheck={false}
              value={directoryPath}
            />
          </label>
          <div className="agent-workspace__actions">
            <button className="button button--primary" disabled={!isWorkspaceRelativePath(directoryPath) || loading || lifecycleBlocked || Boolean(editBlockedReason)} onClick={() => void reviewDirectory()} type="button">Review new folder</button>
          </div>
          {directoryPreview && (
            <section aria-label="New folder review" className="agent-workspace__review">
              <h3>Review exact folder creation</h3>
              <dl className="agent-workspace__move-summary">
                <div><dt>New folder</dt><dd>{directoryPreview.path}</dd></div>
                <div><dt>Safety boundary</dt><dd>The parent folder must already exist; no recursive parents or overwrite authority are included.</dd></div>
              </dl>
              {!directoryPreviewIsCurrent && <p role="status">The folder path changed after this review. Review it again.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--primary" disabled={!directoryPreviewIsCurrent || loading || lifecycleBlocked || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyDirectory()} type="button">Create reviewed folder</button>
            </section>
          )}
        </section>
      )}

      {lifecycleMode === "directory-move" && folder !== "." && (
        <section aria-label="Move workspace folder" className="agent-workspace__lifecycle">
          <header>
            <div>
              <p className="eyebrow">Reviewed folder path change</p>
              <h3>Rename or move folder</h3>
            </div>
            <button className="button button--ghost" disabled={loading} onClick={closeLifecycle} type="button">Cancel</button>
          </header>
          <p>This review moves one ordinary folder entry without overwrite. Its entire subtree moves with it, but the app does not enumerate or claim to review those contents.</p>
          <dl className="agent-workspace__move-summary">
            <div><dt>Current folder</dt><dd><code>{folder}</code></dd></div>
            <div><dt>Safety boundary</dt><dd>The destination parent must already exist; the folder cannot move into itself or one of its descendants.</dd></div>
          </dl>
          <label>
            New workspace-relative folder path
            <input
              aria-label="New workspace-relative folder path"
              autoComplete="off"
              disabled={loading || lifecycleBlocked}
              onChange={(event) => { setDirectoryMoveTarget(event.currentTarget.value); setNotice(""); }}
              placeholder={`${parentFolder(folder) === "." ? "" : `${parentFolder(folder)}/`}renamed-folder`}
              spellCheck={false}
              value={directoryMoveTarget}
            />
          </label>
          <div className="agent-workspace__actions">
            <button className="button button--primary" disabled={!isWorkspaceRelativePath(directoryMoveTarget) || directoryMoveTarget === folder || directoryMoveTarget.startsWith(`${folder}/`) || loading || lifecycleBlocked || Boolean(editBlockedReason)} onClick={() => void reviewDirectoryMove()} type="button">Review folder move</button>
          </div>
          {directoryMovePreview && (
            <section aria-label="Folder move review" className="agent-workspace__review">
              <h3>Review exact folder path move</h3>
              <dl className="agent-workspace__move-summary">
                <div><dt>From</dt><dd>{directoryMovePreview.source_path}</dd></div>
                <div><dt>To</dt><dd>{directoryMovePreview.target_path}</dd></div>
                <div><dt>Contents reviewed</dt><dd>No. The subtree moves with the same directory entry but is not enumerated by this review.</dd></div>
              </dl>
              {!directoryMovePreviewIsCurrent && <p role="status">The destination changed after this review. Review both exact paths again.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--primary" disabled={!directoryMovePreviewIsCurrent || loading || lifecycleBlocked || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyDirectoryMove()} type="button">Move reviewed folder</button>
            </section>
          )}
        </section>
      )}

      {lifecycleMode === "move" && opened && (
        <section aria-label="Move workspace file" className="agent-workspace__lifecycle">
          <header>
            <div>
              <p className="eyebrow">Reviewed path change</p>
              <h3>Rename or move file</h3>
            </div>
            <button className="button button--ghost" disabled={loading} onClick={closeLifecycle} type="button">Cancel</button>
          </header>
          <p>The source bytes remain unchanged. The destination parent must exist, and an existing destination is never replaced.</p>
          <dl className="agent-workspace__move-summary">
            <div><dt>Current path</dt><dd><code>{opened.path}</code></dd></div>
            <div><dt>Revision</dt><dd><code>{opened.revision.slice(0, 12)}</code> · {opened.byte_size.toLocaleString()} bytes</dd></div>
          </dl>
          <label>
            New workspace-relative path
            <input
              aria-label="New workspace-relative path"
              autoComplete="off"
              disabled={loading || lifecycleBlocked}
              onChange={(event) => { setMoveTarget(event.currentTarget.value); setNotice(""); }}
              spellCheck={false}
              value={moveTarget}
            />
          </label>
          <div className="agent-workspace__actions">
            <button className="button button--primary" disabled={!isWorkspaceRelativePath(moveTarget) || moveTarget === opened.path || loading || lifecycleBlocked || Boolean(editBlockedReason)} onClick={() => void reviewMove()} type="button">Review move</button>
          </div>
          {movePreview && (
            <section aria-label="File move review" className="agent-workspace__review agent-workspace__move-review">
              <h3>Review exact path change</h3>
              <dl className="agent-workspace__move-summary">
                <div><dt>From</dt><dd>{movePreview.source_path}</dd></div>
                <div><dt>To</dt><dd>{movePreview.target_path}</dd></div>
                <div><dt>Unchanged revision</dt><dd><code>{movePreview.expected_revision.slice(0, 12)}</code> · {movePreview.byte_size.toLocaleString()} bytes</dd></div>
              </dl>
              {!movePreviewIsCurrent && <p role="status">The open file or destination changed after this review. Review the move again.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--primary" disabled={!movePreviewIsCurrent || loading || lifecycleBlocked || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyMove()} type="button">Apply reviewed move</button>
            </section>
          )}
        </section>
      )}

      {lifecycleMode === "trash" && opened && (
        <section aria-label="Move workspace file to Recycle Bin" className="agent-workspace__lifecycle">
          <header>
            <div>
              <p className="eyebrow">Reviewed recoverable removal</p>
              <h3>Move file to Windows Recycle Bin</h3>
            </div>
            <button className="button button--ghost" disabled={loading} onClick={closeLifecycle} type="button">Cancel</button>
          </header>
          <p>This operation covers one exact reviewed UTF-8 file. It does not permanently delete the file, and it includes no directory or subtree authority.</p>
          <dl className="agent-workspace__move-summary">
            <div><dt>Current path</dt><dd><code>{opened.path}</code></dd></div>
            <div><dt>Reviewed revision</dt><dd><code>{opened.revision.slice(0, 12)}</code> · {opened.byte_size.toLocaleString()} bytes</dd></div>
            <div><dt>Recovery location</dt><dd>Windows Recycle Bin</dd></div>
            <div><dt>Permanent deletion</dt><dd>No</dd></div>
          </dl>
          <p className="agent-workspace__inline-note">For a safe rollback window, the app first gives the reviewed bytes a private staging name. Windows Recycle Bin may show that generated name instead of the original filename. Windows owns any later recovery action, so inspect the entry before restoring it.</p>
          <div className="agent-workspace__actions">
            <button className="button button--secondary" disabled={loading || lifecycleBlocked || Boolean(editBlockedReason)} onClick={() => void reviewTrash()} type="button">Review Recycle Bin move</button>
          </div>
          {trashPreview && (
            <section aria-label="Recycle Bin review" className="agent-workspace__review agent-workspace__move-review">
              <h3>Review exact recoverable removal</h3>
              <dl className="agent-workspace__move-summary">
                <div><dt>File</dt><dd>{trashPreview.path}</dd></div>
                <div><dt>Revision</dt><dd><code>{trashPreview.expected_revision.slice(0, 12)}</code> · {trashPreview.byte_size.toLocaleString()} bytes</dd></div>
                <div><dt>Recovery</dt><dd>Windows Recycle Bin</dd></div>
                <div><dt>Recycle Bin name</dt><dd>May be an app-generated private staging name</dd></div>
                <div><dt>Permanent</dt><dd>No</dd></div>
              </dl>
              {!trashPreviewIsCurrent && <p role="status">The open file changed after this review. Review its exact revision again.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--danger-ghost" disabled={!trashPreviewIsCurrent || loading || lifecycleBlocked || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyTrash()} type="button">Move reviewed file to Recycle Bin</button>
            </section>
          )}
        </section>
      )}

      <div className="agent-workspace__editor">
        <div className="agent-workspace__editor-head">
          <strong>{opened?.path ?? "No file open"}</strong>
          <small>{summary}</small>
          {currentDraftMatchesStage && <span className="agent-workspace__staged-badge">Staged in multi-file transaction</span>}
        </div>
        <textarea
          ref={editorRef}
          aria-label="Workspace file editor"
          disabled={!opened || loading}
          readOnly={needsFileReload || Boolean(editBlockedReason)}
          onChange={(event) => {
            setDraft(event.currentTarget.value);
            setNotice("");
          }}
          placeholder="Choose a file from the tree"
          rows={16}
          spellCheck={false}
          value={draft}
        />
        <div className="agent-workspace__actions">
          <button className="button button--primary" disabled={!unstagedDirty || transactionIsDirty || loading || needsFileReload || transactionBlocked || Boolean(editBlockedReason)} onClick={() => void createPreview()} type="button">Review diff</button>
          {transactionSupported && (
            <button
              className="button button--secondary"
              disabled={!transactionStageNeedsUpdate || loading || needsFileReload || transactionBlocked || Boolean(editBlockedReason) || (!currentTransactionDraft && transactionDrafts.length >= MAX_TRANSACTION_FILES)}
              onClick={stageTransactionDraft}
              type="button"
            >
              {currentTransactionDraft ? "Update staged file" : "Stage for multi-file edit"}
            </button>
          )}
          {moveLifecycleSupported && (
            <button
              className="button button--secondary"
              disabled={!opened || loading || needsFileReload || hasUnsavedWork || lifecycleMode !== null || lifecycleBlocked || Boolean(editBlockedReason)}
              onClick={startMove}
              type="button"
            >
              Rename or move
            </button>
          )}
          {fileTrashSupported && (
            <button
              className="button button--danger-ghost"
              disabled={!opened || loading || needsFileReload || hasUnsavedWork || lifecycleMode !== null || lifecycleBlocked || Boolean(editBlockedReason)}
              onClick={startTrash}
              type="button"
            >
              Move to Recycle Bin
            </button>
          )}
          {needsFileReload && opened && <button className="button button--ghost" disabled={loading || rootChanged} onClick={() => void openFile(opened.path, true)} type="button">Reload file</button>}
          <button
            className="button button--ghost"
            disabled={!unstagedDirty || loading}
            onClick={() => requestDiscard(
              unstagedDirty ? "Discard the unsaved manual edit?" : null,
              "Discard manual edit",
              () => {
                if (!opened) return;
                setDraft(currentTransactionDraft?.content ?? opened.content);
                setPreview(null);
                setPreviewDraft("");
              },
            )}
            type="button"
          >
            Discard draft
          </button>
        </div>
        {transactionIsDirty && <p className="agent-workspace__inline-note">Single-file apply is paused while a multi-file plan is staged. Review the whole plan, or clear it first.</p>}
      </div>

      {transactionSupported && (
        <section aria-label="Multi-file transaction" className="agent-workspace__transaction">
          <header>
            <div>
              <p className="eyebrow">Failure-atomic review</p>
              <h3>Multi-file transaction</h3>
            </div>
            <span>{transactionDrafts.length}/{MAX_TRANSACTION_FILES} staged · {transactionCreateCount} create · {transactionEditCount} edit</span>
          </header>
          <p>Stage 2–8 creations and edits, inspect every diff, then approve one bounded transaction. A rejected later write restores earlier edits and removes only creations still owned by this transaction.</p>
          {transactionDrafts.length === 0 ? (
            <p className="agent-workspace__empty-plan">Edit an existing file or start a new file, then stage it to begin a plan.</p>
          ) : (
            <ol className="agent-workspace__transaction-files">
              {transactionDrafts.map((item) => (
                <li key={item.path}>
                  <button aria-label={item.operation === "create" ? `Edit staged new file ${item.path}` : `Open staged file ${item.path}`} className="agent-workspace__transaction-open" onClick={() => openTransactionDraft(item)} type="button">
                    <span className="agent-workspace__transaction-path"><strong>{item.path}</strong><span data-operation={item.operation}>{item.operation}</span></span>
                    <small>{item.operation === "edit" ? `base ${item.expected_revision.slice(0, 8)}` : "new path · collision protected"} · {transactionDraftByteSize(item).toLocaleString()} bytes</small>
                  </button>
                  <button aria-label={`Remove ${item.path} from transaction`} className="button button--ghost" disabled={loading || transactionBlocked} onClick={() => removeTransactionDraft(item.path)} type="button">Remove</button>
                </li>
              ))}
            </ol>
          )}
          {unstagedDirty && transactionDrafts.length > 0 && <p role="status">The open editor has changes that are not in this plan. Stage or discard them before reviewing or applying the transaction.</p>}
          {lifecycleDraftDirty && transactionDrafts.length > 0 && <p role="status">The new-file editor has changes that are not in this plan. Stage or discard them before reviewing or applying the transaction.</p>}
          {transactionBlocked && <p role="alert">This transaction is locked because its last write outcome could not be verified. Copy any draft you need and start a new session after inspecting every listed file.</p>}
          <div className="agent-workspace__actions">
            <button className="button button--primary" disabled={transactionDrafts.length < 2 || unstagedDirty || lifecycleDraftDirty || loading || transactionBlocked || Boolean(editBlockedReason)} onClick={() => void createTransactionPreview()} type="button">
              {transactionDrafts.length >= 2 ? `Review ${transactionDrafts.length}-file transaction` : "Review transaction"}
            </button>
            <button className="button button--ghost" disabled={transactionDrafts.length === 0 || loading || transactionBlocked} onClick={clearTransactionDrafts} type="button">Clear staged drafts</button>
          </div>
          {transactionPreview && (
            <section aria-label="Multi-file transaction review" className="agent-workspace__review agent-workspace__transaction-review">
              <header>
                <div>
                  <h3>Review every file</h3>
                  <p>{transactionPreview.file_count} files · {transactionPreview.files.filter((item) => item.operation === "create").length} create · {transactionPreview.files.filter((item) => item.operation === "edit").length} edit · {transactionPreview.added_lines} addition{transactionPreview.added_lines === 1 ? "" : "s"} · {transactionPreview.removed_lines} removal{transactionPreview.removed_lines === 1 ? "" : "s"} · {transactionPreview.total_byte_size.toLocaleString()} bytes after apply</p>
                </div>
                <span>One approval</span>
              </header>
              <div className="agent-workspace__transaction-diffs">
                {transactionPreview.files.map((item, index) => (
                  <details key={item.path} open={index === 0}>
                    <summary><span>{item.path} <span className="agent-workspace__transaction-operation" data-operation={item.operation}>{item.operation}</span></span><small>+{item.added_lines} −{item.removed_lines}</small></summary>
                    <AgentDiffViewer
                      addedLines={item.added_lines}
                      compact
                      diff={item.diff}
                      label={`Transaction diff for ${item.path}`}
                      removedLines={item.removed_lines}
                    />
                  </details>
                ))}
              </div>
              {!transactionPreviewIsCurrent && <p role="status">The staged plan changed after this review. Create a fresh review before applying.</p>}
              {unstagedDirty && <p role="status">The open editor has unstaged changes. Stage or discard them before applying.</p>}
              {lifecycleDraftDirty && <p role="status">The new-file editor has unstaged changes. Stage or discard them before applying.</p>}
              {!userPresenceAvailable && <p role="status">This review is read-only here because native user-presence confirmation is unavailable.</p>}
              {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
              <button className="button button--primary" disabled={!transactionPreviewIsCurrent || unstagedDirty || lifecycleDraftDirty || loading || transactionBlocked || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyTransaction()} type="button">
                Apply {transactionPreview.file_count}-file transaction
              </button>
            </section>
          )}
        </section>
      )}

      {agentDiffForOpened && (
        <section aria-label="Agent proposed diff" className="agent-workspace__agent-diff">
          <h3>Agent proposal for this file</h3>
          <AgentDiffViewer diff={agentDiffForOpened} label={`Agent proposed diff for ${opened?.path ?? "current file"}`} />
          <p>The agent still needs approval in the conversation. This view does not apply it.</p>
        </section>
      )}

      {preview && (
        <section aria-label="Manual edit review" className="agent-workspace__review">
          <h3>Review manual edit</h3>
          <AgentDiffViewer diff={preview.diff} label={`Manual edit diff for ${preview.path}`} />
          {!previewIsCurrent && <p role="status">The draft changed after this preview. Review a fresh diff before applying.</p>}
          {!userPresenceAvailable && <p role="status">This preview is read-only here because native user-presence confirmation is unavailable.</p>}
          {editBlockedReason && <p role="alert">{editBlockedReason}</p>}
          <button className="button button--primary" disabled={!previewIsCurrent || loading || !userPresenceAvailable || Boolean(editBlockedReason)} onClick={() => void applyPreview()} type="button">Apply reviewed edit</button>
        </section>
      )}

      {message && <p className="agent__error" role="alert">{message}</p>}
      {notice && <p className="agent-workspace__notice" role="status">{notice}</p>}
      <Dialog
        description={discardPrompt?.message}
        initialFocusRef={keepDraftRef}
        onClose={() => finishDiscard(false)}
        open={discardPrompt !== null}
        title="Discard workspace changes?"
        tone="danger"
        footer={(
          <>
            <button className="button button--ghost" onClick={() => finishDiscard(false)} ref={keepDraftRef} type="button">
              Keep draft
            </button>
            <button className="button button--danger-ghost" onClick={() => finishDiscard(true)} type="button">
              {discardPrompt?.confirmLabel ?? "Discard changes"}
            </button>
          </>
        )}
      >
        <p>No workspace file is changed by this confirmation. Only the selected in-memory draft is cleared.</p>
      </Dialog>
      {artifactCaptureSupported && artifactCapturePath !== null && projectId && transport.previewAgentArtifactCapture && transport.captureAgentArtifact && (
        <AgentArtifactCaptureDialog
          initialPath={artifactCapturePath}
          onCaptured={(artifact) => {
            setNotice(`${artifact.title} is now available as a verified chat artifact.`);
            onArtifactCaptured?.();
          }}
          onCaptureUncertain={() => {
            setNotice("Capture outcome is unknown. The saved-artifacts list is refreshing; inspect it before trying again.");
            onCaptureUncertain?.();
          }}
          onClose={() => setArtifactCapturePath(null)}
          open
          projectId={projectId}
          sessionId={sessionId}
          transport={transport as Pick<PromptEnhancerTransport, "previewAgentArtifactCapture" | "captureAgentArtifact">}
          userPresenceAvailable={userPresenceAvailable}
        />
      )}
    </section>
  );
}
