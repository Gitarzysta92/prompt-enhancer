import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type {
  AgentCatalogSession,
  AgentProject,
  AgentSessionView,
  PromptEnhancerTransport,
  UpdateAgentCatalogSession,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { BoundedListPager, useBoundedListPage } from "../../shared/ui/BoundedListPager";
import { connectAgentCatalogSync, type AgentCatalogSync } from "./agentWindowChannel";
import {
  AgentMessageSearchDialog,
  type AgentSavedMessageSearch,
  type AgentSavedMessageSearchHit,
} from "./AgentMessageSearchDialog";
import "./AgentCatalogRail.css";

const CATALOG_RENDER_PAGE = 40;
const CATALOG_SERVER_PAGE = 100;

type CoreCatalogTransport = Pick<
  PromptEnhancerTransport,
  | "listAgentProjects"
  | "createAgentProject"
  | "updateAgentProject"
  | "deleteAgentProject"
  | "listAgentCatalogSessions"
  | "updateAgentCatalogSession"
  | "deleteAgentCatalogSession"
>;

type CatalogTransport = CoreCatalogTransport & Partial<Pick<
  PromptEnhancerTransport,
  | "pageAgentProjects"
  | "pageAgentCatalogSessions"
  | "getAgentProject"
  | "getAgentCatalogSession"
  | "searchAgentSavedMessages"
>>;

interface CatalogPageCoverage {
  snapshot: string | null;
  nextOffset: number | null;
  total: number;
  complete: boolean;
}

type CatalogDialog =
  | { kind: "create-project" }
  | { kind: "rename-project"; project: AgentProject }
  | { kind: "delete-project"; project: AgentProject }
  | { kind: "rename-session"; session: AgentCatalogSession }
  | { kind: "move-session"; session: AgentCatalogSession }
  | { kind: "fork-session"; session: AgentCatalogSession }
  | { kind: "delete-session"; session: AgentCatalogSession };

type CatalogActionMenu =
  | { kind: "project"; project: AgentProject }
  | { kind: "session"; session: AgentCatalogSession };

const MODAL_FOCUSABLE = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function trapModalFocus(event: ReactKeyboardEvent<HTMLElement>): void {
  if (event.key !== "Tab") return;
  const eventTarget = event.target instanceof HTMLElement ? event.target : null;
  const container = event.currentTarget.matches("[role='dialog']")
    ? event.currentTarget
    : eventTarget?.closest<HTMLElement>("[role='dialog']") ?? event.currentTarget;
  // Filtering a DOM-ordered wildcard query avoids selector-list ordering differences
  // between browsers and jsdom while preserving the user's actual tab sequence.
  const focusable = [...container.querySelectorAll<HTMLElement>("*")]
    .filter((element) => element.matches(MODAL_FOCUSABLE));
  if (focusable.length === 0) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  // The dialog container itself is focusable but outside the tab sequence, so it
  // wraps like an edge instead of letting Shift+Tab escape the modal.
  const inSequence = active instanceof HTMLElement && focusable.includes(active);
  if (event.shiftKey && (!inSequence || active === first)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (!inSequence || active === last)) {
    event.preventDefault();
    first.focus();
  }
}

export interface AgentCatalogRailProps {
  transport: Partial<CatalogTransport>;
  liveSessions: AgentSessionView[] | null;
  currentSessionId?: string;
  closeFailureSessionIds?: ReadonlySet<string>;
  draftSessionIds?: ReadonlySet<string>;
  selectedProjectId: string | null;
  collapsed?: boolean;
  disabled?: boolean;
  newChatDisabled?: boolean;
  refreshKey?: number;
  onProjectChange: (projectId: string | null) => void;
  onToggleCollapsed?: () => void;
  onNewChat: (projectId: string | null, trigger: HTMLButtonElement) => void;
  onOpenLiveSession: (session: AgentSessionView) => void;
  onOpenUnavailableSession: (session: AgentCatalogSession) => void;
  onOpenSavedMessage?: (
    match: AgentSavedMessageSearchHit,
    session: AgentCatalogSession,
    signal: AbortSignal,
  ) => Promise<boolean>;
  onCloseLiveSession: (session: AgentSessionView) => void;
  onSessionDeleted?: (sessionId: string) => void;
  onSessionUpdated?: (session: AgentCatalogSession) => void;
  onForkSession?: (
    session: AgentCatalogSession,
    title: string,
    signal?: AbortSignal,
  ) => Promise<void>;
  onInitialCatalogLoad?: (session: AgentCatalogSession | null) => void;
}

function catalogAvailable(transport: Partial<CatalogTransport>): transport is CatalogTransport {
  return typeof transport.listAgentProjects === "function"
    && typeof transport.createAgentProject === "function"
    && typeof transport.updateAgentProject === "function"
    && typeof transport.deleteAgentProject === "function"
    && typeof transport.listAgentCatalogSessions === "function"
    && typeof transport.updateAgentCatalogSession === "function"
    && typeof transport.deleteAgentCatalogSession === "function";
}

function pagingFailureCopy(error: unknown, noun: "projects" | "chats"): string {
  if (error instanceof TransportError && (
    error.reasonCode === "agent_catalog_page_snapshot_conflict"
    || error.reasonCode === "agent_catalog_page_out_of_range"
  )) {
    return `The ${noun} changed while another page was loading. Reload from the first page.`;
  }
  return `More ${noun} could not be loaded. The records already shown are unchanged.`;
}

function failureCopy(error: unknown): string {
  if (!(error instanceof TransportError)) return "The Agent catalog could not be updated.";
  switch (error.reasonCode) {
    case "agent_project_revision_conflict":
    case "agent_catalog_session_revision_conflict":
    case "agent_history_revision_conflict":
      return "This item changed in another window. It has been refreshed; retry your action.";
    case "agent_project_not_empty":
      return "Move, archive, or delete this project's chats before deleting the project.";
    case "agent_default_project_protected":
      return "The Personal workspace project cannot be archived or deleted.";
    case "agent_catalog_session_live":
      return "Close the live chat before deleting its saved navigation entry.";
    case "agent_session_fork_point_invalid":
      return "The selected branch point is no longer a completed turn. Refresh and retry.";
    case "agent_session_fork_request_conflict":
      return "This branch request no longer matches its original input. Refresh and retry.";
    case "agent_session_fork_conflict":
      return "Another branch operation changed this chat. Refresh and retry.";
    case "agent_project_archived":
      return "Restore the destination project before creating a branch.";
    case "agent_catalog_storage_unavailable":
    case "agent_catalog_unavailable":
      return "The private Agent catalog is unavailable. Live chats remain separate.";
    case "agent_catalog_migration_history_incomplete":
    case "agent_catalog_migration_checksum_mismatch":
    case "agent_catalog_schema_version_mismatch":
      return "The private Agent catalog migration history is inconsistent. No data was changed.";
    default:
      return "The Agent catalog could not be updated.";
  }
}

function sessionStatus(
  session: AgentCatalogSession,
  live: AgentSessionView | undefined,
  hasDraft = false,
): string {
  const status = live?.cleanup_unconfirmed
    ? "cleanup unconfirmed"
    : live?.closing
      ? "closing"
      : live?.pending_approval_id
        ? "waiting for approval"
        : live?.running
          ? "working"
          : live
            ? `${live.turns} ${live.turns === 1 ? "turn" : "turns"} · live${live.settings.retention_policy === "local_history" ? " · saved" : " · metadata only"}`
            : session.retention_policy === "local_history"
              ? `${session.turn_count} ${session.turn_count === 1 ? "turn" : "turns"} · saved locally`
              : "Metadata only · history unavailable";
  return hasDraft ? `${status} · draft in this window` : status;
}

function liveSessionTitle(session: AgentSessionView): string {
  return session.settings.title
    || session.settings.workspace.split(/[\\/]/).filter(Boolean).pop()
    || "Untitled chat";
}

function branchTitle(title: string): string {
  const suffix = " (branch)";
  return `${title.slice(0, 120 - suffix.length).trimEnd()}${suffix}`;
}

export function AgentCatalogRail({
  transport,
  liveSessions,
  currentSessionId,
  closeFailureSessionIds,
  draftSessionIds,
  selectedProjectId,
  collapsed = false,
  disabled = false,
  newChatDisabled = disabled,
  refreshKey = 0,
  onProjectChange,
  onToggleCollapsed,
  onNewChat,
  onOpenLiveSession,
  onOpenUnavailableSession,
  onOpenSavedMessage,
  onCloseLiveSession,
  onSessionDeleted,
  onSessionUpdated,
  onForkSession,
  onInitialCatalogLoad,
}: AgentCatalogRailProps) {
  const supported = catalogAvailable(transport);
  const [projects, setProjects] = useState<AgentProject[] | null>(supported ? null : []);
  const [catalogSessions, setCatalogSessions] = useState<AgentCatalogSession[] | null>(
    supported ? null : [],
  );
  const [selectedProjectExtra, setSelectedProjectExtra] = useState<AgentProject | null>(null);
  const [selectedSessionExtra, setSelectedSessionExtra] = useState<AgentCatalogSession | null>(null);
  const [projectCoverage, setProjectCoverage] = useState<CatalogPageCoverage | null>(null);
  const [sessionCoverage, setSessionCoverage] = useState<CatalogPageCoverage | null>(null);
  const [projectPageBusy, setProjectPageBusy] = useState(false);
  const [sessionPageBusy, setSessionPageBusy] = useState(false);
  const [projectPageError, setProjectPageError] = useState("");
  const [sessionPageError, setSessionPageError] = useState("");
  const [selectedProjectError, setSelectedProjectError] = useState("");
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [dialog, setDialog] = useState<CatalogDialog | null>(null);
  const [actionMenu, setActionMenu] = useState<CatalogActionMenu | null>(null);
  const [dialogValue, setDialogValue] = useState("");
  const [moveDestinations, setMoveDestinations] = useState<AgentProject[] | null>(null);
  const [moveDestinationError, setMoveDestinationError] = useState("");
  const [moveDestinationNonce, setMoveDestinationNonce] = useState(0);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [messageSearchOpen, setMessageSearchOpen] = useState(false);
  const actionMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogTriggerRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLFormElement | null>(null);
  const newChatRef = useRef<HTMLButtonElement | null>(null);
  const catalogSyncRef = useRef<AgentCatalogSync | null>(null);
  const selectedProjectSnapshotRef = useRef<AgentProject | null>(null);
  const initialCatalogReported = useRef(false);
  const mutationOwnerRef = useRef(0);
  const mutationRef = useRef<{
    controller: AbortController;
    key: string;
    owner: number;
  } | null>(null);
  const projectReadOwnerRef = useRef(0);
  const sessionReadOwnerRef = useRef(0);
  const projectPageControllerRef = useRef<AbortController | null>(null);
  const sessionPageControllerRef = useRef<AbortController | null>(null);
  const messageOpenControllerRef = useRef<AbortController | null>(null);
  const messageOpenOwnerRef = useRef(0);
  const messageSearchTriggerRef = useRef<HTMLButtonElement | null>(null);
  const projectServerIdsRef = useRef(new Set<string>());
  const sessionServerIdsRef = useRef(new Set<string>());

  const liveById = useMemo(
    () => new Map((liveSessions ?? []).map((session) => [session.session_id, session])),
    [liveSessions],
  );
  const normalizedSearch = search.trim();
  const savedMessageSearch: AgentSavedMessageSearch | undefined = transport.searchAgentSavedMessages;
  const projectItems = useMemo(() => {
    const loaded = projects ?? [];
    if (
      selectedProjectExtra === null
      || loaded.some((project) => project.project_id === selectedProjectExtra.project_id)
    ) return loaded;
    return [...loaded, selectedProjectExtra];
  }, [projects, selectedProjectExtra]);
  const projectNameById = useMemo(
    () => new Map(projectItems.map((project) => [project.project_id, project.name])),
    [projectItems],
  );
  const selectedProjectIndex = selectedProjectId === null
    ? null
    : projectItems.findIndex((project) => project.project_id === selectedProjectId);
  const projectPage = useBoundedListPage({
    itemCount: projectItems.length,
    pageSize: CATALOG_RENDER_PAGE,
    preferredIndex: selectedProjectIndex !== null && selectedProjectIndex >= 0 ? selectedProjectIndex : null,
    resetKey: `${normalizedSearch}:${String(includeArchived)}:${refreshKey}:${refreshNonce}:projects`,
  });
  const sessionItems = useMemo(() => {
    const loaded = catalogSessions ?? [];
    if (
      selectedSessionExtra === null
      || loaded.some((session) => session.session_id === selectedSessionExtra.session_id)
    ) return loaded;
    return [...loaded, selectedSessionExtra];
  }, [catalogSessions, selectedSessionExtra]);
  const selectedSessionIndex = currentSessionId === undefined
    ? null
    : sessionItems.findIndex((session) => session.session_id === currentSessionId);
  const sessionPage = useBoundedListPage({
    itemCount: sessionItems.length,
    pageSize: CATALOG_RENDER_PAGE,
    preferredIndex: selectedSessionIndex !== null && selectedSessionIndex >= 0 ? selectedSessionIndex : null,
    resetKey: `${selectedProjectId ?? "all"}:${normalizedSearch}:${String(includeArchived)}:${refreshKey}:${refreshNonce}:sessions`,
  });

  const refresh = useCallback(() => setRefreshNonce((value) => value + 1), []);

  useEffect(() => {
    if (!supported) return;
    const sync = connectAgentCatalogSync(refresh);
    catalogSyncRef.current = sync;
    return () => {
      if (catalogSyncRef.current === sync) catalogSyncRef.current = null;
      sync.close();
    };
  }, [refresh, supported]);

  useEffect(() => {
    initialCatalogReported.current = false;
    selectedProjectSnapshotRef.current = null;
    projectReadOwnerRef.current += 1;
    sessionReadOwnerRef.current += 1;
    projectPageControllerRef.current?.abort();
    sessionPageControllerRef.current?.abort();
    projectPageControllerRef.current = null;
    sessionPageControllerRef.current = null;
    projectServerIdsRef.current = new Set();
    sessionServerIdsRef.current = new Set();
    setSelectedProjectExtra(null);
    setSelectedSessionExtra(null);
    setProjectCoverage(null);
    setSessionCoverage(null);
    setProjectPageBusy(false);
    setSessionPageBusy(false);
    setProjectPageError("");
    setSessionPageError("");
    setSelectedProjectError("");
    mutationOwnerRef.current += 1;
    mutationRef.current?.controller.abort();
    mutationRef.current = null;
    setBusyKey("");
    setMoveDestinations(null);
    setMoveDestinationError("");
    messageOpenOwnerRef.current += 1;
    messageOpenControllerRef.current?.abort();
    messageOpenControllerRef.current = null;
    setMessageSearchOpen(false);
    return () => {
      projectReadOwnerRef.current += 1;
      sessionReadOwnerRef.current += 1;
      projectPageControllerRef.current?.abort();
      sessionPageControllerRef.current?.abort();
      mutationOwnerRef.current += 1;
      mutationRef.current?.controller.abort();
      mutationRef.current = null;
      messageOpenOwnerRef.current += 1;
      messageOpenControllerRef.current?.abort();
      messageOpenControllerRef.current = null;
    };
  }, [transport]);

  useEffect(() => {
    if (!supported || dialog?.kind !== "move-session") return;
    const controller = new AbortController();
    setMoveDestinations(null);
    setMoveDestinationError("");
    transport.listAgentProjects({
      includeArchived: false,
      limit: 200,
    }, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      const destinations = result.projects.filter((project) => (
        project.project_id !== dialog.session.project_id && !project.archived_at
      ));
      setMoveDestinations(destinations);
      setDialogValue((current) => (
        destinations.some((project) => project.project_id === current)
          ? current
          : destinations[0]?.project_id ?? ""
      ));
    }).catch(() => {
      if (controller.signal.aborted) return;
      setMoveDestinations([]);
      setMoveDestinationError("Active projects could not be loaded. Retry this read before moving the chat.");
    });
    return () => controller.abort();
  }, [dialog, moveDestinationNonce, supported, transport]);

  useEffect(() => {
    if (!disabled) return;
    mutationOwnerRef.current += 1;
    mutationRef.current?.controller.abort();
    mutationRef.current = null;
    setBusyKey("");
    setActionMenu(null);
    setDialog(null);
  }, [disabled]);

  function closeActionMenu(restoreFocus = true): void {
    setActionMenu(null);
    if (restoreFocus) {
      window.setTimeout(() => actionMenuTriggerRef.current?.focus(), 0);
    }
  }

  function openActionMenu(
    next: CatalogActionMenu,
    trigger: HTMLButtonElement,
  ): void {
    actionMenuTriggerRef.current = trigger;
    setDialog(null);
    setActionMenu(next);
  }

  useEffect(() => {
    if (actionMenu === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeActionMenu();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [actionMenu]);

  const catalogModalOpen = actionMenu !== null || dialog !== null;
  useEffect(() => {
    if (!catalogModalOpen) return undefined;
    const bodyOverflow = document.body.style.overflow;
    const documentOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = documentOverflow;
    };
  }, [catalogModalOpen]);

  useEffect(() => {
    if (!supported) return;
    const owner = projectReadOwnerRef.current + 1;
    projectReadOwnerRef.current = owner;
    const controller = new AbortController();
    projectPageControllerRef.current?.abort();
    projectPageControllerRef.current = null;
    projectServerIdsRef.current = new Set();
    setProjects(null);
    setSelectedProjectExtra(null);
    setProjectCoverage(null);
    setProjectPageBusy(false);
    setProjectPageError("");
    setSelectedProjectError("");
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const query = {
            search: normalizedSearch || undefined,
            includeArchived,
          };
          const pageProjects = transport.pageAgentProjects;
          let paged = false;
          let firstProjects: AgentProject[];
          let initialComplete = true;
          let nextCoverage: CatalogPageCoverage;
          if (typeof pageProjects === "function") {
            const result = await pageProjects({
                ...query,
                limit: CATALOG_SERVER_PAGE,
                offset: 0,
              }, controller.signal);
            paged = true;
            firstProjects = result.projects;
            initialComplete = result.complete;
            nextCoverage = {
              snapshot: result.snapshot,
              nextOffset: result.next_offset ?? null,
              total: result.total,
              complete: result.complete,
            };
          } else {
            const result = await transport.listAgentProjects({
                ...query,
                limit: 200,
              }, controller.signal);
            firstProjects = result.projects;
            nextCoverage = {
              snapshot: null,
              nextOffset: null,
              total: firstProjects.length,
              complete: true,
            };
          }
          if (controller.signal.aborted || projectReadOwnerRef.current !== owner) return;
          projectServerIdsRef.current = new Set(
            firstProjects.map((project) => project.project_id),
          );
          setProjects(firstProjects);
          setProjectCoverage(nextCoverage);
          setError("");
          const selectedProject = firstProjects.find(
            (project) => project.project_id === selectedProjectId,
          );
          if (selectedProject !== undefined) {
            selectedProjectSnapshotRef.current = selectedProject;
          } else if (
            selectedProjectId !== null
            && normalizedSearch === ""
            && typeof transport.getAgentProject === "function"
          ) {
            try {
              const selected = await transport.getAgentProject(
                selectedProjectId,
                controller.signal,
              );
              if (controller.signal.aborted || projectReadOwnerRef.current !== owner) return;
              if (includeArchived || selected.archived_at === null) {
                selectedProjectSnapshotRef.current = selected;
                setSelectedProjectExtra(selected);
              } else {
                const preferredProject = firstProjects.find((project) => (
                  project.archived_at === null && project.session_count > 0
                )) ?? firstProjects[0];
                onProjectChange(preferredProject?.project_id ?? null);
              }
            } catch (selectedCaught: unknown) {
              if (controller.signal.aborted || projectReadOwnerRef.current !== owner) return;
              // Only an authoritative absence retargets the rail. A transient read
              // failure keeps the user's selection instead of silently opening
              // another project's chats.
              const absent = selectedCaught instanceof TransportError
                && (selectedCaught.reasonCode === "agent_project_not_found"
                  || selectedCaught.status === 404);
              if (absent && (!paged || initialComplete)) {
                const preferredProject = firstProjects.find((project) => (
                  project.archived_at === null && project.session_count > 0
                )) ?? firstProjects[0];
                onProjectChange(preferredProject?.project_id ?? null);
              } else if (!absent) {
                setSelectedProjectError(
                  "The selected project could not be reloaded. It stays selected; retry this read.",
                );
              }
            }
          } else if (selectedProjectId === null && normalizedSearch === "") {
            const preferredProject = firstProjects.find((project) => (
              project.archived_at === null && project.session_count > 0
            )) ?? firstProjects[0];
            onProjectChange(preferredProject?.project_id ?? null);
          }
          if (
            firstProjects.length === 0
            && normalizedSearch === ""
            && !initialCatalogReported.current
          ) {
            initialCatalogReported.current = true;
            onInitialCatalogLoad?.(null);
          }
        } catch (caught: unknown) {
          if (controller.signal.aborted || projectReadOwnerRef.current !== owner) return;
          setProjects((previous) => previous ?? []);
          setProjectCoverage(null);
          setError(failureCopy(caught));
        }
      })();
    }, search.trim() ? 140 : 0);
    return () => {
      controller.abort();
      window.clearTimeout(handle);
    };
  }, [includeArchived, normalizedSearch, onInitialCatalogLoad, onProjectChange, refreshKey, refreshNonce, search, selectedProjectId, supported, transport]);

  useEffect(() => {
    const searchingAllProjects = normalizedSearch !== "";
    if (!supported || (selectedProjectId === null && !searchingAllProjects)) {
      sessionReadOwnerRef.current += 1;
      sessionPageControllerRef.current?.abort();
      sessionPageControllerRef.current = null;
      sessionServerIdsRef.current = new Set();
      setCatalogSessions([]);
      setSelectedSessionExtra(null);
      setSessionCoverage(null);
      setSessionPageBusy(false);
      setSessionPageError("");
      return;
    }
    const owner = sessionReadOwnerRef.current + 1;
    sessionReadOwnerRef.current = owner;
    const controller = new AbortController();
    sessionPageControllerRef.current?.abort();
    sessionPageControllerRef.current = null;
    sessionServerIdsRef.current = new Set();
    setCatalogSessions(null);
    setSelectedSessionExtra(null);
    setSessionCoverage(null);
    setSessionPageBusy(false);
    setSessionPageError("");
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const query = {
            projectId: searchingAllProjects ? undefined : selectedProjectId ?? undefined,
            search: normalizedSearch || undefined,
            includeArchived,
          };
          const pageSessions = transport.pageAgentCatalogSessions;
          let firstSessions: AgentCatalogSession[];
          let nextCoverage: CatalogPageCoverage;
          if (typeof pageSessions === "function") {
            const result = await pageSessions({
                ...query,
                limit: CATALOG_SERVER_PAGE,
                offset: 0,
              }, controller.signal);
            firstSessions = result.sessions;
            nextCoverage = {
              snapshot: result.snapshot,
              nextOffset: result.next_offset ?? null,
              total: result.total,
              complete: result.complete,
            };
          } else {
            const result = await transport.listAgentCatalogSessions({
                ...query,
                limit: 200,
              }, controller.signal);
            firstSessions = result.sessions;
            nextCoverage = {
              snapshot: null,
              nextOffset: null,
              total: firstSessions.length,
              complete: true,
            };
          }
          if (controller.signal.aborted || sessionReadOwnerRef.current !== owner) return;
          sessionServerIdsRef.current = new Set(
            firstSessions.map((session) => session.session_id),
          );
          setCatalogSessions(firstSessions);
          setSessionCoverage(nextCoverage);
          setError("");
          if (
            !initialCatalogReported.current
            && normalizedSearch === ""
            && !includeArchived
          ) {
            initialCatalogReported.current = true;
            onInitialCatalogLoad?.(firstSessions[0] ?? null);
          }
        } catch (caught: unknown) {
          if (controller.signal.aborted || sessionReadOwnerRef.current !== owner) return;
          setCatalogSessions((previous) => previous ?? []);
          setSessionCoverage(null);
          setError(failureCopy(caught));
        }
      })();
    }, search.trim() ? 140 : 0);
    return () => {
      controller.abort();
      window.clearTimeout(handle);
    };
  }, [includeArchived, normalizedSearch, onInitialCatalogLoad, refreshKey, refreshNonce, search, selectedProjectId, supported, transport]);

  useEffect(() => {
    if (
      !supported
      || currentSessionId === undefined
      || normalizedSearch !== ""
      || catalogSessions === null
      || catalogSessions.some((session) => session.session_id === currentSessionId)
      || typeof transport.getAgentCatalogSession !== "function"
    ) {
      if (catalogSessions !== null) setSelectedSessionExtra(null);
      return;
    }
    setSelectedSessionExtra(null);
    const owner = sessionReadOwnerRef.current;
    const controller = new AbortController();
    void (async () => {
      try {
        const selected = await transport.getAgentCatalogSession!(
          currentSessionId,
          controller.signal,
        );
        if (controller.signal.aborted || sessionReadOwnerRef.current !== owner) return;
        if (
          selected.project_id === selectedProjectId
          && (includeArchived || selected.archived_at === null)
        ) setSelectedSessionExtra(selected);
      } catch {
        // The loaded prefix remains truthful; a missing selected record is not invented.
      }
    })();
    return () => controller.abort();
  }, [
    catalogSessions,
    currentSessionId,
    includeArchived,
    normalizedSearch,
    selectedProjectId,
    supported,
    transport,
  ]);

  async function loadMoreProjects(): Promise<void> {
    if (
      typeof transport.pageAgentProjects !== "function"
      || projectCoverage === null
      || projectCoverage.nextOffset === null
      || projectCoverage.snapshot === null
      || projectPageBusy
    ) return;
    const owner = projectReadOwnerRef.current;
    const controller = new AbortController();
    projectPageControllerRef.current?.abort();
    projectPageControllerRef.current = controller;
    setProjectPageBusy(true);
    setProjectPageError("");
    try {
      const page = await transport.pageAgentProjects({
        search: normalizedSearch || undefined,
        includeArchived,
        limit: CATALOG_SERVER_PAGE,
        offset: projectCoverage.nextOffset,
        snapshot: projectCoverage.snapshot,
      }, controller.signal);
      if (controller.signal.aborted || projectReadOwnerRef.current !== owner) return;
      if (page.projects.some((project) => projectServerIdsRef.current.has(project.project_id))) {
        setProjectPageError("A repeated project page was refused. Reload from the first page.");
        return;
      }
      page.projects.forEach((project) => projectServerIdsRef.current.add(project.project_id));
      setProjects((previous) => [...(previous ?? []), ...page.projects]);
      setProjectCoverage({
        snapshot: page.snapshot,
        nextOffset: page.next_offset ?? null,
        total: page.total,
        complete: page.complete,
      });
    } catch (caught) {
      if (!controller.signal.aborted && projectReadOwnerRef.current === owner) {
        setProjectPageError(pagingFailureCopy(caught, "projects"));
      }
    } finally {
      if (projectPageControllerRef.current === controller) {
        projectPageControllerRef.current = null;
        setProjectPageBusy(false);
      }
    }
  }

  async function loadMoreSessions(): Promise<void> {
    if (
      typeof transport.pageAgentCatalogSessions !== "function"
      || sessionCoverage === null
      || sessionCoverage.nextOffset === null
      || sessionCoverage.snapshot === null
      || sessionPageBusy
    ) return;
    const owner = sessionReadOwnerRef.current;
    const controller = new AbortController();
    sessionPageControllerRef.current?.abort();
    sessionPageControllerRef.current = controller;
    setSessionPageBusy(true);
    setSessionPageError("");
    try {
      const page = await transport.pageAgentCatalogSessions({
        projectId: normalizedSearch ? undefined : selectedProjectId ?? undefined,
        search: normalizedSearch || undefined,
        includeArchived,
        limit: CATALOG_SERVER_PAGE,
        offset: sessionCoverage.nextOffset,
        snapshot: sessionCoverage.snapshot,
      }, controller.signal);
      if (controller.signal.aborted || sessionReadOwnerRef.current !== owner) return;
      if (page.sessions.some((session) => sessionServerIdsRef.current.has(session.session_id))) {
        setSessionPageError("A repeated chat page was refused. Reload from the first page.");
        return;
      }
      page.sessions.forEach((session) => sessionServerIdsRef.current.add(session.session_id));
      setCatalogSessions((previous) => [...(previous ?? []), ...page.sessions]);
      setSessionCoverage({
        snapshot: page.snapshot,
        nextOffset: page.next_offset ?? null,
        total: page.total,
        complete: page.complete,
      });
    } catch (caught) {
      if (!controller.signal.aborted && sessionReadOwnerRef.current === owner) {
        setSessionPageError(pagingFailureCopy(caught, "chats"));
      }
    } finally {
      if (sessionPageControllerRef.current === controller) {
        sessionPageControllerRef.current = null;
        setSessionPageBusy(false);
      }
    }
  }

  function openCatalogSession(
    session: AgentCatalogSession,
    live: AgentSessionView | undefined,
  ): void {
    if (session.project_id !== selectedProjectId) {
      onProjectChange(session.project_id);
    }
    if (live !== undefined) onOpenLiveSession(live);
    else onOpenUnavailableSession(session);
  }

  const closeMessageSearch = useCallback(() => {
    messageOpenOwnerRef.current += 1;
    messageOpenControllerRef.current?.abort();
    messageOpenControllerRef.current = null;
    setMessageSearchOpen(false);
    window.setTimeout(() => messageSearchTriggerRef.current?.focus(), 0);
  }, []);

  async function openSavedMessage(match: AgentSavedMessageSearchHit, signal: AbortSignal): Promise<boolean> {
    if (
      onOpenSavedMessage === undefined
      || typeof transport.getAgentCatalogSession !== "function"
    ) throw new Error("saved-message navigation is unavailable");
    messageOpenControllerRef.current?.abort();
    const controller = new AbortController();
    messageOpenControllerRef.current = controller;
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    const owner = messageOpenOwnerRef.current + 1;
    messageOpenOwnerRef.current = owner;
    try {
      const session = await transport.getAgentCatalogSession(match.session_id, controller.signal);
      if (controller.signal.aborted || messageOpenOwnerRef.current !== owner) return false;
      if (
        session.session_id !== match.session_id
        || session.project_id !== match.project_id
        || session.retention_policy !== "local_history"
        || session.history_revision !== match.history_revision
        || match.match_event_seq > session.last_event_seq
      ) throw new Error("saved message changed");
      const opened = await onOpenSavedMessage(match, session, controller.signal);
      return !controller.signal.aborted && messageOpenOwnerRef.current === owner && opened;
    } finally {
      signal.removeEventListener("abort", abort);
    }
  }

  // A row trigger is replaced when the catalog reloads after a mutation, so only a
  // control outside the reloading lists can still own focus afterwards.
  function stableFocusOrigin(origin: HTMLElement | null): HTMLElement | null {
    if (origin === null || !origin.isConnected) return null;
    return origin.closest(".agent-rail__project-list, .agent-rail__chat-section") === null
      ? origin
      : null;
  }

  function restoreCatalogFocus(origin: HTMLElement | null): void {
    // A settled mutation closes its menu and may remove the row that owned focus.
    // Focus is re-homed only when it was actually lost, so a focus the user moved
    // during the request is never stolen back.
    window.setTimeout(() => {
      const active = document.activeElement;
      if (active !== null && active !== document.body && active.isConnected) return;
      const openDialogElement = dialogRef.current;
      if (openDialogElement !== null && openDialogElement.isConnected) {
        openDialogElement.focus();
        return;
      }
      if (origin !== null && origin.isConnected) {
        origin.focus();
        return;
      }
      newChatRef.current?.focus();
    }, 0);
  }

  async function mutate(
    key: string,
    operation: (signal: AbortSignal) => Promise<unknown>,
  ): Promise<boolean> {
    if (disabled || !supported || mutationRef.current !== null) return false;
    const focusOrigin = stableFocusOrigin(
      dialog === null ? actionMenuTriggerRef.current : dialogTriggerRef.current,
    );
    const controller = new AbortController();
    const owner = mutationOwnerRef.current + 1;
    mutationOwnerRef.current = owner;
    mutationRef.current = { controller, key, owner };
    setActionMenu(null);
    setBusyKey(key);
    setError("");
    try {
      await operation(controller.signal);
      if (controller.signal.aborted || mutationRef.current?.owner !== owner) return false;
      catalogSyncRef.current?.notify();
      setDialog(null);
      setDialogValue("");
      refresh();
      return true;
    } catch (caught) {
      if (controller.signal.aborted || mutationRef.current?.owner !== owner) return false;
      setError(failureCopy(caught));
      refresh();
      return false;
    } finally {
      if (mutationRef.current?.owner === owner) {
        mutationRef.current = null;
        setBusyKey("");
        restoreCatalogFocus(focusOrigin);
      }
    }
  }

  async function updateCatalogSession(
    sessionId: string,
    command: UpdateAgentCatalogSession,
  ): Promise<boolean> {
    if (!supported) return false;
    const result: { session: AgentCatalogSession | null } = { session: null };
    const updated = await mutate(`session:${sessionId}`, async (signal) => {
      result.session = await transport.updateAgentCatalogSession(
        sessionId,
        command,
        signal,
      );
    });
    if (updated && result.session !== null) onSessionUpdated?.(result.session);
    return updated;
  }

  function openDialog(next: CatalogDialog, trigger?: HTMLElement): void {
    dialogTriggerRef.current = actionMenu === null
      ? trigger ?? document.activeElement as HTMLElement
      : actionMenuTriggerRef.current;
    setActionMenu(null);
    setDialog(next);
    setMoveDestinations(null);
    setMoveDestinationError("");
    setDialogValue(
      next.kind === "rename-project" ? next.project.name
        : next.kind === "rename-session" ? next.session.title
          : next.kind === "fork-session" ? branchTitle(next.session.title)
          : next.kind === "move-session" ? ""
          : "",
    );
  }

  function closeDialog(restoreFocus = true): void {
    setDialog(null);
    setDialogValue("");
    setMoveDestinations(null);
    setMoveDestinationError("");
    if (restoreFocus) {
      window.setTimeout(() => dialogTriggerRef.current?.focus(), 0);
    }
  }

  useEffect(() => {
    // Delete and unavailable-destination dialogs have no autofocused field. Focus
    // moves to the dialog itself rather than to a destructive default action.
    if (dialog === null) return;
    const container = dialogRef.current;
    if (container === null) return;
    const active = document.activeElement;
    if (active !== null && container.contains(active)) return;
    container.focus();
  }, [dialog]);

  useEffect(() => {
    if (dialog === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || mutationRef.current !== null) return;
      event.preventDefault();
      closeDialog();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dialog]);

  async function submitDialog(): Promise<void> {
    if (!supported || disabled || dialog === null) return;
    if (dialog.kind === "create-project") {
      const name = dialogValue.trim();
      if (!name) return;
      let createdProjectId: string | null = null;
      const created = await mutate("create-project", async (signal) => {
        const project = await transport.createAgentProject({ name }, signal);
        createdProjectId = project.project_id;
      });
      if (created && createdProjectId !== null) onProjectChange(createdProjectId);
      return;
    }
    if (dialog.kind === "rename-project") {
      const name = dialogValue.trim();
      if (!name) return;
      await mutate(`project:${dialog.project.project_id}`, (signal) => transport.updateAgentProject(
        dialog.project.project_id,
        { expected_revision: dialog.project.revision, name },
        signal,
      ));
      return;
    }
    if (dialog.kind === "rename-session") {
      const title = dialogValue.trim();
      if (!title) return;
      await updateCatalogSession(
        dialog.session.session_id,
        { expected_revision: dialog.session.revision, title },
      );
      return;
    }
    if (dialog.kind === "move-session") {
      if (!dialogValue || dialogValue === dialog.session.project_id) return;
      await updateCatalogSession(
        dialog.session.session_id,
        { expected_revision: dialog.session.revision, project_id: dialogValue },
      );
      return;
    }
    if (dialog.kind === "fork-session") {
      const title = dialogValue.trim();
      if (!title || onForkSession === undefined) return;
      await mutate(`fork:${dialog.session.session_id}`, (signal) => (
        onForkSession(dialog.session, title, signal)
      ));
      return;
    }
    if (dialog.kind === "delete-project") {
      const deleted = await mutate(`project:${dialog.project.project_id}`, async (signal) => {
        await transport.deleteAgentProject(
          dialog.project.project_id,
          { expected_revision: dialog.project.revision },
          signal,
        );
      });
      if (deleted && selectedProjectId === dialog.project.project_id) onProjectChange(null);
      return;
    }
    const deleted = await mutate(`session:${dialog.session.session_id}`, (signal) => (
      transport.deleteAgentCatalogSession(
        dialog.session.session_id,
        {
          expected_catalog_revision: dialog.session.revision,
          expected_history_revision: dialog.session.history_revision,
        },
        signal,
      )
    ));
    if (deleted) onSessionDeleted?.(dialog.session.session_id);
  }

  if (collapsed) {
    const selectedProject = projects?.find((project) => project.project_id === selectedProjectId)
      ?? (selectedProjectSnapshotRef.current?.project_id === selectedProjectId
        ? selectedProjectSnapshotRef.current
        : undefined);
    return (
      <nav aria-label="Agent projects and chats (collapsed)" className="agent-rail agent-rail--collapsed">
        <button
          aria-label="Expand projects and chats"
          className="agent-rail__icon-button"
          onClick={onToggleCollapsed}
          title="Expand projects and chats"
          type="button"
        >›</button>
        <button
          aria-label="New chat"
          className="agent-rail__collapsed-new"
          disabled={newChatDisabled}
          onClick={(event) => onNewChat(selectedProjectId, event.currentTarget)}
          title="New chat"
          type="button"
        >+</button>
        <span
          aria-label={selectedProject ? `Current project: ${selectedProject.name}` : "No project selected"}
          className="agent-rail__project-mark"
          title={selectedProject?.name ?? "No project selected"}
        >{selectedProject?.name.trim().charAt(0).toLocaleUpperCase() || "—"}</span>
        <span aria-label={`${sessionCoverage?.total ?? catalogSessions?.length ?? liveSessions?.length ?? 0} chats`} className="agent-rail__collapsed-count">
          {sessionCoverage?.total ?? catalogSessions?.length ?? liveSessions?.length ?? 0}
        </span>
      </nav>
    );
  }

  if (!supported) {
    return (
      <nav aria-label="Agent sessions" className="agent-rail">
        <header className="agent-rail__header">
          <div><small>Agent</small><strong>Live sessions</strong></div>
          <div className="agent-rail__header-actions">
            <button aria-label="Collapse projects and chats" className="agent-rail__icon-button" onClick={onToggleCollapsed} title="Collapse projects and chats" type="button">‹</button>
            <button className="button button--primary" disabled={newChatDisabled} onClick={(event) => onNewChat(null, event.currentTarget)} type="button">New chat</button>
          </div>
        </header>
        <p className="agent-rail__truth">These chats are temporary until the local app restarts.</p>
        <ul className="agent-rail__sessions">
          {(liveSessions ?? []).map((session) => (
            <li key={session.session_id} data-current={session.session_id === currentSessionId ? "true" : undefined}>
              <button
                aria-label={`${liveSessionTitle(session)} · ${sessionStatus({} as AgentCatalogSession, session, draftSessionIds?.has(session.session_id))}`}
                onClick={() => onOpenLiveSession(session)}
                type="button"
              >
                <strong>{liveSessionTitle(session)}</strong>
                <small>{sessionStatus({} as AgentCatalogSession, session, draftSessionIds?.has(session.session_id))}</small>
              </button>
              <button
                aria-label={`Close session ${liveSessionTitle(session)}`}
                disabled={disabled || session.closing || session.cleanup_unconfirmed}
                onClick={() => onCloseLiveSession(session)}
                type="button"
              >×</button>
              {closeFailureSessionIds?.has(session.session_id) && (
                <p className="agent-rail__close-failure" role="alert">Close was not confirmed. Its draft was kept. Try closing this chat again.</p>
              )}
            </li>
          ))}
        </ul>
      </nav>
    );
  }

  return (
    <nav aria-label="Agent projects and chats" className="agent-rail">
      <header className="agent-rail__header">
        <div><small>Local Agent</small><strong>Projects</strong></div>
        <div className="agent-rail__header-actions">
          <button aria-label="Collapse projects and chats" className="agent-rail__icon-button" onClick={onToggleCollapsed} title="Collapse projects and chats" type="button">‹</button>
          <button
            aria-label="Create project"
            className="agent-rail__icon-button"
            disabled={disabled || Boolean(busyKey)}
            onClick={(event) => openDialog({ kind: "create-project" }, event.currentTarget)}
            title="Create project"
            type="button"
          >+</button>
        </div>
      </header>

      <button
        className="button button--primary agent-rail__new-chat"
        disabled={newChatDisabled}
        onClick={(event) => onNewChat(selectedProjectId, event.currentTarget)}
        ref={newChatRef}
        type="button"
      >New chat</button>

      {savedMessageSearch !== undefined && onOpenSavedMessage !== undefined && typeof transport.getAgentCatalogSession === "function" && (
        <button
          className="button button--ghost agent-rail__saved-message-search"
          disabled={disabled}
          onClick={(event) => { messageSearchTriggerRef.current = event.currentTarget; setMessageSearchOpen(true); }}
          type="button"
        >Search saved messages</button>
      )}

      <label className="agent-rail__search">
        <span className="sr-only">Search projects and chats</span>
        <input
          maxLength={120}
          onChange={(event) => setSearch(event.currentTarget.value)}
          placeholder="Search projects and chats"
          type="search"
          value={search}
        />
      </label>

      {error && <div className="agent-rail__error" role="alert"><span>{error}</span><button onClick={refresh} type="button">Retry</button></div>}

      <div className="agent-rail__project-list" role="list" aria-label="Projects">
        {projects === null ? <p role="status">Loading projects…</p> : projects.length === 0 ? (
          <p>No project matches this view. Create one, or start a chat to use Personal workspace.</p>
        ) : projectItems.slice(projectPage.start, projectPage.end).map((project) => (
          <div
            className="agent-rail__project"
            data-archived={project.archived_at ? "true" : undefined}
            data-current={project.project_id === selectedProjectId ? "true" : undefined}
            key={project.project_id}
            role="listitem"
          >
            <button
              className="agent-rail__project-pick"
              onClick={() => onProjectChange(project.project_id)}
              type="button"
            >
              <span aria-hidden="true" className="agent-rail__disclosure">{project.project_id === selectedProjectId ? "▾" : "›"}</span>
              <span><strong>{project.name}</strong><small>{project.session_count} {project.session_count === 1 ? "chat" : "chats"}{project.archived_at ? " · archived" : ""}</small></span>
              {project.pinned && <span className="agent-rail__pin">Pinned</span>}
            </button>
            <button
              aria-expanded={actionMenu?.kind === "project" && actionMenu.project.project_id === project.project_id}
              aria-haspopup="dialog"
              aria-label={`Project actions for ${project.name}`}
              className="agent-rail__menu-trigger"
              disabled={disabled || Boolean(busyKey)}
              onClick={(event) => openActionMenu({ kind: "project", project }, event.currentTarget)}
              type="button"
            >•••</button>
          </div>
        ))}
      </div>
      {selectedProjectError && (
        <div className="agent-rail__error" role="alert">
          <span>{selectedProjectError}</span>
          <button onClick={refresh} type="button">Retry project</button>
        </div>
      )}
      <BoundedListPager label="Agent project pages" page={projectPage} />
      {projectCoverage !== null && typeof transport.pageAgentProjects === "function" && (
        <div className="agent-rail__server-page" aria-live="polite">
          <span>{projectItems.length} of {projectCoverage.total} projects available</span>
          {projectPageError && (
            <span className="agent-rail__server-page-error" role="alert">{projectPageError}</span>
          )}
          {projectCoverage.nextOffset !== null && !projectPageError && (
            <button
              disabled={projectPageBusy}
              onClick={() => void loadMoreProjects()}
              type="button"
            >{projectPageBusy ? "Loading…" : "Load more projects"}</button>
          )}
          {projectPageError && <button onClick={refresh} type="button">Reload projects</button>}
        </div>
      )}

      <section aria-labelledby="agent-rail-chats" className="agent-rail__chat-section">
        <div className="agent-rail__section-head">
          <h2 id="agent-rail-chats">{normalizedSearch ? "Matching chats" : "Chats"}</h2>
          <span>{sessionItems.length}{sessionCoverage ? ` / ${sessionCoverage.total}` : ""}</span>
        </div>
        {selectedProjectId === null && !normalizedSearch ? <p>Select or create a project.</p>
          : catalogSessions === null ? <p role="status">Loading chats…</p>
            : catalogSessions.length === 0 ? <p>{normalizedSearch ? "No chat matches your search." : "No chat matches this view."}</p>
              : (
                <ul className="agent-rail__sessions">
                  {sessionItems.slice(sessionPage.start, sessionPage.end).map((session) => {
                    const live = liveById.get(session.session_id);
                    const projectContext = normalizedSearch
                      ? projectNameById.get(session.project_id) ?? "Unknown project"
                      : "";
                    const status = sessionStatus(
                      session,
                      live,
                      draftSessionIds?.has(session.session_id),
                    );
                    return (
                      <li
                        data-archived={session.archived_at ? "true" : undefined}
                        data-current={session.session_id === currentSessionId ? "true" : undefined}
                        key={session.session_id}
                      >
                        <button
                          aria-label={`${session.title} · ${projectContext ? `${projectContext} · ` : ""}${status}${session.model_alias ? ` · ${session.model_alias}` : ""}`}
                          className="agent-rail__session-pick"
                          onClick={() => openCatalogSession(session, live)}
                          type="button"
                        >
                          <strong>{session.title}</strong>
                          <small>{projectContext ? `${projectContext} · ` : ""}{status}{session.model_alias ? ` · ${session.model_alias}` : ""}</small>
                        </button>
                        <button
                          aria-expanded={actionMenu?.kind === "session" && actionMenu.session.session_id === session.session_id}
                          aria-haspopup="dialog"
                          aria-label={`Chat actions for ${session.title}`}
                          className="agent-rail__menu-trigger"
                          disabled={disabled || Boolean(busyKey)}
                          onClick={(event) => openActionMenu({ kind: "session", session }, event.currentTarget)}
                          type="button"
                        >•••</button>
                        {live !== undefined && closeFailureSessionIds?.has(session.session_id) && (
                          <p className="agent-rail__close-failure" role="alert">Close was not confirmed. Its draft was kept. Try closing this chat again.</p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
        <BoundedListPager label="Agent chat pages" page={sessionPage} />
        {sessionCoverage !== null && typeof transport.pageAgentCatalogSessions === "function" && (
          <div className="agent-rail__server-page" aria-live="polite">
            <span>{sessionItems.length} of {sessionCoverage.total} chats available</span>
            {sessionPageError && (
              <span className="agent-rail__server-page-error" role="alert">{sessionPageError}</span>
            )}
            {sessionCoverage.nextOffset !== null && !sessionPageError && (
              <button
                disabled={sessionPageBusy}
                onClick={() => void loadMoreSessions()}
                type="button"
              >{sessionPageBusy ? "Loading…" : "Load more chats"}</button>
            )}
            {sessionPageError && <button onClick={refresh} type="button">Reload chats</button>}
          </div>
        )}
      </section>

      <label className="agent-rail__archived">
        <input checked={includeArchived} onChange={(event) => setIncludeArchived(event.currentTarget.checked)} type="checkbox" />
        <span>Show archived</span>
      </label>

      <footer className="agent-rail__truth">
        Every chat keeps local navigation. Chats marked Save locally also retain bounded conversation history; approvals and reusable authority never persist.
      </footer>

      {actionMenu && (
        <div
          className="agent-rail__action-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeActionMenu();
          }}
        >
          <section
            aria-labelledby="agent-catalog-actions-title"
            aria-modal="true"
            className="agent-rail__action-dialog"
            onKeyDownCapture={trapModalFocus}
            role="dialog"
            tabIndex={-1}
          >
            <header>
              <div>
                <small>{actionMenu.kind === "project" ? "Project" : "Chat"}</small>
                <h2 id="agent-catalog-actions-title">
                  {actionMenu.kind === "project"
                    ? `Project actions for ${actionMenu.project.name}`
                    : `Chat actions for ${actionMenu.session.title}`}
                </h2>
              </div>
              <button aria-label="Close actions" className="button button--ghost" onClick={() => closeActionMenu()} type="button">Close</button>
            </header>
            <div className="agent-rail__action-grid">
              {actionMenu.kind === "project" ? (
                <>
                  <button autoFocus disabled={disabled || Boolean(busyKey)} onClick={() => openDialog({ kind: "rename-project", project: actionMenu.project })} type="button">Rename</button>
                  <button disabled={disabled || Boolean(busyKey)} onClick={() => void mutate(`project:${actionMenu.project.project_id}`, (signal) => transport.updateAgentProject(actionMenu.project.project_id, { expected_revision: actionMenu.project.revision, pinned: !actionMenu.project.pinned }, signal))} type="button">{actionMenu.project.pinned ? "Unpin" : "Pin"}</button>
                  {!actionMenu.project.is_default && <button disabled={disabled || Boolean(busyKey)} onClick={() => void mutate(`project:${actionMenu.project.project_id}`, (signal) => transport.updateAgentProject(actionMenu.project.project_id, { expected_revision: actionMenu.project.revision, archived: !actionMenu.project.archived_at }, signal))} type="button">{actionMenu.project.archived_at ? "Restore" : "Archive"}</button>}
                  {!actionMenu.project.is_default && actionMenu.project.session_count === 0 && <button className="agent-rail__danger" disabled={disabled || Boolean(busyKey)} onClick={() => openDialog({ kind: "delete-project", project: actionMenu.project })} type="button">Delete</button>}
                </>
              ) : (() => {
                const session = actionMenu.session;
                const live = liveById.get(session.session_id);
                return <>
                  <button autoFocus disabled={disabled || Boolean(busyKey)} onClick={() => openDialog({ kind: "rename-session", session })} type="button">Rename</button>
                  <button disabled={disabled || Boolean(busyKey)} onClick={() => openDialog({ kind: "move-session", session })} type="button">Move to project</button>
                  {session.retention_policy === "local_history" && onForkSession !== undefined && (
                    <button
                      disabled={disabled || Boolean(session.archived_at || live?.running || live?.closing || live?.pending_approval_id)}
                      onClick={() => openDialog({ kind: "fork-session", session })}
                      type="button"
                    >Fork latest completed turn</button>
                  )}
                  <button disabled={disabled || Boolean(busyKey)} onClick={() => void updateCatalogSession(session.session_id, { expected_revision: session.revision, pinned: !session.pinned })} type="button">{session.pinned ? "Unpin" : "Pin"}</button>
                  {live
                    ? <button disabled={disabled || Boolean(busyKey)} onClick={() => { closeActionMenu(false); onCloseLiveSession(live); }} type="button">Close live chat</button>
                    : <button disabled={disabled || Boolean(busyKey)} onClick={() => void updateCatalogSession(session.session_id, { expected_revision: session.revision, archived: !session.archived_at })} type="button">{session.archived_at ? "Restore" : "Archive"}</button>}
                  {!live && <button className="agent-rail__danger" disabled={disabled || Boolean(busyKey)} onClick={() => openDialog({ kind: "delete-session", session })} type="button">Delete</button>}
                </>;
              })()}
            </div>
          </section>
        </div>
      )}

      {dialog && (
        <div
          aria-labelledby="agent-catalog-dialog-title"
          aria-modal="true"
          className="agent-rail__dialog-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target && mutationRef.current === null) {
              closeDialog();
            }
          }}
          role="dialog"
        >
          <form
            className="agent-rail__dialog"
            onKeyDownCapture={trapModalFocus}
            onSubmit={(event) => { event.preventDefault(); void submitDialog(); }}
            ref={dialogRef}
            tabIndex={-1}
          >
            <h2 id="agent-catalog-dialog-title">
              {dialog.kind === "create-project" ? "Create project"
                : dialog.kind === "rename-project" ? "Rename project"
                  : dialog.kind === "rename-session" ? "Rename chat"
                    : dialog.kind === "fork-session" ? "Fork chat"
                    : dialog.kind === "move-session" ? "Move chat"
                    : dialog.kind === "delete-project" ? "Delete project"
                      : "Delete chat"}
            </h2>
            {dialog.kind === "create-project" || dialog.kind === "rename-project" || dialog.kind === "rename-session" || dialog.kind === "fork-session" ? (
              <label>
                <span>{dialog.kind === "rename-session" || dialog.kind === "fork-session" ? "Chat name" : "Project name"}</span>
                <input autoFocus maxLength={120} onChange={(event) => setDialogValue(event.currentTarget.value)} value={dialogValue} />
              </label>
            ) : dialog.kind === "move-session" ? (
              moveDestinations === null ? (
                <p role="status">Loading active projects…</p>
              ) : moveDestinationError ? (
                <div className="agent-rail__error" role="alert">
                  <span>{moveDestinationError}</span>
                  <button onClick={() => setMoveDestinationNonce((value) => value + 1)} type="button">Retry projects</button>
                </div>
              ) : moveDestinations.length === 0 ? (
                <p role="status">There is no other active project. Create or restore a project before moving this chat.</p>
              ) : (
                <label>
                  <span>Destination project</span>
                  <select autoFocus onChange={(event) => setDialogValue(event.currentTarget.value)} value={dialogValue}>
                    {moveDestinations.map((project) => (
                      <option key={project.project_id} value={project.project_id}>{project.name}</option>
                    ))}
                  </select>
                </label>
              )
            ) : (
              <p>{dialog.kind === "delete-session" && dialog.session.retention_policy === "local_history"
                ? "This permanently deletes the selected chat record and its retained local conversation. Workspace files are not deleted."
                : "This removes only the selected navigation record. It does not delete workspace files."}</p>
            )}
            {dialog.kind === "fork-session" && (
              <p>
                Copies retained history through the latest completed turn. The branch starts inactive and receives no approvals, protected-action authority, staged attachments, or artifact ownership.
              </p>
            )}
            <div className="agent-rail__dialog-actions">
              <button className="button button--ghost" disabled={Boolean(busyKey)} onClick={() => closeDialog()} type="button">Cancel</button>
              <button className={dialog.kind.startsWith("delete") ? "button agent-rail__danger-button" : "button button--primary"} disabled={disabled || Boolean(busyKey) || ((dialog.kind === "create-project" || dialog.kind.startsWith("rename") || dialog.kind === "move-session" || dialog.kind === "fork-session") && !dialogValue.trim())} type="submit">
                {busyKey ? "Saving…" : dialog.kind.startsWith("delete") ? "Delete" : dialog.kind === "fork-session" ? "Create branch" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
      {messageSearchOpen && savedMessageSearch !== undefined && onOpenSavedMessage !== undefined && (
        <AgentMessageSearchDialog
          initialProjectId={selectedProjectId}
          onClose={closeMessageSearch}
          onOpenMatch={openSavedMessage}
          search={savedMessageSearch}
        />
      )}
    </nav>
  );
}
