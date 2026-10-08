import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import type { AgentArtifact, AgentArtifactLifecycleCounts, AgentArtifactListView, AgentAttachment, AgentCatalogSession, AgentEvent, AgentEvents, AgentMcpConnectionList, AgentSessionForkReceipt, AgentSessionView, AgentSettings, LocalModelStatus, LocalModelsOverview, LocalRuntimeCoordinatorStatus, PromptCheckResult, PromptEnhancerTransport } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";
import { TabList, tabId, tabPanelId, type TabDescriptor } from "../../shared/ui/Tabs";
import {
  chooseNativeWorkspaceFolder,
  hasNativeWorkspaceFolderPicker,
} from "../../shared/platform/nativeDesktopBridge";
import type { LocalRuntimeTransport } from "../../shared/platform/runtimeMode";
import { TeamFoldersPanel } from "./TeamFoldersPanel";
import { AgentWorkspacePane, type AgentFileOpenRequest } from "./AgentWorkspacePane";
import { AgentSessionEffects } from "./AgentSessionEffects";
import { AgentChangeSetPanel, type AgentChangeReviewRequest } from "./AgentChangeSetPanel";
import type { AgentTurnRevisionMode } from "./AgentTurnDetails";
import { AgentPromptCheckResult, agentPromptContext } from "./AgentPromptCheck";
import { AgentCatalogRail } from "./AgentCatalogRail";
import type { AgentSavedMessageSearchHit } from "./AgentMessageSearchDialog";
import { AgentDiffViewer } from "./AgentDiffViewer";
import { AgentRuntimeControl } from "./AgentRuntimeControl";
import { AgentArtifactsPanel, type AgentArtifactOpenRequest } from "./AgentArtifactsPanel";
import { AgentComposerAttachments } from "./AgentComposerAttachments";
import { AgentConversationHeader } from "./AgentConversationHeader";
import {
  coalesceLiveStreams,
  compactTerminalDeltas,
  RetainedHistoryView,
  TranscriptEventRows,
  type TurnRevisionBusy,
} from "./AgentConversationTimeline";
import { AgentControllerPanel } from "./AgentControllerPanel";
import { AgentNativeAcceptancePanel, type NativeAcceptanceRun } from "./AgentNativeAcceptancePanel";
import { AgentMcpProjectToolsPanel } from "./AgentMcpProjectToolsPanel";
import {
  mcpServerLabel,
  mcpToolLabel,
} from "./AgentMcpToolActivity";
import {
  advanceTrustedMcpAcceptance,
  observeTrustedMcpAgentEvents,
  type TrustedMcpAcceptanceEvidence,
  type TrustedMcpAcceptanceRun,
} from "./trustedMcpAcceptance";
import {
  advanceExternalControllerAcceptance,
  observeExternalControllerAcceptance,
  type ExternalControllerAcceptanceEvidence,
  type ExternalControllerAcceptanceRun,
} from "./externalControllerAcceptance";
import { AgentReadinessPanel } from "./AgentReadinessPanel";
import { AgentReviewDrawer, type AgentReviewView } from "./AgentReviewDrawer";
import {
  announceAgentWindowActiveSession,
  connectAgentCatalogSync,
  connectAgentWindowSelectionOwner,
  listenForAgentWindowSelection,
  openAgentChatWindow,
  readAgentWindowKey,
  type AgentCatalogSync,
  type AgentWindowSelectionOwner,
} from "./agentWindowChannel";
import {
  approvalAction,
  isExternalWriteProposal,
  isExternalWriteTransactionProposal,
  summarizeArguments,
  TOOL_LABELS,
} from "./agentEventPresentation";
import "./AgentPage.css";

const POLL_MS = 700;
const IDLE_POLL_MS = 4000;
const STREAM_RETRY_MS = 350;
const MAX_STREAM_RETRY_MS = 5600;
const MAX_STREAM_FAILURES = 5;

function isLiveUpdateNotice(message: string): boolean {
  return message.startsWith("Live updates ");
}
const MODEL_START_POLL_MS = 1500;
const MAX_MODEL_START_POLLS = 20;
const CONNECTION_POLL_MS = 3000;
const REVIEW_DRAWER_MIN_PX = 352;
const REVIEW_DRAWER_MAX_PX = 760;
const ARTIFACT_SERVER_PAGE = 100;
const CLOSING_SESSION_MESSAGE = "This session is closing and cannot accept new messages. Retry closing after its active action stops, or open a new session.";
const COMMAND_CLEANUP_MESSAGE = "Command processes may still be running. Agent work is paused; inspect those processes before restarting the app. Copy your draft before restarting; it is not saved. Earlier command effects were not undone.";
const EMPTY_DRAFT_ATTACHMENTS: AgentAttachment[] = [];
type ArtifactLifecycleView = Exclude<AgentArtifactListView, "all">;
const AgentMcpStorePanel = lazy(async () => {
  const module = await import("./AgentMcpStorePanel");
  return { default: module.AgentMcpStorePanel };
});

function reconcileAgentEventPage(previous: AgentSessionView, page: AgentEvents): AgentSessionView {
  const latched = {
    ...previous,
    closing: previous.closing || page.closing,
    cleanup_unconfirmed: previous.cleanup_unconfirmed || page.cleanup_unconfirmed,
  };
  if (page.last_seq < previous.last_seq) return latched;
  if (page.last_seq > previous.last_seq) {
    return {
      ...latched,
      running: page.running,
      stopping: page.stopping,
      pending_approval_id: page.pending_approval_id ?? null,
      last_seq: page.last_seq,
    };
  }
  // A session command and its event stream are concurrent. At an equal event
  // head, a page captured before a Stop acknowledgement must not clear the
  // newer `stopping` state, and a pre-turn page must not reopen a settled turn.
  if (!previous.running) return latched;
  if (!page.running) {
    return {
      ...latched,
      running: false,
      stopping: false,
      pending_approval_id: null,
    };
  }
  return {
    ...latched,
    running: true,
    stopping: previous.stopping || page.stopping,
    pending_approval_id: previous.pending_approval_id ?? page.pending_approval_id ?? null,
  };
}

function agentEventPageAdvanced(previous: AgentSessionView, next: AgentSessionView): boolean {
  return next.last_seq > previous.last_seq
    || next.running !== previous.running
    || next.stopping !== previous.stopping
    || next.pending_approval_id !== previous.pending_approval_id
    || next.closing !== previous.closing
    || next.cleanup_unconfirmed !== previous.cleanup_unconfirmed;
}

type SessionComposerDraft = {
  text: string;
  attachments: AgentAttachment[];
};
type UserPresenceState = "checking" | "available" | "unavailable" | "error";
type FolderPickerState = "checking" | "available" | "unavailable";
type AgentConfirmationPrompt = {
  title: string;
  description: string;
  detail: string;
  confirmLabel: string;
};
type TransportSlice = Pick<
  PromptEnhancerTransport,
  "listAgentSessions" | "createAgentSession" | "getAgentSession" | "deleteAgentSession" | "sendAgentMessage" | "getAgentEvents" | "decideAgentApproval" | "stopAgentSession" | "getAgentWorkspaceTree" | "getAgentWorkspaceFile" | "previewAgentWorkspaceEdit" | "applyAgentWorkspaceEdit"
> & Partial<Pick<PromptEnhancerTransport, "streamAgentEvents" | "getAgentChangeSet" | "getAgentChangeDiff" | "previewAgentChangeRestore" | "applyAgentChangeRestore" | "getAgentWorkspaceSearch" | "previewAgentWorkspaceTransaction" | "applyAgentWorkspaceTransaction" | "previewAgentWorkspaceCreate" | "applyAgentWorkspaceCreate" | "previewAgentWorkspaceDirectoryCreate" | "applyAgentWorkspaceDirectoryCreate" | "previewAgentWorkspaceDirectoryMove" | "applyAgentWorkspaceDirectoryMove" | "previewAgentWorkspaceMove" | "applyAgentWorkspaceMove" | "previewAgentWorkspaceFileTrash" | "applyAgentWorkspaceFileTrash" | "getLocalModels" | "activateLocalModel" | "deactivateLocalModel" | "getLocalRuntime" | "switchLocalRuntime" | "stopLocalRuntime" | "getAgentSessionContext" | "checkPrompt" | "getUserPresenceCapability" | "getWorkspaceFolderPickerCapability" | "chooseWorkspaceFolder" | "shareFolder" | "listSharedFolders" | "revokeSharedFolder" | "joinSharedFolder" | "listPeerLinks" | "leavePeerLink" | "pullPeerLink" | "pushPeerLink">>
  & Partial<Pick<PromptEnhancerTransport, "getAgentOrchestration" | "getAgentHardening" | "listAgentMcpConnections" | "getAgentMcpClientSetup" | "listMcpRegistryCatalog" | "getMcpRegistryServerReview" | "listMcpManagedServers" | "getMcpManagedServer" | "getMcpManagedToolSnapshot" | "getMcpManagedHostStatus" | "getMcpManagedHostStartPreview" | "startMcpManagedHost" | "stopMcpManagedHost" | "getMcpManagedProjectRuntime" | "createMcpManagedServer" | "probeMcpManagedServer" | "getMcpManagedLifecyclePreview" | "getMcpManagedLocalConfigurationInspectionPreview" | "inspectMcpManagedLocalConfiguration" | "applyMcpManagedLifecycle" | "getMcpManagedLocalCleanupPreview" | "getMcpManagedLocalUpdatePreview" | "applyMcpManagedLocalUpdate" | "getMcpManagedLocalRollbackPreview" | "applyMcpManagedLocalRollback" | "getMcpManagedLocalRollbackCleanupPreview" | "cleanupMcpManagedLocalRollback" | "getMcpManagedLocalOperationRecoveryPreview" | "recoverMcpManagedLocalOperation" | "completeMcpManagedLocalCleanup" | "setMcpManagedProjectBinding" | "storeMcpManagedSecret" | "removeMcpManagedSecret" | "storeMcpManagedConfiguration" | "removeMcpManagedConfiguration" | "createAgentMcpConnection" | "rotateAgentMcpConnection" | "revokeAgentMcpConnection" | "releaseAgentControllerOwnership" | "beginAgentNativeAcceptance" | "listAgentProjects" | "pageAgentProjects" | "getAgentProject" | "createAgentProject" | "updateAgentProject" | "deleteAgentProject" | "listAgentCatalogSessions" | "pageAgentCatalogSessions" | "getAgentCatalogSession" | "updateAgentCatalogSession" | "deleteAgentCatalogSession" | "switchAgentSessionModel" | "getAgentPersistedEvents" | "forkAgentSession" | "resumeAgentSession" | "exportAgentHistory" | "revalidateAgentAuthority" | "listAgentArtifacts" | "pageAgentArtifacts" | "getAgentArtifact" | "exportAgentArtifact" | "updateAgentArtifact" | "removeAgentArtifact" | "previewAgentArtifactCapture" | "getAgentArtifactDocumentPreview" | "getAgentArtifactContent" | "captureAgentArtifact">>
  & Partial<Pick<PromptEnhancerTransport, "listAgentAttachments" | "stageAgentAttachment" | "deleteAgentAttachment" | "getAgentAttachmentContent">>
  & Partial<Pick<LocalRuntimeTransport, "getRuntimeHealth">>;

type ModelCatalogState = "unavailable" | "loading" | "ready" | "error";
type ModelFeedbackTarget = "selection" | "session";
type ModelActionKind = "start" | "stop" | null;
type SessionLookupState = "idle" | "loading" | "missing" | "error";
type ConnectionState = "unverified" | "checking" | "connected" | "disconnected";
type TurnRevisionOperation = {
  controller: AbortController;
  expectedVisibleSessionId: string;
  owner: number;
};
type AgentSettingsTab = "readiness" | "connections" | "store" | "acceptance" | "sharing";
const AGENT_SETTINGS_TABS: readonly TabDescriptor<AgentSettingsTab>[] = [
  { id: "readiness", label: "Readiness" },
  { id: "connections", label: "Connections" },
  { id: "store", label: "MCP Store" },
  { id: "acceptance", label: "Owner checks" },
  { id: "sharing", label: "Team folders" },
] as const;
type ModelOperationContext = {
  active: boolean;
  readRevision: number;
  action: { alias: string; kind: "start" | "stop" } | null;
  creation: object | null;
  refresh: object | null;
};

function hasDurableAgentCatalog(transport: TransportSlice): boolean {
  return transport.listAgentProjects !== undefined
    && transport.createAgentProject !== undefined
    && transport.updateAgentProject !== undefined
    && transport.deleteAgentProject !== undefined
    && transport.listAgentCatalogSessions !== undefined
    && transport.updateAgentCatalogSession !== undefined
    && transport.deleteAgentCatalogSession !== undefined;
}

function runtimeStateLabel(state: LocalModelStatus["runtime"]["state"]): string {
  return state === "running" ? "running" : state === "starting" ? "starting" : state === "failed" ? "failed" : "stopped";
}

function newForkRequestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function readCompleteRetainedEvents(
  getPage: NonNullable<TransportSlice["getAgentPersistedEvents"]>,
  projectId: string,
  sessionId: string,
  signal: AbortSignal,
): Promise<{ events: AgentEvent[]; head: number }> {
  const retained: AgentEvent[] = [];
  let cursor = 0;
  let head: number | null = null;
  for (let pageNumber = 0; pageNumber < 100; pageNumber += 1) {
    const page = await getPage(projectId, sessionId, cursor, signal);
    if (signal.aborted) throw new DOMException("Turn revision cancelled", "AbortError");
    if (page.session_id !== sessionId) throw new Error("retained_history_session_mismatch");
    if (head === null) head = page.last_seq;
    else if (head !== page.last_seq) throw new Error("retained_history_changed");
    for (const event of page.events) {
      if (event.seq <= cursor || event.seq > head) throw new Error("retained_history_cursor_invalid");
      cursor = event.seq;
      retained.push(event);
    }
    if (cursor >= head) return { events: retained, head };
    if (page.events.length === 0) throw new Error("retained_history_cursor_stalled");
  }
  throw new Error("retained_history_page_limit");
}

/**
 * Agent workspace: a local model works inside one folder through tools. Reads
 * are free; enabled protected actions pause for your
 * approval. Each chat explicitly chooses metadata-only or bounded local
 * history retention; approvals and reusable mutation authority never persist.
 */
export function AgentPage({
  sessionId,
  transport,
  windowMode = false,
}: {
  sessionId?: string;
  transport: TransportSlice;
  windowMode?: boolean;
}) {
  const durableCatalogAvailable = hasDurableAgentCatalog(transport);
  const dedicatedWindowKey = useMemo(() => windowMode ? readAgentWindowKey() : null, [windowMode]);
  const [windowTargetSessionId, setWindowTargetSessionId] = useState(sessionId);
  const requestedSessionId = windowMode ? windowTargetSessionId : sessionId;
  const [sessions, setSessions] = useState<AgentSessionView[] | null>(null);
  const [sessionListError, setSessionListError] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    transport.getRuntimeHealth === undefined ? "unverified" : "checking",
  );
  const [current, setCurrent] = useState<AgentSessionView | null>(null);
  const [selectedCatalogSession, setSelectedCatalogSession] = useState<AgentCatalogSession | null>(null);
  const [savedHistoryState, setSavedHistoryState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [savedHistoryMessage, setSavedHistoryMessage] = useState("");
  const [resumeBusy, setResumeBusy] = useState(false);
  const [forkBusy, setForkBusy] = useState(false);
  const [turnRevisionBusy, setTurnRevisionBusy] = useState<TurnRevisionBusy | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [selectedArtifactExtra, setSelectedArtifactExtra] = useState<AgentArtifact | null>(null);
  const [artifactCounts, setArtifactCounts] = useState<AgentArtifactLifecycleCounts | null>(null);
  const [artifactView, setArtifactView] = useState<ArtifactLifecycleView>("active");
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState("");
  const [artifactPageError, setArtifactPageError] = useState("");
  const [artifactPageLoading, setArtifactPageLoading] = useState(false);
  const [artifactSnapshot, setArtifactSnapshot] = useState<string | null>(null);
  const [artifactNextOffset, setArtifactNextOffset] = useState<number | null>(null);
  const [artifactsRefreshKey, setArtifactsRefreshKey] = useState(0);
  const [artifactOpenRequest, setArtifactOpenRequest] = useState<AgentArtifactOpenRequest | null>(null);
  const [artifactTurnFocus, setArtifactTurnFocus] = useState<{ requestId: number; turnId: string } | null>(null);
  const [savedMessageFocus, setSavedMessageFocus] = useState<{
    requestId: number;
    eventSeq: number;
    sessionId: string;
    projectId: string;
  } | null>(null);
  const [retainedHistoryReloadKey, setRetainedHistoryReloadKey] = useState(0);
  const [artifactViewRevision, setArtifactViewRevision] = useState(0);
  const [nativeAcceptanceRun, setNativeAcceptanceRun] = useState<NativeAcceptanceRun | null>(null);
  const [trustedMcpAcceptanceRun, setTrustedMcpAcceptanceRun] = useState<TrustedMcpAcceptanceRun | null>(null);
  const [externalControllerAcceptanceRun, setExternalControllerAcceptanceRun] = useState<ExternalControllerAcceptanceRun | null>(null);
  const recordTrustedMcpAcceptanceEvidence = useCallback((evidence: TrustedMcpAcceptanceEvidence) => {
    setTrustedMcpAcceptanceRun((run) => advanceTrustedMcpAcceptance(run, evidence));
  }, []);
  const observeExternalControllerEvidence = useCallback((catalog: AgentMcpConnectionList) => {
    setExternalControllerAcceptanceRun((run) => observeExternalControllerAcceptance(run, catalog));
  }, []);
  const recordExternalControllerEvidence = useCallback((evidence: ExternalControllerAcceptanceEvidence) => {
    setExternalControllerAcceptanceRun((run) => advanceExternalControllerAcceptance(run, evidence));
  }, []);
  const artifactTurnFocusSequence = useRef(0);
  const savedMessageFocusSequence = useRef(0);
  const savedMessageFocusTarget = useRef<{
    sessionId: string;
    projectId: string;
    historyRevision: number;
    eventSeq: number;
    role: "user" | "assistant";
  } | null>(null);
  const artifactReadOwnerRef = useRef(0);
  const artifactPageControllerRef = useRef<AbortController | null>(null);
  const artifactServerIdsRef = useRef(new Set<string>());
  const artifactViewerTransport = useMemo(() => (
    transport.getAgentArtifact !== undefined
      && transport.getAgentArtifactContent !== undefined
      && transport.removeAgentArtifact !== undefined
      && transport.updateAgentArtifact !== undefined
      ? {
          exportAgentArtifact: transport.exportAgentArtifact,
          getAgentArtifact: transport.getAgentArtifact,
          getAgentArtifactDocumentPreview: transport.getAgentArtifactDocumentPreview,
          getAgentArtifactContent: transport.getAgentArtifactContent,
          removeAgentArtifact: transport.removeAgentArtifact,
          updateAgentArtifact: transport.updateAgentArtifact,
        }
      : null
  ), [transport]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
  const catalogSyncRef = useRef<AgentCatalogSync | null>(null);
  const windowSelectionOwnerRef = useRef<AgentWindowSelectionOwner | null>(null);
  const refreshAgentCatalog = useCallback(() => {
    setCatalogRefreshKey((value) => value + 1);
    catalogSyncRef.current?.notify();
  }, []);
  const handleCatalogProjectChange = useCallback((projectId: string | null) => {
    setSelectedProjectId(projectId);
    setSelectedCatalogSession(null);
  }, []);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [newChatOpen, setNewChatOpen] = useState(!windowMode && !durableCatalogAvailable);
  const [startupCatalogSession, setStartupCatalogSession] = useState<AgentCatalogSession | null | undefined>(undefined);
  const startupCatalogHandled = useRef(windowMode || !durableCatalogAvailable);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<AgentSettingsTab>("readiness");
  const [mcpProjectionRevision, setMcpProjectionRevision] = useState(0);
  const refreshMcpProjection = useCallback(() => {
    setMcpProjectionRevision((value) => value + 1);
  }, []);
  const openMcpStore = useCallback(() => {
    setRailCollapsed(false);
    setNewChatOpen(false);
    setSettingsTab("store");
    setSettingsOpen(true);
  }, []);
  const openProjectTools = useCallback(() => {
    setNewChatOpen(false);
    setSettingsTab("connections");
    setSettingsOpen(true);
  }, []);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewView, setReviewView] = useState<AgentReviewView>("files");
  const [reviewWidth, setReviewWidth] = useState(520);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const activeEventHead = useMemo(
    () => events.reduce((head, event) => Math.max(head, event.seq), 0),
    [events],
  );
  const [models, setModels] = useState<LocalModelsOverview | null>(null);
  const [modelCatalogState, setModelCatalogState] = useState<ModelCatalogState>(
    transport.getLocalModels === undefined ? "unavailable" : "loading",
  );
  const [modelActionAlias, setModelActionAlias] = useState("");
  const [modelActionKind, setModelActionKind] = useState<ModelActionKind>(null);
  const [modelRefreshBusy, setModelRefreshBusy] = useState(false);
  const [runtimeControlBusy, setRuntimeControlBusy] = useState(false);
  const [runtimeCoordinator, setRuntimeCoordinator] = useState<LocalRuntimeCoordinatorStatus | null>(null);
  const [runtimeFocusRequest, setRuntimeFocusRequest] = useState(0);
  const [modelFeedbackTarget, setModelFeedbackTarget] = useState<ModelFeedbackTarget>("selection");
  const [modelNotice, setModelNotice] = useState("");
  const [modelError, setModelError] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [workspaceError, setWorkspaceError] = useState("");
  const [nativeFolderPickerAvailable, setNativeFolderPickerAvailable] = useState(
    hasNativeWorkspaceFolderPicker,
  );
  const [serverFolderPickerState, setServerFolderPickerState] = useState<FolderPickerState>(
    transport.getWorkspaceFolderPickerCapability !== undefined
      && transport.chooseWorkspaceFolder !== undefined
      ? "checking"
      : "unavailable",
  );
  const [folderPickerBusy, setFolderPickerBusy] = useState(false);
  const [folderPickerNotice, setFolderPickerNotice] = useState("");
  const [newSessionModelAlias, setNewSessionModelAlias] = useState("");
  const [allowWrites, setAllowWrites] = useState(false);
  const [allowCommands, setAllowCommands] = useState(false);
  const [retainHistory, setRetainHistory] = useState(true);
  const [recoveryAllowWrites, setRecoveryAllowWrites] = useState(false);
  const [recoveryAllowCommands, setRecoveryAllowCommands] = useState(false);
  const [authorityBusy, setAuthorityBusy] = useState(false);
  const [temperature, setTemperature] = useState(0.2);
  const [topP, setTopP] = useState(0.95);
  const [maxTokens, setMaxTokens] = useState(1400);
  const [thinking, setThinking] = useState(false);
  const [instructions, setInstructions] = useState("");
  // Keep unsent content scoped to this mounted window and exact chat. Browser
  // storage would turn private drafts into a second, ungoverned history store.
  const [composerDrafts, setComposerDrafts] = useState<Record<string, SessionComposerDraft>>({});
  const activeComposerDraft = current === null ? undefined : composerDrafts[current.session_id];
  const draft = activeComposerDraft?.text ?? "";
  const draftAttachments = activeComposerDraft?.attachments ?? EMPTY_DRAFT_ATTACHMENTS;
  const draftSessionIds = useMemo(() => new Set(
    Object.entries(composerDrafts)
      .filter(([, value]) => value.text.length > 0 || value.attachments.length > 0)
      .map(([id]) => id),
  ), [composerDrafts]);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const [promptCheckBusy, setPromptCheckBusy] = useState(false);
  const [promptCheckError, setPromptCheckError] = useState("");
  const [promptCheckNotice, setPromptCheckNotice] = useState("");
  const [promptCheckResult, setPromptCheckResult] = useState<PromptCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [createMessage, setCreateMessage] = useState("");
  const [conversationMessage, setConversationMessage] = useState("");
  const [windowOpenBusy, setWindowOpenBusy] = useState(false);
  const [stopPending, setStopPending] = useState<{ controller: AbortController; contextVersion: number; sessionId: string } | null>(null);
  const stopRequest = useRef<typeof stopPending>(null);
  const [sessionLookupState, setSessionLookupState] = useState<SessionLookupState>(requestedSessionId ? "loading" : "idle");
  const [streamNotice, setStreamNotice] = useState("");
  const [streamRetryNonce, setStreamRetryNonce] = useState(0);
  const [followingOutput, setFollowingOutput] = useState(true);
  const [composerFocusNonce, setComposerFocusNonce] = useState(0);
  const [historyGap, setHistoryGap] = useState(false);
  const [workspaceDirty, setWorkspaceDirty] = useState(false);
  const [confirmationPrompt, setConfirmationPrompt] = useState<AgentConfirmationPrompt | null>(null);
  const [changeSetRevision, setChangeSetRevision] = useState(0);
  const [workspaceFileRequest, setWorkspaceFileRequest] = useState<(AgentFileOpenRequest & { transport: TransportSlice }) | null>(null);
  const [changeReviewRequest, setChangeReviewRequest] = useState<(AgentChangeReviewRequest & { transport: TransportSlice }) | null>(null);
  const fileRequestSequence = useRef(0);
  const changeReviewSequence = useRef(0);
  const artifactOpenSequence = useRef(0);
  const lastSelectedLiveSessionId = useRef<string | null>(null);
  const pendingForkRequest = useRef<{ key: string; requestId: string } | null>(null);
  const forkOperation = useRef<{ controller: AbortController; owner: number } | null>(null);
  const forkOwner = useRef(0);
  const turnRevisionOperation = useRef<TurnRevisionOperation | null>(null);
  const turnRevisionOwner = useRef(0);
  const exportOperation = useRef<{ controller: AbortController; owner: number; key: string } | null>(null);
  const exportOwner = useRef(0);
  const reviewResizeCleanup = useRef<(() => void) | null>(null);
  const [userPresenceState, setUserPresenceState] = useState<UserPresenceState>(
    transport.getUserPresenceCapability === undefined ? "unavailable" : "checking",
  );
  const [userPresenceRetryNonce, setUserPresenceRetryNonce] = useState(0);
  const lastSeq = useRef(0);
  const logRef = useRef<HTMLDivElement | null>(null);
  const approvalRef = useRef<HTMLDivElement | null>(null);
  const workspaceInputRef = useRef<HTMLInputElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const settingsButtonRef = useRef<HTMLButtonElement | null>(null);
  const newChatTriggerRef = useRef<HTMLButtonElement | null>(null);
  const keepConfirmationRef = useRef<HTMLButtonElement | null>(null);
  const confirmationResolver = useRef<((accepted: boolean) => void) | null>(null);
  const modelStartPolls = useRef(0);
  const followOutput = useRef(true);
  const promptCheckController = useRef<AbortController | null>(null);
  const modelContext = useMemo<ModelOperationContext>(() => ({
    active: false, readRevision: 0, action: null, creation: null, refresh: null,
  }), [transport]);
  const currentModelContext = useRef(modelContext);
  currentModelContext.current = modelContext;
  const ownsModelContext = useCallback((context: ModelOperationContext) => (
    context.active && currentModelContext.current === context
  ), []);
  const closingSessions = useRef({ transport, ids: new Set<string>(), cleanupIds: new Set<string>(), cleanup: false });
  const closeRequests = useRef(new Set<string>());
  if (closingSessions.current.transport !== transport) closingSessions.current = { transport, ids: new Set(), cleanupIds: new Set(), cleanup: false };
  const commandCleanupBlocked = closingSessions.current.cleanup || Boolean(current?.cleanup_unconfirmed || sessions?.some((view) => view.cleanup_unconfirmed));
  const sessionContext = useRef({ id: current?.session_id, transport, version: 0 });
  if (sessionContext.current.id !== current?.session_id || sessionContext.current.transport !== transport) {
    sessionContext.current = { id: current?.session_id, transport, version: sessionContext.current.version + 1 };
  }
  const selectedCatalogSessionRef = useRef(selectedCatalogSession);
  selectedCatalogSessionRef.current = selectedCatalogSession;
  useEffect(() => () => { sessionContext.current.version += 1; }, []);
  useEffect(() => () => reviewResizeCleanup.current?.(), []);
  useEffect(() => {
    setConfirmationPrompt(null);
    return () => {
      const resolve = confirmationResolver.current;
      confirmationResolver.current = null;
      resolve?.(false);
    };
  }, [transport]);

  useEffect(() => {
    forkOwner.current += 1;
    forkOperation.current?.controller.abort();
    forkOperation.current = null;
    setForkBusy(false);
    return () => {
      forkOwner.current += 1;
      forkOperation.current?.controller.abort();
      forkOperation.current = null;
    };
  }, [transport]);

  useEffect(() => {
    turnRevisionOwner.current += 1;
    turnRevisionOperation.current?.controller.abort();
    turnRevisionOperation.current = null;
    setTurnRevisionBusy(null);
    return () => {
      turnRevisionOwner.current += 1;
      turnRevisionOperation.current?.controller.abort();
      turnRevisionOperation.current = null;
    };
  }, [transport]);

  useEffect(() => {
    const operation = turnRevisionOperation.current;
    if (operation === null) return;
    const visibleSessionId = current?.session_id ?? selectedCatalogSession?.session_id ?? "";
    if (visibleSessionId === operation.expectedVisibleSessionId) return;
    turnRevisionOwner.current += 1;
    operation.controller.abort();
    turnRevisionOperation.current = null;
    setTurnRevisionBusy(null);
  }, [current?.session_id, selectedCatalogSession?.session_id]);

  useEffect(() => {
    exportOwner.current += 1;
    exportOperation.current?.controller.abort();
    exportOperation.current = null;
    setExportBusy(false);
    return () => {
      exportOwner.current += 1;
      exportOperation.current?.controller.abort();
      exportOperation.current = null;
    };
  }, [transport]);

  const selectedExportKey = selectedCatalogSession?.retention_policy === "local_history"
    ? [
        selectedCatalogSession.project_id,
        selectedCatalogSession.session_id,
        selectedCatalogSession.revision,
        selectedCatalogSession.history_revision,
      ].join(":")
    : null;
  useEffect(() => {
    const operation = exportOperation.current;
    if (operation === null || operation.key === selectedExportKey) return;
    exportOwner.current += 1;
    operation.controller.abort();
    exportOperation.current = null;
    setExportBusy(false);
  }, [selectedExportKey]);

  const requestConfirmation = useCallback((prompt: AgentConfirmationPrompt): Promise<boolean> => {
    if (confirmationResolver.current !== null) return Promise.resolve(false);
    return new Promise<boolean>((resolve) => {
      confirmationResolver.current = resolve;
      setConfirmationPrompt(prompt);
    });
  }, []);

  const finishConfirmation = useCallback((accepted: boolean): void => {
    const resolve = confirmationResolver.current;
    confirmationResolver.current = null;
    setConfirmationPrompt(null);
    resolve?.(accepted);
  }, []);

  const replaceComposerDraft = useCallback((sessionId: string, next: SessionComposerDraft) => {
    setComposerDrafts((previous) => {
      if (next.text.length === 0 && next.attachments.length === 0) {
        if (previous[sessionId] === undefined) return previous;
        const remaining = { ...previous };
        delete remaining[sessionId];
        return remaining;
      }
      const existing = previous[sessionId];
      if (existing?.text === next.text && existing.attachments === next.attachments) return previous;
      return { ...previous, [sessionId]: next };
    });
  }, []);

  const discardComposerDraft = useCallback((sessionId: string) => {
    setComposerDrafts((previous) => {
      if (previous[sessionId] === undefined) return previous;
      const remaining = { ...previous };
      delete remaining[sessionId];
      return remaining;
    });
  }, []);

  const clearSentComposerDraft = useCallback((
    sessionId: string,
    sentText: string,
    sentAttachmentIds: readonly string[],
  ) => {
    setComposerDrafts((previous) => {
      const existing = previous[sessionId];
      if (
        existing === undefined
        || existing.text !== sentText
        || existing.attachments.length !== sentAttachmentIds.length
        || existing.attachments.some((attachment, index) => attachment.attachment_id !== sentAttachmentIds[index])
      ) return previous;
      const remaining = { ...previous };
      delete remaining[sessionId];
      return remaining;
    });
  }, []);
  useEffect(() => {
    if (!current) {
      lastSelectedLiveSessionId.current = null;
      return;
    }
    if (lastSelectedLiveSessionId.current !== current.session_id) {
      setNewChatOpen(false);
      lastSelectedLiveSessionId.current = current.session_id;
    }
    setSelectedCatalogSession(null);
    if (current.settings.project_id) setSelectedProjectId(current.settings.project_id);
  }, [current?.session_id, current?.settings.project_id]);
  useEffect(() => {
    const contextVersion = sessionContext.current.version;
    return () => {
      if (stopRequest.current?.contextVersion === contextVersion) {
        stopRequest.current.controller.abort();
        stopRequest.current = null;
      }
    };
  }, [transport, current?.session_id]);
  const responseStopping = Boolean(current?.stopping || (stopPending?.sessionId === current?.session_id
    && stopPending?.contextVersion === sessionContext.current.version));

  useEffect(() => {
    modelContext.active = true;
    setModels(null);
    setModelCatalogState(transport.getLocalModels === undefined ? "unavailable" : "loading");
    setModelActionAlias("");
    setModelActionKind(null);
    setModelRefreshBusy(false);
    setModelNotice("");
    setModelError("");
    setCreatingSession(false);
    setCreateMessage("");
    setBusy(false);
    return () => {
      modelContext.active = false;
      modelContext.readRevision += 1;
      modelContext.action = null;
      modelContext.creation = null;
      modelContext.refresh = null;
    };
  }, [modelContext, transport]);

  const rememberClosing = useCallback((view: AgentSessionView): AgentSessionView => {
    if (view.closing) closingSessions.current.ids.add(view.session_id);
    if (view.cleanup_unconfirmed) {
      closingSessions.current.cleanup = true;
      closingSessions.current.cleanupIds.add(view.session_id);
      closingSessions.current.ids.add(view.session_id);
    }
    if (closingSessions.current.cleanupIds.has(view.session_id)) return { ...view, cleanup_unconfirmed: true, closing: true, pending_approval_id: null };
    return closingSessions.current.ids.has(view.session_id) ? { ...view, closing: true } : view;
  }, [transport]);

  const acceptRuntimeSessionUpdate = useCallback((view: AgentSessionView) => {
    const next = rememberClosing(view);
    setCurrent((previous) => previous?.session_id === next.session_id ? next : previous);
    setSessions((previous) => previous?.map((session) => (
      session.session_id === next.session_id ? next : session
    )) ?? null);
    refreshAgentCatalog();
  }, [refreshAgentCatalog, rememberClosing]);

  const acceptCatalogSessionUpdate = useCallback((record: AgentCatalogSession) => {
    const applyCatalogUpdate = (view: AgentSessionView): AgentSessionView => (
      view.session_id === record.session_id
        ? {
          ...view,
          settings: {
            ...view.settings,
            project_id: record.project_id,
            title: record.title,
          },
        }
        : view
    );
    const openHere = sessionContext.current.id === record.session_id
      || selectedCatalogSessionRef.current?.session_id === record.session_id;
    setCurrent((previous) => previous === null ? null : applyCatalogUpdate(previous));
    setSessions((previous) => previous?.map(applyCatalogUpdate) ?? null);
    setSelectedCatalogSession((previous) => (
      previous?.session_id === record.session_id ? record : previous
    ));
    if (openHere) setSelectedProjectId(record.project_id);
  }, []);

  const acceptCatalogSessionDeleted = useCallback((sessionId: string) => {
    discardComposerDraft(sessionId);
    if (selectedCatalogSessionRef.current?.session_id !== sessionId) return;
    selectedCatalogSessionRef.current = null;
    setSelectedCatalogSession(null);
    setSavedHistoryState("idle");
    setSavedHistoryMessage("");
    setEvents([]);
    setHistoryGap(false);
    setStreamNotice("");
    setConversationMessage("");
    setArtifacts([]);
    setArtifactCounts(null);
    setArtifactsLoading(false);
    setArtifactsError("");
    lastSeq.current = 0;
    if (windowMode) setWindowTargetSessionId(undefined);
  }, [discardComposerDraft, windowMode]);

  const noteRuntimeModelSelection = useCallback((_alias: string) => {
    // Runtime selection belongs to the active chat. Do not leak it into the
    // next New session, whose default is deliberately model-neutral.
    setModelFeedbackTarget("session");
    setModelError("");
    setModelNotice("");
  }, []);

  const markCommandCleanup = useCallback((id?: string) => {
    closingSessions.current.cleanup = true;
    if (id) {
      closingSessions.current.cleanupIds.add(id);
      closingSessions.current.ids.add(id);
    }
    setCurrent((previous) => previous ? { ...previous, cleanup_unconfirmed: true, closing: true, pending_approval_id: null } : previous);
    setSessions((previous) => previous?.map((view) => ({ ...view, cleanup_unconfirmed: true, closing: true, pending_approval_id: null })) ?? null);
    setCreateMessage("");
  }, []);

  const markSessionClosing = useCallback((id: string) => {
    closingSessions.current.ids.add(id);
    setCurrent((previous) => previous?.session_id === id ? { ...previous, closing: true } : previous);
    setSessions((previous) => previous?.map((view) => view.session_id === id ? { ...view, closing: true } : view) ?? null);
  }, []);

  const clearPromptCheck = useCallback((notice = "") => {
    promptCheckController.current?.abort();
    promptCheckController.current = null;
    setPromptCheckBusy(false);
    setPromptCheckError("");
    setPromptCheckNotice(notice);
    setPromptCheckResult(null);
  }, []);

  const refreshSessions = useCallback(async (signal?: AbortSignal) => {
    try {
      const list = await transport.listAgentSessions(signal);
      if (signal?.aborted || sessionContext.current.transport !== transport) return;
      const next = list.map(rememberClosing);
      setSessions(next);
      setCurrent((previous) => {
        if (previous === null) return previous;
        return next.find((session) => session.session_id === previous.session_id) ?? previous;
      });
      setSessionListError(false);
      setUnavailable(false);
    } catch (caught) {
      if (signal?.aborted || sessionContext.current.transport !== transport) return;
      if (caught instanceof TransportError && caught.status === 404) setUnavailable(true);
      else {
        setSessionListError(true);
        setSessions((previous) => previous ?? []);
      }
    }
  }, [rememberClosing, transport]);

  useEffect(() => {
    const sync = connectAgentCatalogSync(() => {
      setCatalogRefreshKey((value) => value + 1);
      void refreshSessions();
    });
    catalogSyncRef.current = sync;
    return () => {
      if (catalogSyncRef.current === sync) catalogSyncRef.current = null;
      sync.close();
    };
  }, [refreshSessions]);

  useEffect(() => {
    if (windowMode) return;
    const owner = connectAgentWindowSelectionOwner();
    windowSelectionOwnerRef.current = owner;
    return () => {
      if (windowSelectionOwnerRef.current === owner) windowSelectionOwnerRef.current = null;
      owner.close();
    };
  }, [windowMode]);

  const refreshModels = useCallback(async (signal?: AbortSignal): Promise<LocalModelsOverview | null | undefined> => {
    if (!ownsModelContext(modelContext)) return undefined;
    const revision = ++modelContext.readRevision;
    // A superseded read is not a current failure. Commands invalidate reads
    // both when admitted and when settled, including reads made during them.
    const ownsRead = () => ownsModelContext(modelContext) && !signal?.aborted
      && revision === modelContext.readRevision && modelContext.action === null;
    const getLocalModels = transport.getLocalModels;
    if (getLocalModels === undefined) {
      setModelCatalogState("unavailable");
      return null;
    }
    try {
      const value = await getLocalModels(signal);
      if (!ownsRead()) return undefined;
      setModels(value);
      setModelCatalogState("ready");
      return value;
    } catch {
      if (!ownsRead()) return undefined;
      setModelCatalogState("error");
      return null;
    }
  }, [modelContext, ownsModelContext, transport]);

  useEffect(() => {
    const controller = new AbortController();
    void refreshSessions(controller.signal);
    void refreshModels(controller.signal);
    return () => controller.abort();
  }, [refreshModels, refreshSessions]);

  useEffect(() => {
    const getRuntimeHealth = transport.getRuntimeHealth;
    if (getRuntimeHealth === undefined) {
      setConnectionState("unverified");
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    let handle = 0;
    let wasDisconnected = false;

    const check = async () => {
      try {
        await getRuntimeHealth(controller.signal);
        if (cancelled) return;
        const recovered = wasDisconnected;
        wasDisconnected = false;
        setConnectionState("connected");
        if (recovered) {
          void refreshSessions();
          void refreshModels();
        }
      } catch {
        if (cancelled || controller.signal.aborted) return;
        wasDisconnected = true;
        setConnectionState("disconnected");
      }
      if (!cancelled) handle = window.setTimeout(() => { void check(); }, CONNECTION_POLL_MS);
    };

    void check();
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(handle);
    };
  }, [refreshModels, refreshSessions, transport.getRuntimeHealth]);

  useEffect(() => {
    if (transport.getLocalModels === undefined) return;
    const handleFocus = () => { void refreshModels(); };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [refreshModels, transport.getLocalModels]);

  useEffect(() => {
    const hasStartingModel = modelCatalogState === "ready"
      && (models?.models ?? []).some((model) => model.runtime.state === "starting");
    if (!hasStartingModel) {
      modelStartPolls.current = 0;
      return;
    }
    if (modelStartPolls.current >= MAX_MODEL_START_POLLS) return;
    const handle = window.setTimeout(() => {
      modelStartPolls.current += 1;
      void refreshModels();
    }, MODEL_START_POLL_MS);
    return () => window.clearTimeout(handle);
  }, [modelCatalogState, models, refreshModels]);

  useEffect(() => {
    const getCapability = transport.getUserPresenceCapability;
    if (getCapability === undefined) {
      setUserPresenceState("unavailable");
      setAllowWrites(false);
      setAllowCommands(false);
      return;
    }
    const controller = new AbortController();
    setUserPresenceState("checking");
    getCapability(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        const available = value.contract_version === "native-user-presence-capability-v1"
          && value.confirmation_available === true
          && value.mode === "native_bridge_bound_token";
        setUserPresenceState(available ? "available" : "unavailable");
        if (!available) {
          setAllowWrites(false);
          setAllowCommands(false);
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setUserPresenceState("error");
        setAllowWrites(false);
        setAllowCommands(false);
      });
    return () => controller.abort();
  }, [transport, userPresenceRetryNonce]);

  useEffect(() => {
    const getCapability = transport.getWorkspaceFolderPickerCapability;
    if (getCapability === undefined || transport.chooseWorkspaceFolder === undefined) {
      setServerFolderPickerState("unavailable");
      return;
    }
    const controller = new AbortController();
    setServerFolderPickerState("checking");
    getCapability(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        const available = value.contract_version === "local-workspace-folder-picker.v1"
          && value.available === true
          && value.mode === "server_native_dialog";
        setServerFolderPickerState(available ? "available" : "unavailable");
      })
      .catch(() => {
        if (!controller.signal.aborted) setServerFolderPickerState("unavailable");
      });
    return () => controller.abort();
  }, [transport]);

  useEffect(() => {
    const handleNativeBridgeReady = () => {
      setNativeFolderPickerAvailable(hasNativeWorkspaceFolderPicker());
      setUserPresenceRetryNonce((value) => value + 1);
    };
    window.addEventListener("pywebviewready", handleNativeBridgeReady);
    // Close the render/effect registration race without polling.
    setNativeFolderPickerAvailable(hasNativeWorkspaceFolderPicker());
    return () => window.removeEventListener("pywebviewready", handleNativeBridgeReady);
  }, []);

  const userPresenceAvailable = userPresenceState === "available";
  const folderPickerAvailable = nativeFolderPickerAvailable
    || serverFolderPickerState === "available";
  const folderPickerChecking = !nativeFolderPickerAvailable
    && serverFolderPickerState === "checking";
  const activeAgentProjectId = current?.settings.project_id
    ?? selectedCatalogSession?.project_id
    ?? selectedProjectId;

  useEffect(() => {
    setTrustedMcpAcceptanceRun((run) => observeTrustedMcpAgentEvents(run, {
      events,
      projectId: current?.settings.project_id ?? null,
      sessionId: current?.session_id ?? null,
    }));
  }, [current?.session_id, current?.settings.project_id, events]);

  useEffect(() => () => promptCheckController.current?.abort(), []);

  useEffect(() => {
    if (current?.closing) clearPromptCheck();
  }, [clearPromptCheck, current?.closing]);

  useEffect(() => {
    clearPromptCheck();
    setConversationMessage("");
    if (modelFeedbackTarget === "session") {
      setModelError("");
      setModelNotice("");
    }
  }, [clearPromptCheck, current?.session_id]);

  useEffect(() => {
    if (!current || composerFocusNonce === 0) return;
    const composer = composerInputRef.current;
    composer?.scrollIntoView?.({ block: "nearest" });
    composer?.focus({ preventScroll: true });
  }, [composerFocusNonce, current?.session_id]);

  // Pick the session from the route, or the newest one. A selected durable
  // catalog entry without retained conversation history intentionally leaves
  // `current` empty so its truthful history-unavailable view is not replaced
  // by the newest live session on the next render.
  useEffect(() => {
    if (!sessions) return;
    const currentFromList = current ? sessions.find((s) => s.session_id === current.session_id) : undefined;
    const wanted = requestedSessionId
      ? sessions.find((s) => s.session_id === requestedSessionId)
      : selectedCatalogSession
        ? undefined
        : currentFromList ?? sessions[0];
    if (wanted && wanted.session_id !== current?.session_id) {
      setCurrent(rememberClosing(wanted));
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
      followOutput.current = true;
      setFollowingOutput(true);
    }
    if (wanted?.closing && wanted.session_id === current?.session_id && !current.closing) {
      markSessionClosing(wanted.session_id);
    }
    if (!wanted && !requestedSessionId && current) {
      setCurrent(null);
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
      followOutput.current = true;
      setFollowingOutput(true);
    }
    if (wanted) setSessionLookupState("idle");
  }, [sessions, requestedSessionId, current, selectedCatalogSession, markSessionClosing, rememberClosing]);

  // Returning users land on their newest durable chat instead of a setup
  // drawer. A truly empty catalog still opens onboarding after both the live
  // session list and durable catalog have loaded successfully.
  useEffect(() => {
    if (
      startupCatalogHandled.current
      || startupCatalogSession === undefined
      || sessions === null
      || sessionListError
    ) return;
    startupCatalogHandled.current = true;
    if (current || selectedCatalogSession || sessions.length > 0) return;
    if (startupCatalogSession === null) {
      setNewChatOpen(true);
      return;
    }
    setSelectedCatalogSession(startupCatalogSession);
    setSavedHistoryState(startupCatalogSession.retention_policy === "local_history" ? "loading" : "idle");
    setSavedHistoryMessage("");
    setSelectedProjectId(startupCatalogSession.project_id);
    setEvents([]);
    setHistoryGap(false);
    setStreamNotice("");
    lastSeq.current = 0;
  }, [current, selectedCatalogSession, sessionListError, sessions, startupCatalogSession]);

  useEffect(() => {
    if (selectedCatalogSession === null) {
      setSavedHistoryState("idle");
      setSavedHistoryMessage("");
      return;
    }
    if (selectedCatalogSession.retention_policy !== "local_history") {
      setSavedHistoryState("idle");
      setSavedHistoryMessage("");
      return;
    }
    if (transport.getAgentPersistedEvents === undefined) {
      setSavedHistoryState("error");
      setSavedHistoryMessage("This app build cannot read the retained conversation.");
      return;
    }
    const controller = new AbortController();
    const selected = selectedCatalogSession;
    setSavedHistoryState("loading");
    setSavedHistoryMessage("");
    setEvents([]);
    lastSeq.current = 0;
    void (async () => {
      const { events: retained, head } = await readCompleteRetainedEvents(
        transport.getAgentPersistedEvents!,
        selected.project_id,
        selected.session_id,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const focus = savedMessageFocusTarget.current;
      if (focus !== null && focus.sessionId === selected.session_id) {
        const refreshed = transport.getAgentCatalogSession === undefined
          ? null
          : await transport.getAgentCatalogSession(selected.session_id, controller.signal);
        if (controller.signal.aborted) return;
        const target = retained.find((event) => (
          event.seq === focus.eventSeq && (focus.role === "user" ? event.kind === "user" : event.kind === "assistant")
        ));
        if (
          refreshed === null
          || refreshed.session_id !== focus.sessionId
          || refreshed.project_id !== focus.projectId
          || refreshed.retention_policy !== "local_history"
          || refreshed.history_revision !== focus.historyRevision
          || refreshed.last_event_seq !== head
          || head < focus.eventSeq
          || target === undefined
        ) {
          savedMessageFocusTarget.current = null;
          setSavedMessageFocus(null);
          setEvents(retained);
          lastSeq.current = head;
          setSavedHistoryState("ready");
          setSavedHistoryMessage("The matching saved message changed or is no longer retained. Search again; no chat was resumed or changed.");
          return;
        }
        savedMessageFocusSequence.current += 1;
        setSavedMessageFocus({
          requestId: savedMessageFocusSequence.current,
          eventSeq: focus.eventSeq,
          sessionId: focus.sessionId,
          projectId: focus.projectId,
        });
        savedMessageFocusTarget.current = null;
      }
      setEvents(retained);
      lastSeq.current = head;
      setSavedHistoryState("ready");
    })().catch(() => {
      if (controller.signal.aborted) return;
      setEvents([]);
      lastSeq.current = 0;
      setSavedHistoryState("error");
      setSavedHistoryMessage("The retained conversation could not be read. Nothing was reconstructed.");
    });
    return () => controller.abort();
  }, [
    selectedCatalogSession?.history_revision,
    selectedCatalogSession?.last_event_seq,
    selectedCatalogSession?.project_id,
    selectedCatalogSession?.retention_policy,
    selectedCatalogSession?.session_id,
    retainedHistoryReloadKey,
    transport,
  ]);

  const artifactProjectId = current?.settings.retention_policy === "local_history"
    ? current.settings.project_id ?? null
    : selectedCatalogSession?.retention_policy === "local_history"
      ? selectedCatalogSession.project_id
      : null;
  const artifactSessionId = current?.settings.retention_policy === "local_history"
    ? current.session_id
    : selectedCatalogSession?.retention_policy === "local_history"
      ? selectedCatalogSession.session_id
      : null;
  const artifactItems = useMemo(() => {
    if (
      selectedArtifactExtra === null
      || artifacts.some((artifact) => artifact.artifact_id === selectedArtifactExtra.artifact_id)
    ) return artifacts;
    return [...artifacts, selectedArtifactExtra];
  }, [artifacts, selectedArtifactExtra]);
  const artifactPathSet = useMemo(() => new Set(
    artifactItems
      .filter((artifact) => (
        artifact.project_id === artifactProjectId
        && artifact.session_id === artifactSessionId
      ))
      .map((artifact) => artifact.path),
  ), [artifactItems, artifactProjectId, artifactSessionId]);
  const artifactDoneSequence = [...events].reverse().find((event) => (
    event.kind === "done"
    || event.kind === "tool_result" && event.write_receipt?.state === "verified"
  ))?.seq ?? 0;

  useEffect(() => {
    if (
      artifactProjectId === null
      || artifactSessionId === null
      || (
        transport.pageAgentArtifacts === undefined
        && transport.listAgentArtifacts === undefined
      )
    ) {
      artifactReadOwnerRef.current += 1;
      artifactPageControllerRef.current?.abort();
      artifactPageControllerRef.current = null;
      artifactServerIdsRef.current = new Set();
      setArtifacts([]);
      setSelectedArtifactExtra(null);
      setArtifactCounts(null);
      setArtifactsLoading(false);
      setArtifactsError("");
      setArtifactPageError("");
      setArtifactPageLoading(false);
      setArtifactSnapshot(null);
      setArtifactNextOffset(null);
      return;
    }
    const owner = artifactReadOwnerRef.current + 1;
    artifactReadOwnerRef.current = owner;
    const controller = new AbortController();
    artifactPageControllerRef.current?.abort();
    artifactPageControllerRef.current = null;
    artifactServerIdsRef.current = new Set();
    setArtifacts([]);
    setSelectedArtifactExtra(null);
    setArtifactCounts(null);
    setArtifactsLoading(true);
    setArtifactsError("");
    setArtifactPageError("");
    setArtifactPageLoading(false);
    setArtifactSnapshot(null);
    setArtifactNextOffset(null);
    void (async () => {
      try {
        const pageArtifacts = transport.pageAgentArtifacts;
        if (typeof pageArtifacts === "function") {
          const result = await pageArtifacts(
            artifactProjectId,
            artifactSessionId,
            {
              view: artifactView,
              limit: ARTIFACT_SERVER_PAGE,
              offset: 0,
            },
            controller.signal,
          );
          if (controller.signal.aborted || artifactReadOwnerRef.current !== owner) return;
          artifactServerIdsRef.current = new Set(
            result.artifacts.map((artifact) => artifact.artifact_id),
          );
          setArtifacts([...result.artifacts]);
          setArtifactCounts(result.counts);
          setArtifactSnapshot(result.snapshot);
          setArtifactNextOffset(result.next_offset ?? null);
        } else {
          const listArtifacts = transport.listAgentArtifacts;
          if (listArtifacts === undefined) return;
          const result = await listArtifacts(
            artifactProjectId,
            artifactSessionId,
            artifactView,
            controller.signal,
          );
          if (controller.signal.aborted || artifactReadOwnerRef.current !== owner) return;
          artifactServerIdsRef.current = new Set(
            result.artifacts.map((artifact) => artifact.artifact_id),
          );
          setArtifacts([...result.artifacts]);
          setArtifactCounts(result.counts);
        }
      } catch {
        if (!controller.signal.aborted && artifactReadOwnerRef.current === owner) {
          artifactServerIdsRef.current = new Set();
          setArtifacts([]);
          setSelectedArtifactExtra(null);
          setArtifactCounts(null);
          setArtifactSnapshot(null);
          setArtifactNextOffset(null);
          setArtifactsError("Artifacts could not be read. The conversation and workspace were not changed.");
        }
      } finally {
        if (!controller.signal.aborted && artifactReadOwnerRef.current === owner) {
          setArtifactsLoading(false);
        }
      }
    })();
    return () => {
      controller.abort();
      artifactPageControllerRef.current?.abort();
    };
  }, [
    artifactProjectId,
    artifactSessionId,
    artifactDoneSequence,
    artifactView,
    artifactsRefreshKey,
    transport,
  ]);

  async function loadMoreArtifacts(): Promise<void> {
    const pageArtifacts = transport.pageAgentArtifacts;
    if (
      typeof pageArtifacts !== "function"
      || artifactProjectId === null
      || artifactSessionId === null
      || artifactSnapshot === null
      || artifactNextOffset === null
      || artifactPageLoading
    ) return;
    const owner = artifactReadOwnerRef.current;
    const controller = new AbortController();
    artifactPageControllerRef.current?.abort();
    artifactPageControllerRef.current = controller;
    setArtifactPageLoading(true);
    setArtifactPageError("");
    try {
      const page = await pageArtifacts(
        artifactProjectId,
        artifactSessionId,
        {
          view: artifactView,
          limit: ARTIFACT_SERVER_PAGE,
          offset: artifactNextOffset,
          snapshot: artifactSnapshot,
        },
        controller.signal,
      );
      if (controller.signal.aborted || artifactReadOwnerRef.current !== owner) return;
      if (page.artifacts.some((artifact) => (
        artifactServerIdsRef.current.has(artifact.artifact_id)
      ))) {
        setArtifactPageError("A repeated artifact page was refused. Reload from the first page.");
        return;
      }
      page.artifacts.forEach((artifact) => (
        artifactServerIdsRef.current.add(artifact.artifact_id)
      ));
      setArtifacts((previous) => [...previous, ...page.artifacts]);
      setArtifactCounts(page.counts);
      setArtifactSnapshot(page.snapshot);
      setArtifactNextOffset(page.next_offset ?? null);
    } catch (caught) {
      if (!controller.signal.aborted && artifactReadOwnerRef.current === owner) {
        const changed = caught instanceof TransportError && (
          caught.reasonCode === "agent_artifact_page_snapshot_conflict"
          || caught.reasonCode === "agent_artifact_page_out_of_range"
        );
        setArtifactPageError(changed
          ? "Artifacts changed while another page was loading. Reload from the first page."
          : "More artifacts could not be loaded. The records already shown are unchanged.");
      }
    } finally {
      if (artifactPageControllerRef.current === controller) {
        artifactPageControllerRef.current = null;
        setArtifactPageLoading(false);
      }
    }
  }

  useEffect(() => {
    const request = artifactOpenRequest;
    const getArtifact = transport.getAgentArtifact;
    if (
      request === null
      || artifactProjectId === null
      || artifactSessionId === null
      || request.projectId !== artifactProjectId
      || request.sessionId !== artifactSessionId
      || artifactItems.some((artifact) => artifact.artifact_id === request.artifactId)
      || artifactsLoading
      || artifactsError !== ""
      || typeof getArtifact !== "function"
    ) return;
    const controller = new AbortController();
    void getArtifact(
      artifactProjectId,
      artifactSessionId,
      request.artifactId,
      controller.signal,
    ).then((artifact) => {
      if (
        controller.signal.aborted
        || artifact.path !== request.path
        || artifact.project_id !== artifactProjectId
        || artifact.session_id !== artifactSessionId
      ) return;
      if (artifact.lifecycle_state !== artifactView) {
        setArtifactView(artifact.lifecycle_state);
        return;
      }
      setSelectedArtifactExtra(artifact);
    }).catch(() => {
      if (!controller.signal.aborted) {
        setArtifactPageError("The requested artifact is no longer available in this chat.");
      }
    });
    return () => controller.abort();
  }, [
    artifactItems,
    artifactOpenRequest,
    artifactProjectId,
    artifactSessionId,
    artifactView,
    artifactsError,
    artifactsLoading,
    transport,
  ]);

  // A dedicated Agent window addresses one session directly. If the session
  // list is stale or bounded, resolve that route explicitly and report why it
  // cannot be restored instead of rendering an unexplained empty card.
  useEffect(() => {
    if (!requestedSessionId) {
      setSessionLookupState("idle");
      return;
    }
    if (sessions === null) {
      setSessionLookupState("loading");
      return;
    }
    if (sessions.some((session) => session.session_id === requestedSessionId)) return;

    const controller = new AbortController();
    setSessionLookupState("loading");
    void Promise.resolve(transport.getAgentSession(requestedSessionId, controller.signal))
      .then((view) => {
        if (controller.signal.aborted) return;
        if (!view || view.session_id !== requestedSessionId) {
          setCurrent(null);
          setSessionLookupState("missing");
          return;
        }
        setCurrent(rememberClosing(view));
        setEvents([]);
        setHistoryGap(false);
        setStreamNotice("");
        lastSeq.current = 0;
        followOutput.current = true;
        setFollowingOutput(true);
        setSessionLookupState("idle");
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        const missing = caught instanceof TransportError && caught.status === 404;
        if (!missing) {
          setSessionLookupState("error");
          return;
        }
        const getCatalogSession = transport.getAgentCatalogSession;
        if (getCatalogSession === undefined) {
          setCurrent(null);
          setSessionLookupState("missing");
          return;
        }
        void Promise.resolve(getCatalogSession(requestedSessionId, controller.signal))
          .then((record) => {
            if (controller.signal.aborted) return;
            if (!record || record.session_id !== requestedSessionId) {
              setCurrent(null);
              setSessionLookupState("missing");
              return;
            }
            setCurrent(null);
            setSelectedCatalogSession(record);
            setSelectedProjectId(record.project_id);
            setSavedHistoryState(record.retention_policy === "local_history" ? "loading" : "idle");
            setSavedHistoryMessage("");
            setEvents([]);
            setHistoryGap(false);
            setStreamNotice("");
            lastSeq.current = 0;
            followOutput.current = true;
            setFollowingOutput(true);
            if (windowMode) setWindowTargetSessionId(undefined);
            setSessionLookupState("idle");
          })
          .catch((catalogError) => {
            if (controller.signal.aborted) return;
            const catalogMissing = catalogError instanceof TransportError && catalogError.status === 404;
            setCurrent(null);
            setSessionLookupState(catalogMissing ? "missing" : "error");
          });
      });
    return () => controller.abort();
  }, [rememberClosing, requestedSessionId, sessions, transport, windowMode]);

  const pending = useMemo(() => {
    if (!current?.pending_approval_id || commandCleanupBlocked || current.closing || current.stopping || responseStopping) return null;
    return [...events].reverse().find((event) => event.kind === "approval_required" && event.approval_id === current.pending_approval_id) ?? null;
  }, [events, current?.closing, current?.stopping, current?.pending_approval_id, responseStopping, commandCleanupBlocked]);

  const activeExternalProposal = useMemo(() => {
    const settled = new Set(events
      .filter((event) => event.kind === "tool_result" && event.call_id)
      .map((event) => event.call_id));
    return [...events].reverse().find((event) => (
      event.kind === "tool_call"
      && Boolean(event.call_id)
      && !settled.has(event.call_id ?? "")
      && isExternalWriteProposal(event)
    )) ?? null;
  }, [events]);

  useEffect(() => {
    if (pending) approvalRef.current?.focus();
  }, [pending]);

  // Prefer the private SSE event stream; retain polling for older/test transports.
  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    const controller = new AbortController();
    let handle = 0;
    let streamFailures = 0;
    let acceptedView = current;
    const acceptPage = (page: AgentEvents): boolean => {
      if (cancelled || page.session_id !== current.session_id) return false;
      if (page.cleanup_unconfirmed) markCommandCleanup(page.session_id);
      if (page.closing) markSessionClosing(page.session_id);
      const cursor = lastSeq.current;
      if (page.first_seq > cursor + 1) setHistoryGap(true);
      const fresh = page.events.filter((event) => event.seq > cursor);
      const nextAcceptedView = reconcileAgentEventPage(acceptedView, page);
      const advanced = fresh.length > 0 || agentEventPageAdvanced(acceptedView, nextAcceptedView);
      acceptedView = nextAcceptedView;
      if (advanced) {
        streamFailures = 0;
        setStreamNotice((previous) => isLiveUpdateNotice(previous) ? "" : previous);
      }
      if (fresh.length > 0) {
        setEvents((previous) => {
          const priorSeq = previous.length > 0 ? previous[previous.length - 1].seq : 0;
          return compactTerminalDeltas([...previous, ...fresh.filter((event) => event.seq > priorSeq)]);
        });
        lastSeq.current = fresh[fresh.length - 1].seq;
        if (fresh.some((event) => event.kind === "error")) void refreshModels();
      }
      setCurrent((previous) => previous && previous.session_id === page.session_id
        ? rememberClosing(reconcileAgentEventPage(previous, page))
        : previous);
      return acceptedView.running || Boolean(acceptedView.pending_approval_id) || fresh.length > 0;
    };

    if (transport.streamAgentEvents) {
      let streamActive = current.running;
      const recordStreamFailure = () => {
        streamFailures += 1;
        if (streamFailures >= 3) setStreamNotice("Live updates were interrupted; reconnecting on this machine…");
      };
      const connect = async () => {
        try {
          await transport.streamAgentEvents?.(
            current.session_id,
            lastSeq.current,
            (page) => { streamActive = acceptPage(page); },
            controller.signal,
          );
          if (!controller.signal.aborted && !cancelled) {
            if (streamActive) recordStreamFailure();
            else {
              streamFailures = 0;
              setStreamNotice((previous) => isLiveUpdateNotice(previous) ? "" : previous);
            }
          }
        } catch {
          if (!controller.signal.aborted) recordStreamFailure();
        }
        if (cancelled) return;
        if (streamFailures >= MAX_STREAM_FAILURES) {
          setStreamNotice("Live updates paused after repeated connection failures. Retry when the local service is available.");
          return;
        }
        const delay = streamFailures > 0
          ? Math.min(STREAM_RETRY_MS * (2 ** (streamFailures - 1)), MAX_STREAM_RETRY_MS)
          : streamActive ? STREAM_RETRY_MS : IDLE_POLL_MS;
        handle = window.setTimeout(() => { void connect(); }, delay);
      };
      void connect();
    } else {
      const tick = async (): Promise<boolean> => {
        try {
          return acceptPage(await transport.getAgentEvents(current.session_id, lastSeq.current, controller.signal));
        } catch {
          return true;
        }
      };
      const schedule = (active: boolean) => {
        if (cancelled) return;
        handle = window.setTimeout(async () => {
          schedule(await tick());
        }, active ? POLL_MS : IDLE_POLL_MS);
      };
      void tick().then(schedule);
    }
    return () => { cancelled = true; controller.abort(); window.clearTimeout(handle); };
  }, [current?.session_id, current?.running, markSessionClosing, refreshModels, rememberClosing, streamRetryNonce, transport]);

  useEffect(() => {
    const node = logRef.current;
    if (node && followOutput.current) node.scrollTop = node.scrollHeight;
  }, [events]);

  const selectedModel = useMemo(
    () => newSessionModelAlias
      ? (models?.models ?? []).find((model) => model.record.alias === newSessionModelAlias) ?? null
      : null,
    [models, newSessionModelAlias],
  );
  const currentModelAlias = current?.model_alias ?? current?.settings.model_alias ?? null;
  const currentModel = useMemo(() => {
    if (!current) return null;
    return currentModelAlias
      ? (models?.models ?? []).find((model) => model.record.alias === currentModelAlias) ?? null
      : null;
  }, [current, currentModelAlias, models]);
  const connectionDisconnected = connectionState === "disconnected";
  const selectedModelNeedsActivation = modelCatalogState === "ready"
    && selectedModel !== null
    && selectedModel.runtime.state !== "running";
  const selectedModelUnavailableForSession = connectionDisconnected
    || (Boolean(newSessionModelAlias) && (
      Boolean(modelActionAlias)
      || runtimeControlBusy
      || modelCatalogState === "loading"
      || (modelCatalogState === "ready" && selectedModel === null)
      || (selectedModelNeedsActivation
        && (selectedModel?.runtime.state === "starting" || transport.activateLocalModel === undefined))
    ));
  const currentModelAction = modelActionAlias && modelActionAlias === (currentModel?.record.alias ?? currentModelAlias)
    ? modelActionKind : null;
  const currentModelBlocked = commandCleanupBlocked || connectionDisconnected || currentModelAlias === null || currentModelAction !== null || modelCatalogState === "loading"
    || runtimeControlBusy
    || (modelCatalogState === "ready" && currentModel?.runtime.state !== "running");
  const runtimeCoordinatorAvailable = transport.getLocalRuntime !== undefined
    && transport.switchLocalRuntime !== undefined
    && transport.stopLocalRuntime !== undefined;
  const inlineRuntimeRecoveryAvailable = runtimeCoordinatorAvailable
    && Boolean(models?.models.length);
  const mediaCapabilities = runtimeCoordinator?.state === "ready"
    && runtimeCoordinator.served?.alias === currentModelAlias
    ? runtimeCoordinator.capabilities
    : null;
  const mediaRuntimeKey = [
    currentModelAlias ?? "no-chat-model",
    runtimeCoordinator?.state ?? "runtime-unavailable",
    runtimeCoordinator?.served?.alias ?? "no-served-model",
    runtimeCoordinator?.served?.started_at ?? "not-started",
    mediaCapabilities?.state ?? "media-unverified",
    mediaCapabilities?.vision ? "vision" : "no-vision",
    mediaCapabilities?.audio ? "audio" : "no-audio",
    mediaCapabilities?.recording ? "recording" : "no-recording",
  ].join(":");
  const attachmentModelMismatch = currentModelAlias !== null
    && draftAttachments.some((attachment) => attachment.model_alias !== currentModelAlias);
  const liveStreams = useMemo(() => coalesceLiveStreams(events), [events]);
  const reasoningEnabled = current?.settings.parameters.enable_thinking ?? false;
  const hasLiveReasoning = [...liveStreams.values()].some((stream) => Boolean(stream.reasoning));
  const hasVisibleReasoning = events.some((event) => Boolean(event.reasoning)) || hasLiveReasoning;
  const toolCallCount = events.filter((event) => event.kind === "tool_call").length;
  const turnRevisionSupported = transport.getAgentCatalogSession !== undefined
    && transport.getAgentPersistedEvents !== undefined
    && transport.forkAgentSession !== undefined
    && transport.resumeAgentSession !== undefined;
  const liveTurnRevisionDisabled = !turnRevisionSupported
    || current?.settings.retention_policy !== "local_history"
    || current.running
    || current.closing
    || current.history_write_failed
    || commandCleanupBlocked
    || connectionDisconnected
    || busy
    || forkBusy
    || turnRevisionBusy !== null;
  const lastActivity = [...events].reverse().find((event) => event.kind !== "done" && event.kind !== "assistant_delta");
  const activityState = commandCleanupBlocked
    ? { detail: "Agent work is paused. You can still select and copy your draft.", label: "Command cleanup unconfirmed", tone: "error" }
    : current?.closing
    ? { detail: CLOSING_SESSION_MESSAGE, label: "Session closing", tone: "attention" }
    : responseStopping
      ? { detail: "Cancelling this response; the model stays loaded. Waiting for the active operation to end.", label: "Stopping response", tone: "working" }
    : runtimeControlBusy
      ? { detail: "Changing the shared model runtime. This chat and its draft stay in place.", label: "Switching model", tone: "working" }
    : currentModelAction !== null
      ? { detail: "Waiting for the model runtime to confirm the change. Your draft is kept here.", label: currentModelAction === "start" ? "Starting model" : "Stopping model", tone: "working" }
    : pending
    ? { detail: "A protected action needs your decision.", label: "Approval needed", tone: "attention" }
    : current?.running
      ? hasLiveReasoning
        ? { detail: "The model reasoning stream is visible below.", label: "Reasoning", tone: "working" }
        : liveStreams.size > 0
          ? { detail: "The response is streaming below.", label: "Responding", tone: "working" }
          : { detail: "Waiting for the next model or tool event.", label: "Working", tone: "working" }
      : currentModelAlias === null
        ? { detail: "Choose and start a model in Model & context before sending.", label: "No model", tone: "paused" }
      : modelCatalogState === "loading"
        ? { detail: "Verifying the exact session model runtime.", label: "Checking model", tone: "paused" }
        : modelCatalogState === "error" || modelCatalogState === "unavailable"
          ? { detail: "The model will be verified again before the next turn.", label: "Model unverified", tone: "attention" }
          : currentModelBlocked
            ? {
              detail: inlineRuntimeRecoveryAvailable
                ? "Choose, start, or bind this chat's model in Model & context."
                : runtimeCoordinatorAvailable
                  ? "Install or restore a model on the Models page."
                : "Start the session model to continue.",
              label: "Model stopped",
              tone: "paused",
            }
            : lastActivity?.kind === "error"
              ? { detail: "The last run needs attention before retrying.", label: "Needs attention", tone: "error" }
              : { detail: "Ready for your next request.", label: "Ready", tone: "ready" };
  const sessionModelStatus = current === null ? "" : commandCleanupBlocked
    ? COMMAND_CLEANUP_MESSAGE
    : current.closing
      ? CLOSING_SESSION_MESSAGE
      : connectionDisconnected
        ? "The local app is disconnected. Reopen the protected Agent desktop window before sending."
        : currentModelAction !== null
          ? `${currentModelAction === "start" ? "Starting" : "Stopping"} the session model. Your draft will remain here while the runtime confirms the change.`
          : runtimeControlBusy
            ? "Changing the shared model runtime. This chat and its draft stay in place."
            : modelCatalogState === "loading"
              ? "Checking the session model…"
              : modelCatalogState === "error"
                ? "Model status could not be refreshed; it will be verified before the next turn."
                : modelCatalogState === "unavailable"
                  ? "The session model will be verified before the next turn."
                  : currentModel === null
                    ? currentModelAlias
                      ? inlineRuntimeRecoveryAvailable
                        ? "This chat's saved model is not installed. Choose a replacement in Model & context."
                        : runtimeCoordinatorAvailable
                          ? "This chat's saved model is not installed. Add or restore it on the Models page."
                          : "The session model is not registered and cannot receive a message."
                      : inlineRuntimeRecoveryAvailable
                        ? "No model is bound to this chat. Choose one in Model & context, then start or bind it."
                        : runtimeCoordinatorAvailable
                          ? "No installed local model is available. Add one on the Models page."
                          : "No local model is running for this session. Start one on the Models page."
                    : currentModel.runtime.state === "running"
                      ? `${currentModel.record.display_name} · running · ${current.closing ? "session closing" : responseStopping ? "stopping current response" : activeExternalProposal ? pending ? "external proposal awaiting review" : "applying reviewed external proposal" : current.running ? "response in progress" : "ready for messages"}`
                      : `${currentModel.record.display_name} · ${runtimeStateLabel(currentModel.runtime.state)} · ${inlineRuntimeRecoveryAvailable ? "start or switch it in Model & context" : "start it before sending"}`;
  const sessionModelState = currentModelAction === "start"
    ? "starting"
    : currentModelAction === "stop"
      ? "stopping"
      : currentModel?.runtime.state ?? modelCatalogState;
  const sessionModelNoticeVisible = current !== null && (
    !runtimeCoordinatorAvailable
    || commandCleanupBlocked
    || current.closing
    || connectionDisconnected
    || currentModelAction !== null
    || runtimeControlBusy
    || modelCatalogState !== "ready"
    || currentModel?.runtime.state !== "running"
    || (modelFeedbackTarget === "session" && Boolean(modelError || modelNotice))
  );
  const handleWorkspaceDirty = useCallback((value: boolean) => setWorkspaceDirty(value), []);
  const handleWorkspaceApplied = useCallback(() => {
    setChangeSetRevision((value) => value + 1);
    setArtifactsRefreshKey((value) => value + 1);
  }, []);
  const handleChangeRestored = useCallback(() => {
    setChangeSetRevision((value) => value + 1);
    setArtifactsRefreshKey((value) => value + 1);
  }, []);
  const latestDoneSequence = [...events].reverse().find((event) => event.kind === "done")?.seq ?? 0;
  const changeSetRefreshKey = `${current?.session_id ?? "none"}:${latestDoneSequence}:${changeSetRevision}:${current?.running ? "running" : "settled"}`;
  const currentFileRequest = workspaceFileRequest?.sessionId === current?.session_id && workspaceFileRequest?.transport === transport ? workspaceFileRequest : null;
  const currentChangeReviewRequest = changeReviewRequest?.sessionId === current?.session_id && changeReviewRequest?.transport === transport
    ? changeReviewRequest
    : null;
  const workspaceVisible = current !== null && (reviewOpen || currentFileRequest !== null);

  useEffect(() => {
    setArtifactOpenRequest(null);
  }, [current?.session_id, transport]);

  useEffect(() => {
    setReviewView("files");
  }, [current?.session_id]);

  function openReceiptFile(path: string): void {
    if (!current || current.closing || connectionDisconnected) return;
    setReviewView("files");
    setReviewOpen(true);
    setWorkspaceFileRequest({ sessionId: current.session_id, transport, path, requestId: ++fileRequestSequence.current, intent: "open" });
  }

  function revealArtifactFile(path: string): void {
    if (!current || current.closing || connectionDisconnected) return;
    setReviewView("files");
    setReviewOpen(true);
    setWorkspaceFileRequest({ sessionId: current.session_id, transport, path, requestId: ++fileRequestSequence.current, intent: "reveal" });
  }

  function reviewArtifactChanges(path: string): void {
    if (!current || current.closing || connectionDisconnected) return;
    setReviewView("changes");
    setReviewOpen(true);
    setChangeReviewRequest({
      sessionId: current.session_id,
      transport,
      path,
      requestId: ++changeReviewSequence.current,
    });
  }

  function openArtifactSourceTurn(turnId: string): boolean {
    if (!events.some((event) => event.kind === "done" && event.turn_id === turnId)) return false;
    artifactTurnFocusSequence.current += 1;
    setArtifactTurnFocus({ requestId: artifactTurnFocusSequence.current, turnId });
    return true;
  }

  function openChangeArtifact(path: string): void {
    if (
      !current
      || artifactProjectId === null
      || artifactSessionId !== current.session_id
      || current.closing
      || connectionDisconnected
    ) return;
    const artifact = artifacts.find((candidate) => (
      candidate.project_id === artifactProjectId
      && candidate.session_id === artifactSessionId
      && candidate.path === path
    ));
    if (artifact === undefined) return;
    setArtifactOpenRequest({
      projectId: artifactProjectId,
      sessionId: artifactSessionId,
      artifactId: artifact.artifact_id,
      path: artifact.path,
      requestId: ++artifactOpenSequence.current,
    });
  }

  function addChangeArtifact(path: string): void {
    if (!current || current.closing || connectionDisconnected) return;
    setReviewView("files");
    setReviewOpen(true);
    setWorkspaceFileRequest({
      sessionId: current.session_id,
      transport,
      path,
      requestId: ++fileRequestSequence.current,
      intent: "capture",
    });
  }

  function continueAfterWorkspaceDiscard(confirmLabel: string, action: () => void): void {
    if (!workspaceDirty) {
      action();
      return;
    }
    const requestedTransport = transport;
    void mayLeaveWorkspace(confirmLabel).then((accepted) => {
      if (accepted && sessionContext.current.transport === requestedTransport) action();
    });
  }

  function hideWorkspace(): void {
    continueAfterWorkspaceDiscard("Discard and close", () => {
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setReviewOpen(false);
      setComposerFocusNonce((value) => value + 1);
    });
  }

  function beginReviewResize(event: ReactPointerEvent<HTMLDivElement>): void {
    if (event.button !== 0) return;
    event.preventDefault();
    reviewResizeCleanup.current?.();
    const originX = event.clientX;
    const originWidth = reviewWidth;
    const move = (nextEvent: PointerEvent) => {
      setReviewWidth(Math.max(
        REVIEW_DRAWER_MIN_PX,
        Math.min(REVIEW_DRAWER_MAX_PX, originWidth + originX - nextEvent.clientX),
      ));
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      reviewResizeCleanup.current = null;
    };
    reviewResizeCleanup.current = finish;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
    window.addEventListener("pointercancel", finish, { once: true });
  }

  function resizeReviewWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>): void {
    const step = event.shiftKey ? 64 : 24;
    let next: number | null = null;
    if (event.key === "ArrowLeft") next = reviewWidth + step;
    else if (event.key === "ArrowRight") next = reviewWidth - step;
    else if (event.key === "Home") next = REVIEW_DRAWER_MIN_PX;
    else if (event.key === "End") next = REVIEW_DRAWER_MAX_PX;
    if (next === null) return;
    event.preventDefault();
    setReviewWidth(Math.max(REVIEW_DRAWER_MIN_PX, Math.min(REVIEW_DRAWER_MAX_PX, next)));
  }

  function openLiveSession(session: AgentSessionView): void {
    continueAfterWorkspaceDiscard("Discard and switch chat", () => {
      savedMessageFocusTarget.current = null;
      setSavedMessageFocus(null);
      if (windowMode) {
        if (dedicatedWindowKey !== null) announceAgentWindowActiveSession(dedicatedWindowKey, session.session_id);
        setWindowTargetSessionId(session.session_id);
      }
      setSelectedCatalogSession(null);
      setSavedHistoryState("idle");
      setSavedHistoryMessage("");
      setNewChatOpen(false);
      setSettingsOpen(false);
      setSelectedProjectId(session.settings.project_id ?? null);
      setCurrent(rememberClosing(session));
      setReviewOpen(false);
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
    });
  }

  function openUnavailableSession(session: AgentCatalogSession): void {
    continueAfterWorkspaceDiscard("Discard and open chat", () => {
      selectUnavailableSession(session);
    });
  }

  function selectUnavailableSession(session: AgentCatalogSession, preserveSavedMessageFocus = false): void {
      if (!preserveSavedMessageFocus) {
        savedMessageFocusTarget.current = null;
        setSavedMessageFocus(null);
      }
      if (windowMode) {
        if (dedicatedWindowKey !== null) announceAgentWindowActiveSession(dedicatedWindowKey, session.session_id);
        setWindowTargetSessionId(undefined);
      }
      setCurrent(null);
      setSelectedCatalogSession(session);
      setSavedHistoryState(session.retention_policy === "local_history" ? "loading" : "idle");
      setSavedHistoryMessage("");
      setNewChatOpen(false);
      setSettingsOpen(false);
      setSelectedProjectId(session.project_id);
      setReviewOpen(false);
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
      setRetainedHistoryReloadKey((value) => value + 1);
  }

  async function openSavedMessage(
    match: AgentSavedMessageSearchHit,
    session: AgentCatalogSession,
    signal: AbortSignal,
  ): Promise<boolean> {
    const visibleBeforeConfirmation = sessionContext.current.id
      ?? selectedCatalogSessionRef.current?.session_id
      ?? null;
    const requestedTransport = transport;
    if (!(await mayLeaveWorkspace("Discard and open matching saved message")) || signal.aborted) return false;
    if (
      requestedTransport !== sessionContext.current.transport
      || visibleBeforeConfirmation !== (sessionContext.current.id ?? selectedCatalogSessionRef.current?.session_id ?? null)
    ) return false;
    if (
      session.session_id !== match.session_id
      || session.project_id !== match.project_id
      || session.retention_policy !== "local_history"
      || session.history_revision !== match.history_revision
    ) return false;
    savedMessageFocusTarget.current = {
      sessionId: match.session_id,
      projectId: match.project_id,
      historyRevision: match.history_revision,
      eventSeq: match.match_event_seq,
      role: match.role,
    };
    selectUnavailableSession(session, true);
    return true;
  }

  function beginNewChat(projectId: string | null, trigger: HTMLButtonElement): void {
    savedMessageFocusTarget.current = null;
    setSavedMessageFocus(null);
    newChatTriggerRef.current = trigger;
    if (projectId !== null) setSelectedProjectId(projectId);
    setNewSessionModelAlias("");
    setSelectedCatalogSession(null);
    setSavedHistoryState("idle");
    setSavedHistoryMessage("");
    setRailCollapsed(false);
    setSettingsOpen(false);
    setNewChatOpen(true);
    window.setTimeout(() => workspaceInputRef.current?.focus(), 0);
  }

  async function forkCatalogSession(
    source: AgentCatalogSession,
    title: string | undefined,
    throughEventSeq?: number,
    signal?: AbortSignal,
    announceResult = true,
  ): Promise<AgentSessionForkReceipt | null> {
    if (
      transport.forkAgentSession === undefined
      || forkOperation.current !== null
      || signal?.aborted
    ) return null;
    const controller = new AbortController();
    const owner = forkOwner.current + 1;
    forkOwner.current = owner;
    forkOperation.current = { controller, owner };
    const forwardAbort = () => controller.abort();
    signal?.addEventListener("abort", forwardAbort, { once: true });
    const normalizedTitle = title?.trim() || undefined;
    const key = [
      source.project_id,
      source.session_id,
      source.revision,
      source.history_revision,
      throughEventSeq ?? "latest",
      normalizedTitle ?? "default-title",
    ].join(":");
    const requestId = pendingForkRequest.current?.key === key
      ? pendingForkRequest.current.requestId
      : newForkRequestId();
    pendingForkRequest.current = { key, requestId };
    setForkBusy(true);
    if (announceResult) {
      setSavedHistoryMessage("");
      setConversationMessage("");
      setStreamNotice("");
    }
    try {
      const receipt = await transport.forkAgentSession(
        source.project_id,
        source.session_id,
        {
          request_id: requestId,
          expected_catalog_revision: source.revision,
          expected_history_revision: source.history_revision,
          destination_project_id: null,
          through_event_seq: throughEventSeq ?? null,
          title: normalizedTitle ?? null,
        },
        controller.signal,
      );
      if (controller.signal.aborted || forkOperation.current?.owner !== owner) return null;
      pendingForkRequest.current = null;
      refreshAgentCatalog();
      if (announceResult) {
        if (current === null) {
          openUnavailableSession(receipt.session);
        } else {
          setStreamNotice(
            receipt.source_tail_omitted
              ? "Branch created through the selected completed turn; later or interrupted events were not copied. Open it from the project list."
              : "Branch created without live authority. Open it from the project list when ready.",
          );
        }
      }
      return receipt;
    } catch (caught) {
      if (controller.signal.aborted || forkOperation.current?.owner !== owner) return null;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      const message = reason === "agent_catalog_session_revision_conflict" || reason === "agent_history_revision_conflict"
        ? "This chat changed in another window. Reopen it from the project list before branching."
        : reason === "agent_session_fork_point_invalid"
          ? "That branch point is no longer a completed turn. Refresh the retained history and retry."
          : "The branch could not be created. The source chat was not changed.";
      if (announceResult) {
        setSavedHistoryMessage(message);
        setConversationMessage(message);
      }
      throw caught;
    } finally {
      signal?.removeEventListener("abort", forwardAbort);
      if (forkOperation.current?.owner === owner) {
        forkOperation.current = null;
        setForkBusy(false);
      }
    }
  }

  function ownsTurnRevision(operation: TurnRevisionOperation): boolean {
    return turnRevisionOperation.current === operation
      && turnRevisionOwner.current === operation.owner
      && !operation.controller.signal.aborted;
  }

  async function reviseTurn(turnId: string, mode: AgentTurnRevisionMode): Promise<void> {
    const sourceLive = current;
    const sourceSaved = selectedCatalogSession;
    const sourceSessionId = sourceLive?.session_id ?? sourceSaved?.session_id ?? null;
    const sourceProjectId = sourceLive?.settings.project_id ?? sourceSaved?.project_id ?? null;
    const sourceRetained = sourceLive?.settings.retention_policy === "local_history"
      || sourceSaved?.retention_policy === "local_history";
    if (
      sourceSessionId === null
      || sourceProjectId === null
      || !sourceRetained
      || sourceSaved?.archived_at
      || sourceLive?.running
      || sourceLive?.closing
      || sourceLive?.history_write_failed
      || commandCleanupBlocked
      || connectionDisconnected
      || forkOperation.current !== null
      || turnRevisionOperation.current !== null
      || transport.getAgentCatalogSession === undefined
      || transport.getAgentPersistedEvents === undefined
      || transport.forkAgentSession === undefined
      || transport.resumeAgentSession === undefined
    ) return;
    if (sourceLive !== null && !(await mayLeaveWorkspace("Discard and create branch"))) return;
    const visibleAfterConfirmation = sessionContext.current.id
      ?? selectedCatalogSessionRef.current?.session_id
      ?? null;
    if (visibleAfterConfirmation !== sourceSessionId) return;

    const controller = new AbortController();
    const owner = turnRevisionOwner.current + 1;
    turnRevisionOwner.current = owner;
    const operation: TurnRevisionOperation = {
      controller,
      expectedVisibleSessionId: sourceSessionId,
      owner,
    };
    turnRevisionOperation.current = operation;
    setTurnRevisionBusy({ mode, turnId });
    setConversationMessage("");
    setSavedHistoryMessage("");
    setStreamNotice("");
    let forkReceipt: AgentSessionForkReceipt | null = null;
    let resumedBranch: AgentSessionView | null = null;
    let sourceText = "";
    try {
      const catalog = await transport.getAgentCatalogSession(sourceSessionId, controller.signal);
      if (!ownsTurnRevision(operation)) return;
      if (
        catalog.session_id !== sourceSessionId
        || catalog.project_id !== sourceProjectId
        || catalog.retention_policy !== "local_history"
        || catalog.archived_at !== null
      ) throw new Error("turn_revision_source_changed");

      const retained = await readCompleteRetainedEvents(
        transport.getAgentPersistedEvents,
        sourceProjectId,
        sourceSessionId,
        controller.signal,
      );
      if (!ownsTurnRevision(operation)) return;
      if (retained.head !== catalog.last_event_seq) throw new Error("turn_revision_source_changed");
      const sourceUser = retained.events.find((event) => event.kind === "user" && event.turn_id === turnId);
      const settled = retained.events.find((event) => event.kind === "done" && event.turn_id === turnId);
      sourceText = sourceUser?.text?.trim() ?? "";
      if (sourceUser === undefined || settled === undefined || sourceText.length === 0) {
        throw new Error("turn_revision_source_unavailable");
      }
      if (mode !== "edit" && sourceUser.attachments.length > 0) {
        throw new Error("turn_revision_attachments_require_edit");
      }
      const branchPoint = [...retained.events]
        .reverse()
        .find((event) => event.kind === "done" && event.seq < sourceUser.seq)?.seq ?? 0;
      forkReceipt = await forkCatalogSession(
        catalog,
        undefined,
        branchPoint,
        controller.signal,
        false,
      );
      if (!ownsTurnRevision(operation) || forkReceipt === null) return;

      operation.expectedVisibleSessionId = forkReceipt.session.session_id;
      resumedBranch = await transport.resumeAgentSession(
        forkReceipt.session.project_id,
        forkReceipt.session.session_id,
        {
          expected_catalog_revision: forkReceipt.session.revision,
          expected_history_revision: forkReceipt.session.history_revision,
        },
        controller.signal,
      );
      if (!ownsTurnRevision(operation)) return;
      if (
        resumedBranch.session_id !== forkReceipt.session.session_id
        || resumedBranch.settings.project_id !== forkReceipt.session.project_id
        || resumedBranch.settings.retention_policy !== "local_history"
      ) throw new Error("turn_revision_resume_mismatch");

      const copiedEvents = retained.events.filter((event) => event.seq <= branchPoint);
      replaceComposerDraft(resumedBranch.session_id, { text: sourceText, attachments: [] });
      setSessions((previous) => [
        resumedBranch as AgentSessionView,
        ...(previous ?? []).filter((session) => session.session_id !== resumedBranch?.session_id),
      ]);
      if (windowMode) {
        if (dedicatedWindowKey !== null) announceAgentWindowActiveSession(dedicatedWindowKey, resumedBranch.session_id);
        setWindowTargetSessionId(resumedBranch.session_id);
      }
      setCurrent(rememberClosing(resumedBranch));
      setSelectedCatalogSession(null);
      setSelectedProjectId(resumedBranch.settings.project_id);
      setEvents(copiedEvents);
      setHistoryGap(false);
      lastSeq.current = branchPoint;
      setSavedHistoryState("idle");
      setNewChatOpen(false);
      setReviewOpen(false);
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setRecoveryAllowWrites(false);
      setRecoveryAllowCommands(false);
      clearPromptCheck();
      refreshAgentCatalog();
      followOutput.current = true;
      setFollowingOutput(true);

      if (mode === "edit") {
        setStreamNotice(
          `Editable branch created before turn ${settled.turn_summary?.turn_number ?? "?"}. The source chat and existing workspace effects are unchanged; review the draft before sending.`,
        );
        setComposerFocusNonce((value) => value + 1);
        return;
      }

      try {
        const started = await transport.sendAgentMessage(
          resumedBranch.session_id,
          sourceText,
          [],
          controller.signal,
        );
        if (!ownsTurnRevision(operation)) return;
        clearSentComposerDraft(resumedBranch.session_id, sourceText, []);
        setSessions((previous) => [
          started,
          ...(previous ?? []).filter((session) => session.session_id !== started.session_id),
        ]);
        setCurrent(rememberClosing(started));
        setStreamNotice(
          `${mode === "regenerate" ? "Regeneration" : "Retry"} started in a new branch before turn ${settled.turn_summary?.turn_number ?? "?"}. The source chat and existing workspace effects are unchanged.`,
        );
      } catch (caught) {
        if (!ownsTurnRevision(operation)) return;
        const reason = caught instanceof TransportError ? caught.reasonCode : null;
        if (reason === "command_cleanup_unconfirmed") markCommandCleanup(resumedBranch.session_id);
        setConversationMessage(
          reason === "model_not_ready" || reason === "no_active_model"
            ? "The branch is ready and its prompt is kept, but the model is not running. Start this branch's model, then send the draft."
            : "The branch is ready and its prompt is kept, but the response did not start. Review the draft and send it manually.",
        );
        setComposerFocusNonce((value) => value + 1);
      }
    } catch (caught) {
      if (!ownsTurnRevision(operation)) return;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      const localReason = caught instanceof Error ? caught.message : "";
      const message = resumedBranch !== null
        ? "The new branch is open and its prompt is kept, but the revision did not start. Review the draft and send it manually."
        : forkReceipt !== null
          ? "The branch was created safely, but it could not be reopened. The source chat is unchanged; open the new branch from the project list."
          : localReason === "turn_revision_attachments_require_edit"
            ? "Attachments are never copied into a branch. Use Edit in branch, then add the files or recording again."
            : localReason === "turn_revision_source_unavailable"
              ? "This turn has no retained text request that can be revised safely. The source chat was not changed."
              : reason === "agent_catalog_session_revision_conflict" || reason === "agent_history_revision_conflict" || localReason === "turn_revision_source_changed" || localReason === "retained_history_changed"
                ? "This chat changed while the branch was being prepared. Reopen it and try again; no revision was started."
                : "The revision branch could not be prepared. The source chat was not changed.";
      setConversationMessage(message);
      setSavedHistoryMessage(message);
    } finally {
      if (turnRevisionOperation.current?.owner === owner) {
        turnRevisionOperation.current = null;
        setTurnRevisionBusy(null);
      }
    }
  }

  async function resumeSelectedSession(): Promise<void> {
    const selected = selectedCatalogSession;
    if (
      selected === null
      || selected.archived_at !== null
      || selected.retention_policy !== "local_history"
      || savedHistoryState !== "ready"
      || resumeBusy
      || transport.resumeAgentSession === undefined
    ) return;
    setResumeBusy(true);
    setSavedHistoryMessage("");
    try {
      const resumed = await transport.resumeAgentSession(
        selected.project_id,
        selected.session_id,
        {
          expected_catalog_revision: selected.revision,
          expected_history_revision: selected.history_revision,
        },
      );
      setSessions((previous) => [
        resumed,
        ...(previous ?? []).filter((session) => session.session_id !== resumed.session_id),
      ]);
      if (windowMode) {
        if (dedicatedWindowKey !== null) announceAgentWindowActiveSession(dedicatedWindowKey, resumed.session_id);
        setWindowTargetSessionId(resumed.session_id);
      }
      setCurrent(rememberClosing(resumed));
      setSelectedCatalogSession(null);
      setSelectedProjectId(resumed.settings.project_id ?? selected.project_id);
      refreshAgentCatalog();
      setRecoveryAllowWrites(false);
      setRecoveryAllowCommands(false);
      setConversationMessage("");
      setSavedHistoryState("idle");
      lastSeq.current = resumed.last_seq;
      followOutput.current = true;
      setFollowingOutput(true);
      setComposerFocusNonce((value) => value + 1);
    } catch (caught) {
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      setSavedHistoryMessage(
        reason === "agent_catalog_session_revision_conflict" || reason === "agent_history_revision_conflict"
          ? "This chat changed in another window. Reopen it from the project list and retry."
          : reason === "workspace_not_a_folder" || reason === "workspace_not_allowed"
            ? "The saved workspace cannot be revalidated. Restore access to that exact folder before resuming."
            : "The retained chat could not be resumed. Its saved history remains unchanged.",
      );
    } finally {
      setResumeBusy(false);
    }
  }

  async function exportSelectedHistory(): Promise<void> {
    const selected = selectedCatalogSession;
    if (
      selected === null
      || selected.retention_policy !== "local_history"
      || exportOperation.current !== null
      || transport.exportAgentHistory === undefined
    ) return;
    const key = [
      selected.project_id,
      selected.session_id,
      selected.revision,
      selected.history_revision,
    ].join(":");
    const controller = new AbortController();
    const owner = exportOwner.current + 1;
    exportOwner.current = owner;
    exportOperation.current = { controller, owner, key };
    setExportBusy(true);
    setSavedHistoryMessage("");
    try {
      const exported = await transport.exportAgentHistory(
        selected.project_id,
        selected.session_id,
        {
          expected_catalog_revision: selected.revision,
          expected_history_revision: selected.history_revision,
        },
        controller.signal,
      );
      const currentSelection = selectedCatalogSessionRef.current;
      if (
        controller.signal.aborted
        || exportOperation.current?.owner !== owner
        || currentSelection === null
        || currentSelection.project_id !== selected.project_id
        || currentSelection.session_id !== selected.session_id
        || currentSelection.revision !== selected.revision
        || currentSelection.history_revision !== selected.history_revision
      ) return;
      if (typeof URL.createObjectURL !== "function" || typeof URL.revokeObjectURL !== "function") {
        throw new Error("Local object URL downloads are unavailable.");
      }
      const blob = new Blob([`${JSON.stringify(exported, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      try {
        link.href = url;
        link.download = `agent-chat-${selected.session_id.slice(0, 8)}.json`;
        link.hidden = true;
        document.body.append(link);
        link.click();
      } finally {
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
      }
      setSavedHistoryMessage("History export prepared locally.");
    } catch (caught) {
      if (controller.signal.aborted || exportOperation.current?.owner !== owner) return;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      setSavedHistoryMessage(
        reason === "agent_catalog_session_revision_conflict" || reason === "agent_history_revision_conflict"
          ? "This chat changed in another window. Reopen it from the project list before exporting."
          : "The local history export could not be prepared.",
      );
    } finally {
      if (exportOperation.current?.owner === owner) {
        exportOperation.current = null;
        setExportBusy(false);
      }
    }
  }

  async function revalidateRecoveredAuthority(): Promise<void> {
    if (
      current === null
      || !current.recovered
      || current.authority_revalidated
      || authorityBusy
      || transport.revalidateAgentAuthority === undefined
      || transport.getAgentCatalogSession === undefined
      || !userPresenceAvailable
    ) return;
    const sessionId = current.session_id;
    setAuthorityBusy(true);
    setConversationMessage("");
    try {
      const catalog = await transport.getAgentCatalogSession(sessionId);
      const updated = await transport.revalidateAgentAuthority(sessionId, {
        expected_catalog_revision: catalog.revision,
        allow_writes: recoveryAllowWrites,
        allow_commands: recoveryAllowCommands,
        allow_web: false,
      });
      setCurrent(rememberClosing(updated));
      setSessions((previous) => previous?.map((session) => (
        session.session_id === updated.session_id ? updated : session
      )) ?? [updated]);
      setConversationMessage("Workspace authority revalidated. Every protected action still needs its own approval.");
    } catch (caught) {
      const status = caught instanceof TransportError ? caught.status : null;
      setConversationMessage(status === 503
        ? "Native confirmation is unavailable. This recovered chat remains read-only for protected actions."
        : status === 403
          ? "Authority revalidation was declined or expired. This recovered chat remains read-only."
          : "Workspace authority could not be revalidated. This recovered chat remains read-only.");
    } finally {
      setAuthorityBusy(false);
    }
  }

  function closeNewChatSetup(): void {
    const trigger = newChatTriggerRef.current;
    newChatTriggerRef.current = null;
    setNewChatOpen(false);
    window.setTimeout(() => {
      if (trigger?.isConnected) {
        trigger.focus();
        return;
      }
      const composer = composerInputRef.current;
      if (composer && !composer.disabled) composer.focus({ preventScroll: true });
    }, 0);
  }

  function openAgentSettings(tab: AgentSettingsTab = "readiness"): void {
    setRailCollapsed(false);
    setNewChatOpen(false);
    setSettingsTab(tab);
    setSettingsOpen(true);
  }

  function closeAgentSettings(): void {
    setSettingsOpen(false);
    settingsButtonRef.current?.focus();
  }

  function toggleCatalogRail(): void {
    if (!railCollapsed) {
      setNewChatOpen(false);
      setSettingsOpen(false);
    }
    setRailCollapsed((value) => !value);
  }

  function focusRuntimeControls(): void {
    setRailCollapsed(false);
    setNewChatOpen(false);
    setSettingsOpen(false);
    setRuntimeFocusRequest((value) => value + 1);
  }

  useEffect(() => {
    if (!newChatOpen && !settingsOpen) return;
    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (settingsOpen) closeAgentSettings();
      else closeNewChatSetup();
    };
    window.addEventListener("keydown", closeDrawer);
    return () => window.removeEventListener("keydown", closeDrawer);
  }, [newChatOpen, settingsOpen]);

  useEffect(() => {
    if (!windowMode || !current || current.closing || current.running || currentModelBlocked) return;
    const composer = composerInputRef.current;
    composer?.scrollIntoView?.({ block: "nearest" });
    composer?.focus({ preventScroll: true });
  }, [current?.session_id, current?.closing, current?.running, currentModelBlocked, windowMode]);

  async function mayLeaveWorkspace(confirmLabel = "Discard and continue"): Promise<boolean> {
    if (!workspaceDirty) return true;
    return requestConfirmation({
      title: "Discard workspace changes?",
      description: "Discard the unsaved manual workspace edit?",
      detail: "No workspace file is changed by this confirmation. Only the in-memory manual draft is cleared.",
      confirmLabel,
    });
  }

  useEffect(() => {
    if (windowMode && sessionId) setWindowTargetSessionId(sessionId);
  }, [sessionId, windowMode]);

  useEffect(() => {
    if (!windowMode) return;
    if (dedicatedWindowKey === null) return;
    const controller = new AbortController();
    const close = listenForAgentWindowSelection(dedicatedWindowKey, async (nextSessionId) => {
      if (current?.session_id === nextSessionId || selectedCatalogSession?.session_id === nextSessionId) return true;
      let target = sessions?.find((session) => session.session_id === nextSessionId) ?? null;
      let catalogTarget: AgentCatalogSession | null = null;
      if (target === null) {
        try {
          target = await transport.getAgentSession(nextSessionId, controller.signal);
        } catch (caught) {
          if (!(caught instanceof TransportError && caught.status === 404)) return false;
        }
      }
      if (target === null) {
        const getCatalogSession = transport.getAgentCatalogSession;
        if (!durableCatalogAvailable || getCatalogSession === undefined) return false;
        try {
          catalogTarget = await getCatalogSession(nextSessionId, controller.signal);
        } catch {
          return false;
        }
      }
      if (
        controller.signal.aborted
        || (target?.session_id !== nextSessionId && catalogTarget?.session_id !== nextSessionId)
      ) return false;
      if (workspaceDirty && !(await mayLeaveWorkspace("Discard and switch chat"))) return false;
      if (controller.signal.aborted) return false;
      if (target !== null) {
        const resolved = rememberClosing(target);
        setSessions((previous) => [
          resolved,
          ...(previous ?? []).filter((session) => session.session_id !== resolved.session_id),
        ]);
        setSelectedCatalogSession(null);
        setSavedHistoryState("idle");
        setSelectedProjectId(resolved.settings.project_id ?? null);
        setCurrent(resolved);
        setWindowTargetSessionId(nextSessionId);
      } else if (catalogTarget !== null) {
        setCurrent(null);
        setSelectedCatalogSession(catalogTarget);
        setSavedHistoryState(catalogTarget.retention_policy === "local_history" ? "loading" : "idle");
        setSelectedProjectId(catalogTarget.project_id);
        setWindowTargetSessionId(undefined);
      }
      setSavedHistoryMessage("");
      setNewChatOpen(false);
      setSettingsOpen(false);
      setReviewOpen(false);
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
      followOutput.current = true;
      setFollowingOutput(true);
      setSessionLookupState("idle");
      return true;
    });
    return () => {
      controller.abort();
      close();
    };
  }, [
    current?.session_id,
    dedicatedWindowKey,
    durableCatalogAvailable,
    rememberClosing,
    requestConfirmation,
    selectedCatalogSession?.session_id,
    sessions,
    transport,
    windowMode,
    workspaceDirty,
  ]);

  function changeWorkspace(value: string): void {
    setWorkspace(value);
    setWorkspaceError("");
    setFolderPickerNotice("");
  }

  async function browseForWorkspace(): Promise<void> {
    if (folderPickerBusy || !folderPickerAvailable) return;
    setFolderPickerBusy(true);
    setWorkspaceError("");
    setFolderPickerNotice("");
    try {
      let selected: { status: "selected"; path: string }
        | { status: "cancelled" | "busy" | "unavailable"; path?: null };
      if (nativeFolderPickerAvailable) {
        try {
          selected = await chooseNativeWorkspaceFolder();
        } catch {
          if (
            serverFolderPickerState !== "available"
            || transport.chooseWorkspaceFolder === undefined
          ) throw new Error("folder_picker_unavailable");
          setNativeFolderPickerAvailable(false);
          selected = await transport.chooseWorkspaceFolder();
        }
      } else {
        selected = await transport.chooseWorkspaceFolder!();
      }
      if (
        selected.status === "unavailable"
        && nativeFolderPickerAvailable
        && serverFolderPickerState === "available"
        && transport.chooseWorkspaceFolder !== undefined
      ) {
        setNativeFolderPickerAvailable(false);
        selected = await transport.chooseWorkspaceFolder();
      }
      if (selected.status === "selected") {
        setWorkspace(selected.path);
        setFolderPickerNotice("Workspace folder selected.");
      } else if (selected.status === "cancelled") {
        setFolderPickerNotice("Folder selection cancelled. The workspace path was not changed.");
      } else if (selected.status === "busy") {
        setFolderPickerNotice("Another folder chooser is already open. Finish or cancel it, then try again.");
      } else {
        if (nativeFolderPickerAvailable) setNativeFolderPickerAvailable(false);
        else setServerFolderPickerState("unavailable");
        setFolderPickerNotice("Folder selection is unavailable here. Enter or paste an absolute path.");
      }
    } catch {
      if (nativeFolderPickerAvailable) setNativeFolderPickerAvailable(false);
      else setServerFolderPickerState("unavailable");
      setWorkspaceError("The folder picker did not return a valid folder. Enter or paste an absolute path.");
      workspaceInputRef.current?.focus();
    } finally {
      setFolderPickerBusy(false);
    }
  }

  async function activateModel(alias: string, target: ModelFeedbackTarget): Promise<LocalModelStatus | null> {
    const activate = transport.activateLocalModel;
    if (!activate || !alias || commandCleanupBlocked || modelContext.action || !ownsModelContext(modelContext) || (target === "session" && current?.closing)) return null;
    const action = { alias, kind: "start" as const };
    modelContext.action = action;
    modelContext.readRevision += 1;
    const ownsAction = () => ownsModelContext(modelContext) && modelContext.action === action;
    const contextVersion = sessionContext.current.version;
    const feedbackCurrent = () => ownsAction() && (target !== "session" || sessionContext.current.version === contextVersion);
    setModelActionAlias(alias);
    setModelActionKind("start");
    setModelFeedbackTarget(target);
    setModelError("");
    setModelNotice("");
    try {
      const status = await activate(alias, {
        remember: true,
        fast_attention: true,
        tool_calling: true,
      });
      if (!ownsAction()) return null;
      if (status.record.alias !== alias || status.runtime.state !== "running") {
        throw new Error("model_activation_incomplete");
      }
      setModels((previous) => previous === null ? previous : {
        ...previous,
        models: previous.models.map((model) => model.record.alias === alias ? status : model),
      });
      setModelCatalogState("ready");
      if (feedbackCurrent()) {
        setModelNotice(`${status.record.display_name} is running and ready for the agent.`);
        setCreateMessage("");
        setConversationMessage("");
      }
      return status;
    } catch {
      if (ownsAction()) setModelCatalogState("error");
      if (feedbackCurrent()) setModelError("The model could not be started. Review its runtime settings on the Models page, then retry.");
      return null;
    } finally {
      if (ownsAction()) {
        modelContext.readRevision += 1;
        modelContext.action = null;
        setModelActionAlias("");
        setModelActionKind(null);
      }
    }
  }

  async function deactivateModel(alias: string, target: ModelFeedbackTarget): Promise<void> {
    const deactivate = transport.deactivateLocalModel;
    if (!deactivate || !alias || modelContext.action || !ownsModelContext(modelContext)) return;
    const contextVersion = sessionContext.current.version;
    if (target === "session" && current?.running) {
      setModelFeedbackTarget("session");
      setModelError("Stop the active response before stopping its model.");
      return;
    }
    const action = { alias, kind: "stop" as const };
    modelContext.action = action;
    modelContext.readRevision += 1;
    const ownsAction = () => ownsModelContext(modelContext) && modelContext.action === action;
    const feedbackCurrent = () => ownsAction() && (target !== "session" || sessionContext.current.version === contextVersion);
    setModelActionAlias(alias);
    setModelActionKind("stop");
    setModelFeedbackTarget(target);
    setModelError("");
    setModelNotice("");
    try {
      const openSessions = await transport.listAgentSessions();
      if (!ownsAction()) return;
      setSessions(openSessions.map(rememberClosing));
      const modelHasActiveTurn = openSessions.some((session) => (
        session.model_alias ?? session.settings.model_alias
      ) === alias && session.running);
      if (modelHasActiveTurn) {
        if (feedbackCurrent()) setModelError("Stop every active response using this model before stopping its shared runtime.");
        return;
      }
      const status = await deactivate(alias);
      if (!ownsAction()) return;
      if (status.record.alias !== alias || status.runtime.state !== "stopped") {
        throw new Error("model_deactivation_incomplete");
      }
      setModels((previous) => previous === null ? previous : {
        ...previous,
        models: previous.models.map((model) => model.record.alias === alias ? status : model),
      });
      setModelCatalogState("ready");
      if (feedbackCurrent()) {
        setModelNotice(`${status.record.display_name} stopped. Sessions using it remain open but cannot send until it is restarted.`);
        setCreateMessage("");
        setConversationMessage("");
      }
    } catch {
      if (ownsAction()) setModelCatalogState("error");
      if (feedbackCurrent()) setModelError("The model could not be stopped. Review its runtime on the Models page, then retry.");
    } finally {
      if (ownsAction()) {
        modelContext.readRevision += 1;
        modelContext.action = null;
        setModelActionAlias("");
        setModelActionKind(null);
      }
    }
  }

  async function refreshModelStatus(target: ModelFeedbackTarget): Promise<void> {
    if (modelContext.refresh || modelContext.action || !ownsModelContext(modelContext) || transport.getLocalModels === undefined) return;
    const refresh = {};
    modelContext.refresh = refresh;
    const ownsRefresh = () => ownsModelContext(modelContext) && modelContext.refresh === refresh;
    const contextVersion = sessionContext.current.version;
    setModelRefreshBusy(true);
    setModelFeedbackTarget(target);
    setModelError("");
    setModelNotice("");
    try {
      const overview = await refreshModels();
      if (overview === null && ownsRefresh() && (target !== "session" || sessionContext.current.version === contextVersion)) {
        setModelError("Model status could not be refreshed. Check the Models page or retry here.");
      }
    } finally {
      if (ownsRefresh()) {
        modelContext.refresh = null;
        setModelRefreshBusy(false);
      }
    }
  }

  async function createSession() {
    const path = workspace.trim();
    if (!path || commandCleanupBlocked || busy || modelContext.creation || !ownsModelContext(modelContext) || userPresenceState === "checking" || selectedModelUnavailableForSession) return;
    if (workspaceDirty && !(await mayLeaveWorkspace("Discard and start chat"))) return;
    const creation = {};
    modelContext.creation = creation;
    const ownsCreation = () => ownsModelContext(modelContext) && modelContext.creation === creation;
    setBusy(true);
    setCreatingSession(true);
    setCreateMessage("");
    setModelFeedbackTarget("selection");
    setModelError("");
    setWorkspaceError("");
    try {
      let sessionModel = selectedModel;
      if (selectedModelNeedsActivation && selectedModel) {
        sessionModel = await activateModel(selectedModel.record.alias, "selection");
        if (!ownsCreation()) return;
        if (!sessionModel) {
          setCreateMessage("The chat could not open because the selected model did not start.");
          return;
        }
      }
      const protectedActionsAvailable = userPresenceState === "available";
      const settings: AgentSettings = {
        workspace: path,
        project_id: selectedProjectId,
        model_alias: newSessionModelAlias || sessionModel?.record.alias || null,
        parameters: { temperature, top_p: topP, max_tokens: maxTokens, enable_thinking: thinking },
        instructions: instructions.trim() || null,
        allow_writes: protectedActionsAvailable && allowWrites,
        allow_commands: protectedActionsAvailable && allowCommands,
        allow_web: false,
        max_steps: 10,
        command_timeout_seconds: 120,
        retention_policy: retainHistory ? "local_history" : "metadata_only",
      };
      const created = await transport.createAgentSession(settings);
      if (!ownsCreation()) return;
      // The create response is authoritative. Merging it locally avoids losing
      // a valid chat when the immediately-following list request is stale or
      // temporarily unavailable.
      setSessions((previous) => [
        created,
        ...(previous ?? []).filter((session) => session.session_id !== created.session_id),
      ]);
      if (windowMode) {
        if (dedicatedWindowKey !== null) announceAgentWindowActiveSession(dedicatedWindowKey, created.session_id);
        setWindowTargetSessionId(created.session_id);
      }
      setCurrent(created);
      setNewSessionModelAlias("");
      setSelectedCatalogSession(null);
      setSelectedProjectId(created.settings.project_id ?? selectedProjectId);
      refreshAgentCatalog();
      newChatTriggerRef.current = null;
      setNewChatOpen(false);
      setReviewOpen(false);
      setWorkspaceFileRequest(null);
      setWorkspaceDirty(false);
      setComposerFocusNonce((value) => value + 1);
      setEvents([]);
      setHistoryGap(false);
      setStreamNotice("");
      lastSeq.current = 0;
      followOutput.current = true;
      setFollowingOutput(true);
    } catch (caught) {
      if (!ownsCreation()) return;
      const status = caught instanceof TransportError ? caught.status : null;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (caught instanceof TypeError && transport.getRuntimeHealth !== undefined) {
        setConnectionState("disconnected");
        setCreateMessage("The local app disconnected before the session could start. Reopen the protected Agent window; this page will reconnect automatically.");
      } else if (reason === "command_cleanup_unconfirmed") {
        markCommandCleanup();
      } else if (status === 422 || status === 403) {
        setWorkspaceError(status === 422
          ? "That is not an existing folder. Use an absolute path, not a drive root."
          : "That folder is outside the allowed workspace roots.");
        workspaceInputRef.current?.focus();
      } else if (reason === "web_fetch_unavailable") {
        setCreateMessage("Web fetch is unavailable in this release. No chat or web action was started.");
      } else if (reason === "model_not_ready" || reason === "no_active_model") {
        void refreshModels();
        setModelError(reason === "model_not_ready"
          ? "The selected model is not running. Start it here, then create the session."
          : "No local model is running. Choose an installed model and start it first.");
      } else {
        setCreateMessage(reason === "too_many_sessions"
          ? "Too many open sessions - close one first."
          : status === 409
            ? "Local state changed while the session was starting. Refresh the model status and retry."
            : "The session could not be created.");
      }
    } finally {
      if (ownsCreation()) {
        modelContext.creation = null;
        setCreatingSession(false);
        setBusy(false);
      }
    }
  }

  async function send() {
    const sendingSessionId = current?.session_id;
    const sentDraft = draft;
    const text = draft.trim();
    const attachmentIds = draftAttachments.map((attachment) => attachment.attachment_id);
    if (!current || sendingSessionId === undefined || current.closing || current.running || current.history_write_failed || responseStopping || (!text && attachmentIds.length === 0) || busy || attachmentBusy || attachmentModelMismatch || promptCheckBusy || currentModelBlocked
      || modelContext.action?.alias === (currentModel?.record.alias ?? currentModelAlias)) return;
    const contextVersion = sessionContext.current.version;
    setBusy(true);
    setConversationMessage("");
    followOutput.current = true;
    setFollowingOutput(true);
    try {
      const view = await transport.sendAgentMessage(current.session_id, text, attachmentIds);
      clearSentComposerDraft(sendingSessionId, sentDraft, attachmentIds);
      if (sessionContext.current.version !== contextVersion) return;
      setCurrent(rememberClosing(view));
      clearPromptCheck();
    } catch (caught) {
      if (sessionContext.current.version !== contextVersion) return;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "command_cleanup_unconfirmed") {
        markCommandCleanup(current.session_id);
        setConversationMessage(COMMAND_CLEANUP_MESSAGE);
        return;
      }
      if (reason === "session_closing") {
        markSessionClosing(current.session_id);
        setConversationMessage(CLOSING_SESSION_MESSAGE);
        return;
      }
      if (caught instanceof TypeError && transport.getRuntimeHealth !== undefined) {
        setConnectionState("disconnected");
        setConversationMessage("The local app disconnected before it received this message. Your draft is still here; reopen the protected Agent window and retry after reconnection.");
      } else {
        if (reason === "model_not_ready" || reason === "no_active_model") void refreshModels();
        setConversationMessage(reason === "agent_attachment_model_changed"
          ? "The served model changed after this media was added. Your draft is still here; remove the attachment and add it again for the current model."
          : reason === "agent_attachment_not_found" || reason === "agent_attachment_already_sent" || reason === "agent_attachment_state_changed"
            ? "One staged attachment is no longer available. Your draft is still here; remove it and add it again."
          : reason === "agent_attachment_image_capability_unavailable" || reason === "agent_attachment_audio_capability_unavailable"
            ? "The exact served model no longer verifies this media type. Your draft is still here; remove that attachment or restore the verified model."
          : reason === "model_not_ready"
          ? "This session's model is stopped. Start the session model, then send again."
          : reason === "no_active_model"
            ? "No local model is running. Start a model, then send again."
            : reason === "turn_in_progress"
              ? "The agent is already working on a turn. Wait for it to finish or stop it first."
              : "The message could not be sent.");
      }
    } finally {
      if (ownsModelContext(modelContext)) setBusy(false);
    }
  }

  function changeDraft(value: string) {
    if (current === null) return;
    clearPromptCheck();
    replaceComposerDraft(current.session_id, { text: value, attachments: draftAttachments });
  }

  function changeDraftAttachments(attachments: AgentAttachment[]) {
    if (current === null) return;
    replaceComposerDraft(current.session_id, { text: draft, attachments });
  }

  async function runPromptCheck() {
    const text = draft.trim();
    const checkPrompt = transport.checkPrompt;
    if (!current || current.closing || !checkPrompt || !text || busy || promptCheckBusy || current.running || responseStopping
      || modelContext.action?.alias === (currentModel?.record.alias ?? currentModelAlias)) return;

    const controller = new AbortController();
    promptCheckController.current?.abort();
    promptCheckController.current = controller;
    setPromptCheckBusy(true);
    setPromptCheckError("");
    setPromptCheckNotice("");
    setPromptCheckResult(null);

    try {
      const result = await checkPrompt({
        prompt: text,
        prior_messages: agentPromptContext(events),
        session_id: null,
        provider: "other",
        agent_model: current.model_alias,
        want_commentary: true,
      }, controller.signal);
      if (!controller.signal.aborted) setPromptCheckResult(result);
    } catch (caught) {
      if (controller.signal.aborted) return;
      const status = caught instanceof TransportError ? caught.status : null;
      setPromptCheckError(status === 404
        ? "Prompt Check is not available in this runtime. Your draft was not changed."
        : status === 422
          ? "The draft or available conversation context exceeded the local check limits."
          : "The prompt check did not run. Your draft was not changed.");
    } finally {
      if (promptCheckController.current === controller) {
        promptCheckController.current = null;
        setPromptCheckBusy(false);
      }
    }
  }

  function usePromptRewrite(value: string) {
    if (!value.trim() || current === null) return;
    replaceComposerDraft(current.session_id, { text: value, attachments: draftAttachments });
    clearPromptCheck("Suggested prompt applied. Check it again to validate the revised draft before sending.");
  }

  async function decide(approved: boolean) {
    if (!current || current.closing || !pending?.approval_id || !userPresenceAvailable) return;
    const contextVersion = sessionContext.current.version;
    setConversationMessage("");
    try {
      const view = await transport.decideAgentApproval(current.session_id, pending.approval_id, approved);
      if (sessionContext.current.version !== contextVersion) return;
      setCurrent(rememberClosing(view));
    } catch (caught) {
      if (sessionContext.current.version !== contextVersion) return;
      const status = caught instanceof TransportError ? caught.status : null;
      const reason = caught instanceof TransportError ? caught.reasonCode : null;
      if (reason === "approval_already_settled" || reason === "approval_not_pending") {
        try {
          const latest = await transport.getAgentSession(current.session_id);
          if (sessionContext.current.version !== contextVersion) return;
          setCurrent(rememberClosing(latest));
          setConversationMessage("This approval was already settled and cannot be changed. The current session state was refreshed.");
        } catch {
          if (sessionContext.current.version !== contextVersion) return;
          setConversationMessage("This approval was already settled and cannot be changed. Refresh the chat to load its current state.");
        }
        return;
      }
      setConversationMessage(status === 503
        ? "Native user-presence confirmation is unavailable in this app composition. The agent action remains pending."
        : status === 403
          ? "The native confirmation was declined or expired. The agent action remains pending."
          : "The decision did not reach the agent; refresh before deciding again.");
    }
  }

  async function stop() {
    if (!current || !current.running || current.stopping || responseStopping) return;
    const contextVersion = sessionContext.current.version;
    if (stopRequest.current?.contextVersion === contextVersion) return;
    const operation = { controller: new AbortController(), contextVersion, sessionId: current.session_id };
    stopRequest.current = operation;
    setStopPending(operation);
    try {
      setConversationMessage("");
      const stopped = await transport.stopAgentSession(current.session_id, operation.controller.signal);
      if (sessionContext.current.version === contextVersion && !operation.controller.signal.aborted) {
        setCurrent((previous) => previous?.session_id === operation.sessionId
          ? rememberClosing(previous.last_seq > stopped.last_seq || previous.turns > stopped.turns
            ? { ...previous, closing: previous.closing || stopped.closing }
            : { ...stopped, closing: previous.closing || stopped.closing })
          : previous);
      }
    } catch {
      if (sessionContext.current.version !== contextVersion || operation.controller.signal.aborted) return;
      setConversationMessage("The active response could not be stopped. Its live status will continue to refresh.");
    } finally {
      if (stopRequest.current === operation) stopRequest.current = null;
      setStopPending((previous) => previous === operation ? null : previous);
    }
  }

  async function openCurrentWindow(): Promise<void> {
    if (!current || windowOpenBusy) return;
    const openingSessionId = current.session_id;
    const contextVersion = sessionContext.current.version;
    setWindowOpenBusy(true);
    setConversationMessage("");
    try {
      const result = await openAgentChatWindow(openingSessionId);
      if (result.windowKey !== null) {
        windowSelectionOwnerRef.current?.assign(result.windowKey, openingSessionId);
      }
      if (sessionContext.current.version !== contextVersion) return;
      if (result.status === "unavailable") {
        setConversationMessage("The separate Agent window could not be opened. In a browser, allow one popup for this local app and retry.");
      } else if (result.selection === "unconfirmed") {
        setConversationMessage("The Agent window is open, but automatic chat selection was not confirmed. Choose this chat from its Projects list.");
      } else if (result.status === "focus_unconfirmed") {
        setConversationMessage("The existing Agent window received this chat, but Windows did not confirm foreground focus.");
      }
    } finally {
      setWindowOpenBusy(false);
    }
  }

  async function requestCloseLiveSession(session: AgentSessionView): Promise<void> {
    const retained = session.settings.retention_policy === "local_history";
    const discardsWorkspace = current?.session_id === session.session_id && workspaceDirty;
    const accepted = await requestConfirmation({
      title: "Close live chat?",
      description: retained
        ? `Its retained conversation remains available and can be resumed later.${discardsWorkspace ? " The unsaved manual workspace edit in this chat will also be discarded." : ""}`
        : `Its navigation entry remains, but metadata-only conversation content cannot be reopened.${discardsWorkspace ? " The unsaved manual workspace edit in this chat will also be discarded." : ""}`,
      detail: "This closes the live Agent session. It does not delete its project or durable catalog entry.",
      confirmLabel: "Close chat",
    });
    if (accepted) void closeSession(session.session_id, discardsWorkspace);
  }

  async function closeSession(id: string, workspaceDiscardConfirmed = false) {
    if (commandCleanupBlocked) { setConversationMessage(COMMAND_CLEANUP_MESSAGE); return; }
    if (closeRequests.current.has(id)) return;
    if (current?.session_id === id && !workspaceDiscardConfirmed && workspaceDirty && !(await mayLeaveWorkspace("Discard and retry close"))) return;
    closeRequests.current.add(id);
    try {
      try {
        await transport.deleteAgentSession(id);
      } catch (caught) {
        // Another window may have finished closing this same session already.
        // An authoritative absence must not leave an endless retry card.
        if (!(caught instanceof TransportError && caught.status === 404)) throw caught;
      }
      if (sessionContext.current.transport !== transport) return;
      closingSessions.current.ids.delete(id);
      closingSessions.current.cleanupIds.delete(id);
      if (closingSessions.current.cleanupIds.size === 0) {
        closingSessions.current.cleanup = false;
      }
      setSessions((previous) => previous?.filter((session) => session.session_id !== id) ?? []);
      if (sessionContext.current.id === id) {
        setCurrent(null);
        setSelectedCatalogSession(null);
        setReviewOpen(false);
        setWorkspaceFileRequest(null);
        setWorkspaceDirty(false);
        setEvents([]);
        setConversationMessage("");
        setHistoryGap(false);
        setStreamNotice("");
        lastSeq.current = 0;
      }
      refreshAgentCatalog();
      await refreshSessions();
    } catch (caught) {
      if (sessionContext.current.transport !== transport) return;
      if (caught instanceof TransportError && caught.reasonCode === "command_cleanup_unconfirmed") {
        markCommandCleanup(id);
        setConversationMessage(COMMAND_CLEANUP_MESSAGE);
        return;
      }
      const waiting = caught instanceof TransportError && caught.reasonCode === "session_stop_timeout";
      if (waiting) markSessionClosing(id);
      if (sessionContext.current.id === id) setConversationMessage(waiting ? CLOSING_SESSION_MESSAGE : "The session could not be closed.");
    } finally {
      closeRequests.current.delete(id);
    }
  }

  if (unavailable) {
    return (
      <section aria-labelledby="agent-title" className="agent">
        <h1 id="agent-title">Agent workspace</h1>
        <p className="agent__note">The local agent is not available in this runtime.</p>
        <p className="agent__note">Open the local Agent desktop application to select a folder, start a model and create a chat session. Supported protected actions still need a separate native confirmation.</p>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="agent-title"
      className={`agent${windowMode ? " agent--window" : ""}`}
      data-active-session={current !== null || selectedCatalogSession !== null ? "true" : "false"}
      data-workspace-open={workspaceVisible ? "true" : "false"}
    >
      <header className="agent__head">
        <div>
          <p className="eyebrow">Agent · a local model working in one folder</p>
          <h1 id="agent-title">{current
            ? (current.settings.title || current.settings.workspace.split(/[\\/]/).filter(Boolean).pop())
            : selectedCatalogSession?.title ?? "Agent workspace"}</h1>
          {!windowMode && current === null && selectedCatalogSession === null && (
            <p className="agent__lede">
              A local coding workspace with projects, durable or metadata-only chats, files, reviewed changes and protected actions. Retained conversations reopen after restart without replaying approvals.
            </p>
          )}
        </div>
      </header>

      {connectionDisconnected && (
        <div className="agent__connection-error" role="alert">
          <strong>Local app disconnected</strong>
          <span>
            The page is still visible, but its local server is no longer running. Reopen the protected Agent desktop window and keep it open; this page will reconnect automatically. Chats marked Save locally can be resumed after restart; metadata-only conversation content cannot.
          </span>
        </div>
      )}

      <a
        className="skip-link agent__skip-conversation"
        href="#agent-conversation"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("agent-conversation")?.focus();
        }}
      >
        Skip projects and settings; go to conversation
      </a>

      <div className={`agent__layout${windowMode ? " agent__layout--window" : ""}${current ? " agent__layout--session" : ""}`} data-rail-collapsed={railCollapsed ? "true" : undefined}>
          <aside className="agent__side" data-collapsed={railCollapsed ? "true" : undefined}>
            <div className="agent__side-scroll">
              <AgentCatalogRail
              collapsed={railCollapsed}
              currentSessionId={current?.session_id ?? selectedCatalogSession?.session_id}
              draftSessionIds={draftSessionIds}
              disabled={commandCleanupBlocked || connectionDisconnected}
              newChatDisabled={connectionDisconnected}
              liveSessions={sessions}
              onCloseLiveSession={(session) => { void requestCloseLiveSession(session); }}
              onNewChat={beginNewChat}
               onOpenLiveSession={(session) => { void openLiveSession(session); }}
               onOpenUnavailableSession={(session) => { void openUnavailableSession(session); }}
               onOpenSavedMessage={openSavedMessage}
               onSessionDeleted={acceptCatalogSessionDeleted}
               onSessionUpdated={acceptCatalogSessionUpdate}
               onForkSession={transport.forkAgentSession === undefined
                ? undefined
                : async (session, title, signal) => {
                  await forkCatalogSession(session, title, undefined, signal);
                }}
              onInitialCatalogLoad={setStartupCatalogSession}
              onProjectChange={handleCatalogProjectChange}
              onToggleCollapsed={toggleCatalogRail}
              refreshKey={catalogRefreshKey}
              selectedProjectId={selectedProjectId}
              transport={transport}
            />
              {newChatOpen && (
                <section
                  aria-labelledby="agent-new-chat-title"
                  className="agent__drawer agent__new-shell"
                  id="agent-new-chat-drawer"
                  role="dialog"
                >
                  <header className="agent__drawer-head">
                    <span>
                      <small>Project workspace</small>
                      <h2 id="agent-new-chat-title">New session</h2>
                    </span>
                    <button aria-label="Close new chat setup" className="button button--ghost" onClick={closeNewChatSetup} type="button">Close</button>
                  </header>
                  <form aria-busy={creatingSession} className="agent__new" onSubmit={(event) => { event.preventDefault(); void createSession(); }}>
              <div className="agent__workspace-field">
                <label htmlFor="agent-workspace-folder">Workspace folder (absolute path)</label>
                <div className="agent__workspace-entry">
                  <input
                    aria-describedby="agent-workspace-help agent-workspace-picker-status"
                    aria-errormessage={workspaceError ? "agent-workspace-error" : undefined}
                    aria-invalid={workspaceError ? "true" : undefined}
                    aria-label="Workspace folder"
                    autoComplete="off"
                    id="agent-workspace-folder"
                    onChange={(event) => changeWorkspace(event.currentTarget.value)}
                    placeholder="D:\\projects\\example"
                    ref={workspaceInputRef}
                    spellCheck={false}
                    type="text"
                    value={workspace}
                  />
                  {folderPickerAvailable || folderPickerChecking ? (
                    <button
                      className="button button--ghost"
                      disabled={folderPickerBusy || folderPickerChecking || creatingSession}
                      onClick={() => void browseForWorkspace()}
                      title="Choose a local workspace folder"
                      type="button"
                    >
                      {folderPickerBusy ? "Choosing…" : folderPickerChecking ? "Checking…" : "Browse…"}
                    </button>
                  ) : (
                    <span className="agent__workspace-path-mode">Enter path</span>
                  )}
                </div>
                <p className="agent__note" id="agent-workspace-help">
                  {folderPickerAvailable
                    ? "Browse your PC, or enter its absolute path. Choosing only fills this field: no model or session is required, and no files are scanned yet."
                    : folderPickerChecking
                      ? "Checking whether this local app can open the Windows folder chooser. You can still enter an absolute path."
                      : "No model is required. The Windows folder chooser is unavailable in this app composition, so enter or paste an existing absolute path."}
                </p>
                <p className="agent__note" id="agent-workspace-picker-status" role="status">
                  {folderPickerNotice}
                </p>
                {workspaceError && <p className="agent__error" id="agent-workspace-error" role="alert">{workspaceError}</p>}
              </div>
              <div className="agent__model-control">
                <label>
                  <span>Start with a model (optional)</span>
                  <select
                    aria-describedby="agent-model-status"
                    aria-label="Agent model"
                    onChange={(event) => {
                      setNewSessionModelAlias(event.currentTarget.value);
                      setModelFeedbackTarget("selection");
                      setModelError("");
                      setModelNotice("");
                    }}
                    value={newSessionModelAlias}
                  >
                    <option value="">Choose later in chat · no model</option>
                    {(models?.models ?? []).map((model) => (
                      <option key={model.record.alias} value={model.record.alias}>
                        {model.record.display_name} · {runtimeStateLabel(model.runtime.state)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="agent__model-state" id="agent-model-status">
                  <p className="agent__note" role="status">
                    {commandCleanupBlocked
                      ? "Model status does not establish command cleanup. Agent work is paused."
                      : connectionDisconnected
                      ? "The local app is disconnected; cached model status is not usable."
                      : modelCatalogState === "loading"
                      ? "Checking which local models are ready…"
                      : selectedModel === null && !newSessionModelAlias
                        ? "The chat will open without a model. Choose and start one in Model & context beside the message box."
                      : modelCatalogState === "error"
                        ? "Model status could not be refreshed. The server will verify it before the first message."
                      : modelCatalogState === "unavailable"
                          ? "Model status will be verified when the session starts."
                            : selectedModel === null
                            ? "That model is not registered. Choose an installed model."
                            : selectedModel.runtime.state === "running"
                              ? `${selectedModel.record.display_name} is running and ready.`
                              : selectedModel.runtime.state === "starting"
                                ? `${selectedModel.record.display_name} is starting. The chat will be available when it is ready.`
                                : transport.activateLocalModel
                                  ? `${selectedModel.record.display_name} is ${runtimeStateLabel(selectedModel.runtime.state)}. Opening the chat will start it automatically.`
                                  : `${selectedModel.record.display_name} is ${runtimeStateLabel(selectedModel.runtime.state)} and must be started on the Models page.`}
                  </p>
                  {(modelCatalogState === "error" || selectedModel?.runtime.state === "starting") && transport.getLocalModels && (
                    <button
                      className="button button--ghost"
                      disabled={modelRefreshBusy || Boolean(modelActionAlias)}
                      onClick={() => void refreshModelStatus("selection")}
                      type="button"
                    >
                      {modelRefreshBusy ? "Refreshing…" : "Refresh model status"}
                    </button>
                  )}
                  {modelCatalogState === "ready" && selectedModel === null && (models?.models.length ?? 0) === 0 && (
                    <a className="button button--ghost" href="/models">Open Models</a>
                  )}
                  {modelFeedbackTarget === "selection" && modelError && <p className="agent__error" role="alert">{modelError}</p>}
                  {modelFeedbackTarget === "selection" && modelNotice && <p className="agent__notice" role="status">{modelNotice}</p>}
                </div>
              </div>
              <details className="agent__parameters">
                <summary>Model parameters</summary>
                <div className="agent__parameters-grid">
                  <label>
                    <span>Temperature · {temperature.toFixed(2)}</span>
                    <input aria-label="Temperature" max={2} min={0} onChange={(e) => setTemperature(Number(e.currentTarget.value))} step={0.05} type="range" value={temperature} />
                  </label>
                  <label>
                    <span>Top-p · {topP.toFixed(2)}</span>
                    <input aria-label="Top-p" max={1} min={0.05} onChange={(e) => setTopP(Number(e.currentTarget.value))} step={0.05} type="range" value={topP} />
                  </label>
                  <label>
                    <span>Max tokens per step</span>
                    <input aria-label="Max tokens" max={8192} min={64} onChange={(e) => setMaxTokens(Math.max(64, Math.min(8192, Number(e.currentTarget.value) || 1400)))} step={1} type="number" value={maxTokens} />
                  </label>
                  <label className="agent__toggle"><input checked={thinking} onChange={(e) => setThinking(e.currentTarget.checked)} type="checkbox" /><span>Thinking mode (models that support it reason before answering; slower)</span></label>
                </div>
                <label>
                  <span>Standing instructions (optional, kept for the whole session)</span>
                  <textarea aria-label="Standing instructions" onChange={(e) => setInstructions(e.currentTarget.value)} placeholder="e.g. Answer in Polish. Keep documents as Markdown in docs/." rows={2} value={instructions} />
                </label>
              </details>
              <fieldset className="agent__retention">
                <legend>Conversation history</legend>
                <label className="agent__retention-option">
                  <input checked={retainHistory} name="agent-retention" onChange={() => setRetainHistory(true)} type="radio" />
                  <span><strong>Save locally</strong><small>Messages, completed replies, bounded activity, and turn receipts survive restart in the private Agent database.</small></span>
                </label>
                <label className="agent__retention-option">
                  <input checked={!retainHistory} name="agent-retention" onChange={() => setRetainHistory(false)} type="radio" />
                  <span><strong>Metadata only</strong><small>Only the project, chat name, workspace, and model remain. Conversation history disappears when this app process closes.</small></span>
                </label>
                <p className="agent__note">Approvals, raw tool arguments/output, and reusable mutation authority are never restored.</p>
              </fieldset>
              <fieldset
                aria-describedby="agent-permission-status"
                className="agent__permissions"
                disabled={!userPresenceAvailable}
              >
                <legend>Protected actions</legend>
                <label className="agent__toggle"><input checked={allowWrites} onChange={(e) => setAllowWrites(e.currentTarget.checked)} type="checkbox" /><span>May write files (each write needs approval, diff shown)</span></label>
                <label className="agent__toggle"><input checked={allowCommands} onChange={(e) => setAllowCommands(e.currentTarget.checked)} type="checkbox" /><span>May run commands (each command needs approval)</span></label>
                <label className="agent__toggle"><input checked={false} disabled readOnly type="checkbox" /><span>Web fetch unavailable (no governed fetcher is installed in this release)</span></label>
              </fieldset>
              <div className="agent__permission-state">
                <p
                  className="agent__note"
                  id="agent-permission-status"
                  role={userPresenceState === "error" ? "alert" : "status"}
                >
                  {userPresenceState === "checking"
                    ? "Checking whether native confirmation is available…"
                    : userPresenceState === "available"
                      ? "Optional. Every selected protected action still requires a separate native confirmation. Closing the live process does not preserve approvals or reusable authority."
                      : userPresenceState === "error"
                        ? "Native confirmation could not be verified. New sessions stay read-only."
                        : <>
                            This browser can start read-only sessions. For Browse and protected actions on Windows, stop the current <code>serve</code> process and run <code>prompt-enhancer agent-desktop</code>.
                          </>}
                </p>
                {userPresenceState === "error" && transport.getUserPresenceCapability && (
                  <button className="button button--ghost" onClick={() => setUserPresenceRetryNonce((value) => value + 1)} type="button">
                    Retry confirmation check
                  </button>
                )}
              </div>
              <p className="agent__launch-note" role="status">
                {commandCleanupBlocked ? current ? "New Agent sessions are paused until command cleanup is confirmed." : COMMAND_CLEANUP_MESSAGE
                  : selectedModel === null && !newSessionModelAlias
                    ? "Opening chat creates the project session now. Choose and start a model before sending the first message."
                  : selectedModelNeedsActivation && transport.activateLocalModel
                  ? "One action will start the selected model, create the session, and focus the message box."
                  : "Opening chat creates the session and focuses the message box; the model runtime remains separate and reusable."}
              </p>
              <button
                aria-describedby={createMessage ? "agent-create-error" : undefined}
                className="button button--primary"
                disabled={commandCleanupBlocked || busy || creatingSession || folderPickerBusy || userPresenceState === "checking" || selectedModelUnavailableForSession || !workspace.trim()}
                type="submit"
              >
                {commandCleanupBlocked ? "Agent paused for cleanup" : creatingSession
                  ? selectedModelNeedsActivation ? "Starting model & opening chat…" : "Opening chat…"
                  : connectionDisconnected
                    ? "Local app disconnected"
                    : !workspace.trim()
                      ? "Choose workspace to open chat"
                    : modelCatalogState === "loading" && Boolean(newSessionModelAlias)
                      ? "Checking model…"
                      : modelCatalogState === "ready" && selectedModel === null && newSessionModelAlias
                        ? "Choose an installed model"
                        : selectedModel === null
                          ? userPresenceAvailable ? "Open chat without model" : "Open read-only chat without model"
                        : selectedModel?.runtime.state === "starting"
                          ? "Model is starting…"
                          : selectedModelNeedsActivation && transport.activateLocalModel === undefined
                            ? "Start model first"
                            : selectedModelNeedsActivation
                              ? userPresenceAvailable ? "Start model & open chat" : "Start model & open read-only chat"
                              : userPresenceAvailable ? "Open chat session" : "Open read-only chat"}
              </button>
                    {createMessage && <p className="agent__error" id="agent-create-error" role="alert">{createMessage}</p>}
                  </form>
                </section>
              )}
              {sessionListError && (
                <div className="agent__session-list-error" role="alert">
                  <p>Sessions could not be refreshed. Any chat already open remains usable.</p>
                  <button className="button button--ghost" onClick={() => void refreshSessions()} type="button">Retry sessions</button>
                </div>
              )}
            </div>
            <div className="agent__settings-launch">
              <button
                aria-controls="agent-settings-drawer"
                aria-expanded={settingsOpen}
                className="button button--ghost agent__settings-trigger"
                onClick={() => settingsOpen ? closeAgentSettings() : openAgentSettings()}
                ref={settingsButtonRef}
                type="button"
              >
                <span>Agent settings</span>
                <small>Readiness · connections · MCP Store · owner checks · sharing</small>
              </button>
              {settingsOpen && (
                <section
                  aria-labelledby="agent-settings-title"
                  className="agent__drawer agent__settings-drawer"
                  data-settings-tab={settingsTab}
                  id="agent-settings-drawer"
                  role="dialog"
                >
                  <header className="agent__drawer-head">
                    <span>
                      <small>Secondary tools</small>
                      <h2 id="agent-settings-title">Agent settings</h2>
                    </span>
                    <button aria-label="Close agent settings" className="button button--ghost" onClick={closeAgentSettings} type="button">Close</button>
                  </header>
                  <TabList
                    className="agent__settings-tabs"
                    idPrefix="agent-settings"
                    label="Agent settings sections"
                    onChange={setSettingsTab}
                    tabs={AGENT_SETTINGS_TABS}
                    value={settingsTab}
                  />
                  <div className="agent__settings-body">
                    {settingsTab === "readiness" && (
                      <div aria-labelledby={tabId("agent-settings", "readiness")} id={tabPanelId("agent-settings", "readiness")} role="tabpanel">
                        <AgentReadinessPanel
                          onOpenConnections={() => setSettingsTab("connections")}
                          onOpenOwnerChecks={() => setSettingsTab("acceptance")}
                          transport={transport}
                          userPresenceAvailable={userPresenceAvailable}
                        />
                      </div>
                    )}
                    {settingsTab === "connections" && (
                      <div aria-labelledby={tabId("agent-settings", "connections")} id={tabPanelId("agent-settings", "connections")} role="tabpanel">
                        <AgentMcpProjectToolsPanel
                          onOpenStore={openMcpStore}
                          projectId={current?.settings.project_id ?? selectedProjectId}
                          refreshKey={mcpProjectionRevision}
                          transport={transport}
                        />
                        <AgentControllerPanel
                          acceptanceRun={externalControllerAcceptanceRun}
                          onAcceptanceEvidence={recordExternalControllerEvidence}
                          onAcceptanceObservation={observeExternalControllerEvidence}
                          onAcceptanceRunChange={setExternalControllerAcceptanceRun}
                          selectedProjectId={current?.settings.project_id ?? selectedProjectId}
                          selectedSessionId={current?.settings.project_id ? current.session_id : null}
                          transport={transport}
                          userPresenceAvailable={userPresenceAvailable}
                        />
                      </div>
                    )}
                    {settingsTab === "store" && (
                      <div aria-labelledby={tabId("agent-settings", "store")} id={tabPanelId("agent-settings", "store")} role="tabpanel">
                        <Suspense fallback={<p role="status">Loading MCP Store…</p>}>
                          <AgentMcpStorePanel
                            acceptanceRun={trustedMcpAcceptanceRun}
                            activeEventHead={activeEventHead}
                            activeProjectId={activeAgentProjectId}
                            activeSessionId={current?.session_id ?? null}
                            onAcceptanceEvidence={recordTrustedMcpAcceptanceEvidence}
                            onAcceptanceRunChange={setTrustedMcpAcceptanceRun}
                            onManagedStateChange={refreshMcpProjection}
                            transport={transport}
                            userPresenceAvailable={userPresenceAvailable}
                          />
                        </Suspense>
                      </div>
                    )}
                    {settingsTab === "acceptance" && (
                      <div aria-labelledby={tabId("agent-settings", "acceptance")} id={tabPanelId("agent-settings", "acceptance")} role="tabpanel">
                        <AgentNativeAcceptancePanel
                          acceptanceRun={nativeAcceptanceRun}
                          artifactViewRevision={artifactViewRevision}
                          current={current}
                          events={events}
                          onAcceptanceRunChange={setNativeAcceptanceRun}
                          onRuntimeStatus={setRuntimeCoordinator}
                          reviewOpen={workspaceVisible}
                          transport={transport}
                          userPresenceAvailable={userPresenceAvailable}
                        />
                      </div>
                    )}
                    {settingsTab === "sharing" && (
                      <div aria-labelledby={tabId("agent-settings", "sharing")} id={tabPanelId("agent-settings", "sharing")} role="tabpanel">
                        <TeamFoldersPanel onUseAsWorkspace={changeWorkspace} transport={transport} />
                      </div>
                    )}
                  </div>
                </section>
              )}
            </div>
          </aside>

        <div
          className="agent__workbench"
          data-has-workspace={workspaceVisible ? "true" : "false"}
          style={{ "--agent-review-width": `${reviewWidth}px` } as CSSProperties}
        >
          {current && workspaceVisible && (
            <button
              aria-label="Close files and review drawer"
              className="agent__review-backdrop"
              onClick={() => { void hideWorkspace(); }}
              type="button"
            />
          )}
          {current && workspaceVisible && (
            <AgentReviewDrawer
              activeView={reviewView}
              changesPanel={(
                <AgentChangeSetPanel
                  artifactPaths={artifactPathSet}
                  fileActionsDisabled={current.closing || connectionDisconnected}
                  onAddArtifact={artifactProjectId !== null && transport.previewAgentArtifactCapture !== undefined && transport.captureAgentArtifact !== undefined ? addChangeArtifact : undefined}
                  onOpenArtifact={artifactViewerTransport !== null ? openChangeArtifact : undefined}
                  onOpenFile={openReceiptFile}
                  onRestored={handleChangeRestored}
                  refreshKey={changeSetRefreshKey}
                  reviewRequest={currentChangeReviewRequest}
                  sessionId={current.session_id}
                  transport={transport}
                  userPresenceAvailable={userPresenceAvailable}
                />
              )}
              filesPanel={(
                <AgentWorkspacePane
                  blockedReason={commandCleanupBlocked ? COMMAND_CLEANUP_MESSAGE : undefined}
                  fileRequest={currentFileRequest}
                  key={current.session_id}
                  onApplied={handleWorkspaceApplied}
                  onArtifactCaptured={() => setArtifactsRefreshKey((value) => value + 1)}
                  onCaptureUncertain={() => setArtifactsRefreshKey((value) => value + 1)}
                  onDirtyChange={handleWorkspaceDirty}
                  pendingWrite={pending}
                  projectId={artifactProjectId}
                  refreshKey={changeSetRefreshKey}
                  sessionId={current.session_id}
                  transport={transport}
                  userPresenceAvailable={userPresenceAvailable}
                />
              )}
              onActiveViewChange={setReviewView}
              onClose={() => { void hideWorkspace(); }}
            />
          )}
          {current && workspaceVisible && (
            <div
              aria-label="Resize files and review drawer"
              aria-orientation="vertical"
              aria-valuemax={REVIEW_DRAWER_MAX_PX}
              aria-valuemin={REVIEW_DRAWER_MIN_PX}
              aria-valuenow={reviewWidth}
              className="agent__review-resizer"
              onKeyDown={resizeReviewWithKeyboard}
              onPointerDown={beginReviewResize}
              role="separator"
              tabIndex={0}
              title="Drag, or use Left and Right arrow keys, to resize files and review"
            />
          )}
          <section
            aria-label="Agent conversation"
            className="agent__main"
            id="agent-conversation"
            tabIndex={-1}
          >
          {!current && selectedCatalogSession ? (
            selectedCatalogSession.retention_policy === "local_history" ? (
              <RetainedHistoryView
                artifactsPanel={artifactViewerTransport !== null
                  && artifactProjectId === selectedCatalogSession.project_id
                  && artifactSessionId === selectedCatalogSession.session_id
                  && (artifactsLoading || artifactsError !== "" || artifactItems.length > 0 || (artifactCounts?.total ?? 0) > 0 || selectedCatalogSession.turn_count > 0)
                  ? (
                    <AgentArtifactsPanel
                      artifacts={artifactItems}
                      canLoadMore={artifactNextOffset !== null}
                      counts={artifactCounts}
                      error={artifactsError}
                      loading={artifactsLoading}
                      onLoadMore={() => { void loadMoreArtifacts(); }}
                      onOpenSourceTurn={openArtifactSourceTurn}
                      onViewerReady={() => setArtifactViewRevision((value) => value + 1)}
                      onRefresh={() => setArtifactsRefreshKey((value) => value + 1)}
                      onViewChange={setArtifactView}
                      pageError={artifactPageError}
                      pageLoading={artifactPageLoading}
                      projectId={artifactProjectId}
                      sessionId={artifactSessionId}
                      transport={artifactViewerTransport}
                      userPresenceAvailable={userPresenceAvailable}
                      view={artifactView}
                    />
                  )
                  : null}
                events={events}
                focusEventRequest={savedMessageFocus !== null
                  && selectedCatalogSession?.session_id === savedMessageFocus.sessionId
                  && selectedCatalogSession.project_id === savedMessageFocus.projectId
                  ? savedMessageFocus
                  : null}
                focusTurnRequest={artifactTurnFocus}
                exportBusy={exportBusy}
                forkBusy={forkBusy}
                forkSupported={transport.forkAgentSession !== undefined}
                message={savedHistoryMessage}
                onClear={() => setSelectedCatalogSession(null)}
                onExport={() => void exportSelectedHistory()}
                onFork={(throughEventSeq) => {
                  void forkCatalogSession(
                    selectedCatalogSession,
                    undefined,
                    throughEventSeq,
                  ).catch(() => undefined);
                }}
                onReviseTurn={turnRevisionSupported
                  ? (turnId, mode) => { void reviseTurn(turnId, mode); }
                  : undefined}
                onNewChat={(trigger) => beginNewChat(selectedCatalogSession.project_id, trigger)}
                onResume={() => void resumeSelectedSession()}
                resumeSupported={transport.resumeAgentSession !== undefined}
                exportSupported={transport.exportAgentHistory !== undefined}
                resumeBusy={resumeBusy}
                session={selectedCatalogSession}
                state={savedHistoryState}
                turnRevisionBusy={turnRevisionBusy}
              />
            ) : (
              <article className="agent__history-stub" aria-labelledby="agent-history-stub-title">
                <span className="agent__history-stub-badge">Metadata only · history unavailable</span>
                <h2 id="agent-history-stub-title">{selectedCatalogSession.title}</h2>
                <p>
                  This navigation entry survived restart, but this chat was created with Metadata only. Its messages were not stored; nothing has been reconstructed or replaced with an empty transcript.
                </p>
                <dl>
                  <div><dt>Workspace</dt><dd><code>{selectedCatalogSession.workspace}</code></dd></div>
                  <div><dt>Model</dt><dd>{selectedCatalogSession.model_alias ?? "Not recorded"}</dd></div>
                  <div><dt>History</dt><dd>Metadata only · unavailable</dd></div>
                </dl>
                <div className="agent__history-stub-actions">
                  <button className="button button--primary" onClick={(event) => beginNewChat(selectedCatalogSession.project_id, event.currentTarget)} type="button">Start a new chat in this project</button>
                  <button className="button button--ghost" onClick={() => setSelectedCatalogSession(null)} type="button">Clear selection</button>
                </div>
              </article>
            )
          ) : !current ? (
            <div className="agent__empty">
              <p className="agent__note" role="status">
                {commandCleanupBlocked ? COMMAND_CLEANUP_MESSAGE : windowMode && sessionLookupState === "loading"
                  ? "Opening this Agent session…"
                  : windowMode && sessionLookupState === "missing"
                    ? "This in-memory session is no longer available. It may have been closed or cleared when the local app restarted."
                    : windowMode && sessionLookupState === "error"
                      ? "This Agent window could not reach its session. Return to the Agent page and open it again."
                      : windowMode
                        ? "This window has no session. Open one from the Agent page."
                        : sessionListError
                          ? "Existing live sessions could not be determined. Retry the session list before assuming there is no open chat."
                        : !workspace.trim()
                          ? <><span>No session yet.</span>{" "}Open New chat and enter a workspace folder. No model is required; choose one beside the message box after the chat opens.</>
                          : selectedModelUnavailableForSession
                            ? "The optional setup model is not ready. Clear it to open without a model, or wait for it to become ready."
                            : "Open chat now. Model & context will appear beside the message box."}
              </p>
              {windowMode && (sessionLookupState === "missing" || sessionLookupState === "error") && (
                <a className="button button--ghost" href="/agent">Return to Agent</a>
              )}
            </div>
          ) : (
            <>
              <div className="agent__session-top">
              {current.history_write_failed && (
                <div className="agent__history-fault" role="alert">
                  <strong>Local history stopped accepting events</strong>
                  <span>This chat is paused to prevent a false durability claim. Export what is retained, then open a new chat after checking local storage.</span>
                </div>
              )}
              {current.recovered && !current.authority_revalidated && (
                <section aria-labelledby="agent-recovery-authority-title" className="agent__recovery-authority">
                  <div>
                    <span className="agent__history-stub-badge">Recovered · protected actions off</span>
                    <h2 id="agent-recovery-authority-title">Revalidate this workspace before changing it</h2>
                    <p>Visible chat context was restored, but approvals and mutation authority were not. Reads remain available.</p>
                  </div>
                  <fieldset disabled={!userPresenceAvailable || authorityBusy}>
                    <legend>Capabilities to re-enable</legend>
                    <label className="agent__toggle"><input checked={recoveryAllowWrites} onChange={(event) => setRecoveryAllowWrites(event.currentTarget.checked)} type="checkbox" /><span>File writes</span></label>
                    <label className="agent__toggle"><input checked={recoveryAllowCommands} onChange={(event) => setRecoveryAllowCommands(event.currentTarget.checked)} type="checkbox" /><span>Commands</span></label>
                    <label className="agent__toggle"><input checked={false} disabled readOnly type="checkbox" /><span>Web fetch unavailable in this release</span></label>
                  </fieldset>
                  <button className="button button--primary" disabled={!userPresenceAvailable || authorityBusy || transport.revalidateAgentAuthority === undefined} onClick={() => void revalidateRecoveredAuthority()} type="button">
                    {authorityBusy ? "Revalidating…" : userPresenceAvailable ? "Confirm and revalidate" : "Native confirmation required"}
                  </button>
                </section>
              )}
              <AgentConversationHeader
                actionCount={toolCallCount}
                actions={(
                  <>
                    <button
                      aria-expanded={workspaceVisible}
                      className="button button--ghost"
                      onClick={() => {
                        if (workspaceVisible) void hideWorkspace();
                        else {
                          setReviewView("files");
                          setReviewOpen(true);
                        }
                      }}
                      type="button"
                    >{workspaceVisible ? "Close files & review" : "Files & review"}</button>
                    <button
                      aria-controls="agent-settings-drawer"
                      aria-expanded={settingsOpen && settingsTab === "connections"}
                      aria-haspopup="dialog"
                      className="button button--ghost"
                      onClick={openProjectTools}
                      type="button"
                    >Project tools</button>
                    {current.closing && !commandCleanupBlocked && (
                      <button className="button button--ghost" disabled={connectionDisconnected} onClick={() => void closeSession(current.session_id)} type="button">Retry closing session</button>
                    )}
                  </>
                )}
                activity={activityState}
                details={(
                  <div className="agent__meta">
                    <code>{current.settings.workspace}</code>
                    <span>
                      {current.model_alias ?? "no model"}
                      {current.settings.parameters ? " · t=" + current.settings.parameters.temperature.toFixed(2) + " · " + String(current.settings.parameters.max_tokens) + " tok" + (current.settings.parameters.enable_thinking ? " · thinking" : "") : ""}
                      {" · "}{current.settings.retention_policy === "local_history" ? "saved locally" : "metadata only"}
                      {current.recovered ? " · recovered" : ""}
                      {" · "}{current.settings.allow_writes ? "writes" : "no writes"} · {current.settings.allow_commands ? "commands" : "no commands"} · {current.settings.allow_web ? "web" : "no web"}
                    </span>
                    {!windowMode && (
                      <button className="button button--ghost" disabled={windowOpenBusy} onClick={() => void openCurrentWindow()} type="button">
                        {windowOpenBusy ? "Opening window…" : "Open separate window"}
                      </button>
                    )}
                  </div>
                )}
                reasoningLabel={hasVisibleReasoning ? "Reasoning visible" : reasoningEnabled ? "Reasoning enabled" : "Reasoning off"}
                reasoningState={hasVisibleReasoning ? "visible" : reasoningEnabled ? "enabled" : "off"}
                runtimeActions={(
                  <>
                    {!runtimeCoordinatorAvailable && currentModel && currentModel.runtime.state !== "running" && transport.activateLocalModel && (
                      <button
                        className="button button--ghost"
                        disabled={commandCleanupBlocked || connectionDisconnected || current.closing || Boolean(modelActionAlias) || currentModel.runtime.state === "starting"}
                        onClick={() => void activateModel(currentModel.record.alias, "session")}
                        type="button"
                      >
                        {modelActionAlias === currentModel.record.alias && modelActionKind === "start" ? "Starting model…" : "Start session model"}
                      </button>
                    )}
                    {!runtimeCoordinatorAvailable && currentModel?.runtime.state === "running" && transport.deactivateLocalModel && (
                      <button
                        className="button button--ghost"
                        disabled={connectionDisconnected || Boolean(modelActionAlias) || current.running || responseStopping}
                        onClick={() => void deactivateModel(currentModel.record.alias, "session")}
                        title={current.running ? "Stop the active response first" : "Stop this shared local runtime; sessions stay open"}
                        type="button"
                      >
                        {modelActionAlias === currentModel.record.alias && modelActionKind === "stop" ? "Stopping model…" : "Stop model"}
                      </button>
                    )}
                    {(modelCatalogState === "error" || currentModel?.runtime.state === "starting") && transport.getLocalModels && (
                      <button
                        className="button button--ghost"
                        disabled={modelRefreshBusy || Boolean(modelActionAlias)}
                        onClick={() => void refreshModelStatus("session")}
                        type="button"
                      >
                        {modelRefreshBusy ? "Refreshing…" : "Refresh model status"}
                      </button>
                    )}
                    {inlineRuntimeRecoveryAvailable && modelCatalogState === "ready" && (currentModel === null || currentModel.runtime.state !== "running") && (
                      <button
                        aria-controls="agent-runtime-controls"
                        className="button button--ghost"
                        disabled={commandCleanupBlocked || connectionDisconnected || current.closing || runtimeControlBusy}
                        onClick={focusRuntimeControls}
                        type="button"
                      >Choose or start model</button>
                    )}
                    {!inlineRuntimeRecoveryAvailable && modelCatalogState === "ready" && currentModel === null && (
                      <a className="button button--ghost" href="/models">Open Models</a>
                    )}
                  </>
                )}
                runtimeFeedback={(
                  <>
                    {modelFeedbackTarget === "session" && modelError && <p className="agent__error" role="alert">{modelError}</p>}
                    {modelFeedbackTarget === "session" && modelNotice && <p className="agent__notice" role="status">{modelNotice}</p>}
                  </>
                )}
                runtimeNote={!runtimeCoordinatorAvailable && current.running && currentModel?.runtime.state === "running" && transport.deactivateLocalModel
                  ? <span className="agent__action-note">Stop the active response before stopping its model.</span>
                  : null}
                runtimeState={sessionModelState}
                runtimeStatus={sessionModelStatus}
                showRuntimeNotice={sessionModelNoticeVisible}
                turnCount={current.turns}
              />
              </div>
              <div className="agent__conversation-stage">
              <p className="sr-only" aria-live="polite">
                {pending
                  ? `Approval needed for ${pending.mcp_tool ? mcpToolLabel(pending.mcp_tool) : TOOL_LABELS[pending.tool ?? ""] ?? pending.tool ?? "an agent action"}.`
                  : responseStopping ? "Stopping the active response." : liveStreams.size > 0 ? "Agent response is streaming." : current.running ? "Agent is working." : ""}
              </p>
              <div
                className="agent__log"
                ref={logRef}
                role="log"
                aria-live="off"
                onScroll={(event) => {
                  const node = event.currentTarget;
                  const nextFollowingOutput = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
                  followOutput.current = nextFollowingOutput;
                  setFollowingOutput(nextFollowingOutput);
                }}
                tabIndex={-1}
              >
                <header className="agent__log-head">
                  <span>
                    <small>Conversation</small>
                    <strong>Messages and agent activity</strong>
                  </span>
                  <span className="agent__activity-badge" data-tone={activityState.tone}>{activityState.label}</span>
                </header>
                <div aria-label="Agent activity" className="agent__timeline" role="region">
                  <AgentSessionEffects
                    events={events}
                    fileActionsDisabled={current.closing || connectionDisconnected}
                    historyGap={historyGap}
                    onOpenFile={openReceiptFile}
                    running={current.running}
                    scopeKey={current.session_id}
                    turnCount={current.turns}
                  />
                  {historyGap && <p className="agent__status" role="status">Earlier in-memory events expired; completed replies below remain authoritative.</p>}
                  <TranscriptEventRows
                    key={current.session_id}
                    events={events}
                    fileActionsDisabled={current.closing || connectionDisconnected}
                    focusTurnRequest={artifactTurnFocus}
                    liveStreams={liveStreams}
                    onOpenFile={openReceiptFile}
                    onReviseTurn={turnRevisionSupported
                      ? (turnId, mode) => { void reviseTurn(turnId, mode); }
                      : undefined}
                    reasoningEnabled={reasoningEnabled}
                    revisionActionsDisabled={liveTurnRevisionDisabled}
                    stopping={current.stopping || responseStopping}
                    turnRevisionBusy={turnRevisionBusy}
                  />
                  {artifactViewerTransport !== null
                    && artifactProjectId !== null
                    && artifactSessionId === current.session_id
                    && (artifactsLoading || artifactsError !== "" || artifactItems.length > 0 || (artifactCounts?.total ?? 0) > 0 || current.turns > 0)
                    && (
                      <AgentArtifactsPanel
                        artifacts={artifactItems}
                        canLoadMore={artifactNextOffset !== null}
                        counts={artifactCounts}
                        error={artifactsError}
                        loading={artifactsLoading}
                        onCaptureCurrent={addChangeArtifact}
                        onLoadMore={() => { void loadMoreArtifacts(); }}
                        onOpenFile={openReceiptFile}
                        onOpenSourceTurn={openArtifactSourceTurn}
                        onViewerReady={() => setArtifactViewRevision((value) => value + 1)}
                        onRevealFile={revealArtifactFile}
                        onRefresh={() => setArtifactsRefreshKey((value) => value + 1)}
                        onReviewChanges={reviewArtifactChanges}
                        onViewChange={setArtifactView}
                        openRequest={artifactOpenRequest}
                        pageError={artifactPageError}
                        pageLoading={artifactPageLoading}
                        projectId={artifactProjectId}
                        sessionId={artifactSessionId}
                        transport={artifactViewerTransport}
                        userPresenceAvailable={userPresenceAvailable}
                        view={artifactView}
                      />
                    )}
                  {current.turns === 0 && !current.closing && !current.running && !pending && !events.some((event) => event.kind === "user" || event.kind === "assistant" || event.kind === "assistant_delta") && (
                    <p className="agent__status">
                      {currentModelAlias === null
                        ? inlineRuntimeRecoveryAvailable
                          ? "Session created. Choose, start, or bind its model in Model & context to continue."
                          : "Session created without a model. Open Models to install one, then choose it in Model & context."
                        : modelCatalogState === "loading"
                        ? "Session created. Checking the model before your first message…"
                        : currentModelBlocked
                          ? inlineRuntimeRecoveryAvailable
                            ? "Session created. Choose, start, or bind its model in Model & context to continue."
                            : currentModel === null
                              ? "Session created. Open Models and start a local model to continue."
                              : "Session created. Start the session model above to continue."
                          : reasoningEnabled
                            ? "Session ready. Reasoning will appear here when the model exposes it. Write your first request below."
                            : "Session ready. Write your first request below. Reasoning is off for this session."}
                    </p>
                  )}
                  {current.running && !pending && liveStreams.size === 0 && <p className="agent__thinking">{responseStopping ? "Stopping… waiting for the active operation to end" : activeExternalProposal ? "Applying the reviewed external file proposal…" : "Working… waiting for model activity"}</p>}
                </div>
                {!followingOutput && (
                  <button
                    className="button button--ghost agent__jump-latest"
                    onClick={() => {
                      const node = logRef.current;
                      if (!node) return;
                      followOutput.current = true;
                      setFollowingOutput(true);
                      node.scrollTop = node.scrollHeight;
                      node.focus({ preventScroll: true });
                    }}
                    type="button"
                  >
                    Jump to latest activity
                  </button>
                )}
              </div>
              {streamNotice && (
                <div className="agent__status">
                  <span role="status">{streamNotice}</span>{" "}
                  {isLiveUpdateNotice(streamNotice) && (
                    <button
                      className="button button--ghost"
                      onClick={() => {
                        setStreamNotice("");
                        setStreamRetryNonce((value) => value + 1);
                      }}
                      type="button"
                    >
                      Retry live updates
                    </button>
                  )}
                </div>
              )}
              {pending && (
                <div
                  aria-label="Approval needed"
                  aria-modal="true"
                  className="agent__approval"
                  ref={approvalRef}
                  role="alertdialog"
                  tabIndex={-1}
                >
                  {pending.mcp_tool ? (
                    <div className="agent-mcp-approval-review">
                      <p className="agent-mcp-approval-review__identity">
                        <strong>{mcpToolLabel(pending.mcp_tool)}</strong>
                        <span>from</span>
                        <strong>{mcpServerLabel(pending.mcp_tool)}</strong>
                      </p>
                      <p className="agent-mcp-approval-review__policy">
                        This permits one external project-tool invocation. The decision is never remembered, and external effects cannot be verified automatically.
                      </p>
                      {pending.preview && (
                        <div className="agent-mcp-approval-review__preview">
                          <span>Redacted call review</span>
                          <pre aria-label="Redacted MCP call preview" className="agent__diff">{pending.preview}</pre>
                        </div>
                      )}
                    </div>
                  ) : (
                    <>
                      <p className="agent__approval-title">
                        <strong>{isExternalWriteTransactionProposal(pending) ? "External controller change set" : isExternalWriteProposal(pending) ? "External controller proposal" : TOOL_LABELS[pending.tool ?? ""] ?? pending.tool}</strong> wants to {approvalAction(pending.tool)}: <code>{summarizeArguments(pending.tool, pending.arguments as Record<string, unknown> | null)}</code>
                      </p>
                      {pending.preview && (pending.tool === "write_file"
                        ? <AgentDiffViewer diff={pending.preview} label="Pending reviewed file diff" />
                        : <pre className="agent__diff">{pending.preview}</pre>)}
                    </>
                  )}
                  {!userPresenceAvailable && <p className="agent__note">This pending action cannot be decided until the app is opened in a native-confirmation composition.</p>}
                  <div className="agent__approval-actions">
                    <button className="button button--primary" disabled={!userPresenceAvailable} onClick={() => void decide(true)} type="button">{pending.mcp_tool ? "Approve one call" : "Approve"}</button>
                    <button className="button button--ghost" disabled={!userPresenceAvailable} onClick={() => void decide(false)} type="button">{pending.mcp_tool ? "Deny call" : "Deny"}</button>
                  </div>
                </div>
              )}
              </div>
              <form aria-label="Message composer" className="agent__compose" onSubmit={(event) => { event.preventDefault(); void send(); }}>
                <div className="agent__compose-head">
                  <label className="agent__compose-label" htmlFor="agent-message">Message to the agent</label>
                  <small id="agent-composer-shortcut">
                    {current.running || responseStopping
                      ? "Write the next message now · Send unlocks when this response ends"
                      : "Ctrl/⌘+Enter sends · Enter adds a line"}
                  </small>
                </div>
                <textarea
                  aria-describedby={`agent-session-model-status agent-composer-shortcut${conversationMessage ? " agent-message-error" : ""}`}
                  disabled={!commandCleanupBlocked && (current.closing || current.history_write_failed)}
                  readOnly={commandCleanupBlocked}
                  id="agent-message"
                  onChange={(e) => { if (!commandCleanupBlocked) changeDraft(e.currentTarget.value); }}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send(); } }}
                  placeholder={commandCleanupBlocked ? "Agent paused for command cleanup; your draft is kept here" : current.history_write_failed
                    ? "Local history is unavailable; open a new chat after checking storage"
                    : current.closing
                    ? "This session is closing. Open a new session to chat."
                    : responseStopping
                      ? "Keep writing the next message while this response stops…"
                    : current.running
                    ? "Write the next message while the agent responds…"
                    : connectionDisconnected
                      ? "The local app is disconnected; reopen it before writing a message"
                      : currentModelAction !== null
                        ? "Wait for the model change to finish; your draft is kept here"
                      : runtimeControlBusy
                        ? "Switching the shared model; your draft is kept here"
                      : currentModelBlocked
                      ? inlineRuntimeRecoveryAvailable
                        ? "Choose or start a model in Model & context to write a message"
                        : currentModel === null
                          ? "Open Models and start a local model to write a message"
                          : "Start the session model to write a message"
                      : "What should the agent do? Ctrl+Enter sends"}
                  ref={composerInputRef}
                  rows={3}
                  value={draft}
                />
                <AgentComposerAttachments
                  attachments={draftAttachments}
                  capabilities={mediaCapabilities}
                  compact
                  disabled={commandCleanupBlocked || connectionDisconnected || current.closing || current.running || current.history_write_failed || responseStopping || runtimeControlBusy || currentModelAction !== null}
                  modelAlias={currentModelAlias}
                  onAttachmentsChange={changeDraftAttachments}
                  onBusyChange={setAttachmentBusy}
                  runtimeKey={mediaRuntimeKey}
                  sessionId={current.session_id}
                  transport={transport}
                />
                <div className="agent__compose-footer">
                  <AgentRuntimeControl
                    current={current}
                    disabled={commandCleanupBlocked || connectionDisconnected || current.closing}
                    focusRequestKey={runtimeFocusRequest}
                    liveSessions={sessions}
                    models={models}
                    onBusyChange={setRuntimeControlBusy}
                    onModelSelected={noteRuntimeModelSelection}
                    onModelsRefresh={refreshModels}
                    onRuntimeStatus={setRuntimeCoordinator}
                    onSessionUpdated={acceptRuntimeSessionUpdate}
                    transport={transport}
                    variant="composer"
                  />
                  <div className="agent__compose-actions">
                  {transport.checkPrompt && (
                    <button
                      aria-expanded={Boolean(promptCheckResult)}
                      aria-label="Review prompt without sending"
                      className="button button--ghost agent__compose-improve"
                      disabled={commandCleanupBlocked || busy || promptCheckBusy || current.closing || current.history_write_failed || current.running || responseStopping || currentModelAction !== null || runtimeControlBusy || !draft.trim()}
                      onClick={() => void runPromptCheck()}
                      title="Review this draft and suggest a clearer version. This does not send it to the agent."
                      type="button"
                    >
                      <Icon name="sparkles" />
                      <span className="agent__compose-improve-copy">
                        <strong>{promptCheckBusy ? "Reviewing…" : "Review prompt"}</strong>
                        <small>Optional · no agent send</small>
                      </span>
                    </button>
                  )}
                  {current.running || responseStopping ? (
                    <button aria-label={responseStopping ? "Stopping…" : "Stop response"} className="button button--danger-ghost agent__compose-primary-action" disabled={responseStopping} onClick={() => void stop()} title={responseStopping ? "Stopping the active response" : "Stop the active response"} type="button"><Icon name="stop" /><span className="sr-only agent__forced-color-label">{responseStopping ? "Stopping…" : "Stop response"}</span></button>
                  ) : (
                    <button aria-label="Send" className="button button--primary agent__compose-primary-action" disabled={busy || attachmentBusy || attachmentModelMismatch || promptCheckBusy || current.closing || current.history_write_failed || currentModelBlocked || (!draft.trim() && draftAttachments.length === 0)} title="Send message · Ctrl/Command+Enter" type="submit"><Icon name="send" /><span className="sr-only agent__forced-color-label">Send</span></button>
                  )}
                  </div>
                </div>
                <div aria-live="polite" className="agent__prompt-check-status">
                  {promptCheckError && <p className="agent__error" role="alert">{promptCheckError}</p>}
                  {promptCheckNotice && <p className="agent__status">{promptCheckNotice}</p>}
                </div>
                {promptCheckResult && <AgentPromptCheckResult onUseRewrite={usePromptRewrite} result={promptCheckResult} />}
                {conversationMessage && <p className="agent__error" id="agent-message-error" role="alert">{conversationMessage}</p>}
              </form>
            </>
          )}
          {!current && conversationMessage && <p className="agent__error" id="agent-message-error" role="alert">{conversationMessage}</p>}
          </section>
        </div>
      </div>
      <Dialog
        description={confirmationPrompt?.description}
        footer={(
          <>
            <button
              className="button button--ghost"
              onClick={() => finishConfirmation(false)}
              ref={keepConfirmationRef}
              type="button"
            >
              Keep current state
            </button>
            <button className="button button--danger-ghost" onClick={() => finishConfirmation(true)} type="button">
              {confirmationPrompt?.confirmLabel ?? "Continue"}
            </button>
          </>
        )}
        initialFocusRef={keepConfirmationRef}
        onClose={() => finishConfirmation(false)}
        open={confirmationPrompt !== null}
        title={confirmationPrompt?.title ?? "Confirm action"}
        tone="danger"
      >
        <p>{confirmationPrompt?.detail}</p>
      </Dialog>
    </section>
  );
}
