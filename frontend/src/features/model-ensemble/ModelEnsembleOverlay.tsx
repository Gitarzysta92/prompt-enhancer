import { useEffect, useMemo, useRef, useState } from "react";
import type {
  CodexSession,
  ModelEnsembleAttemptStage,
  ModelEnsembleCanonicalHead,
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPage,
  ModelEnsembleWatchSnapshot,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { MetricDefinitionsOutOfDateError, type MetricDefinitionMismatch } from "../../shared/api/metricPublicationV2Contract";
import type { TeamControlPlanePort } from "../../shared/api/teamControlPlane";
import { TeamContextDrawer } from "../team-analytics/TeamContextDrawer";
import type { ModelEnsembleLensId } from "./metricAxisModel";
import { METRIC_DEFINITIONS_OUT_OF_DATE_TITLE, MetricDefinitionsOutOfDateAlert } from "./MetricDefinitionsAlert";
import { MetricWorkspace } from "./MetricWorkspace";
import {
  MODEL_ENSEMBLE_DEFAULT_MAX_MESSAGES,
  MODEL_ENSEMBLE_MESSAGE_WINDOWS,
} from "./modelEnsembleConstants";
import { useTrajectorySelection } from "./useTrajectorySelection";
import { MODEL_CLEANUP_RECOVERY, useModelCleanupWarning, watchPauseCopy } from "./modelEnsembleFailureCopy";
import {
  CANONICAL_POLL_IDLE_MS,
  CANONICAL_POLL_RETRY_MS,
  CANONICAL_POLL_WRONG_RUN_MS,
  TRAJECTORY_RETRY_LIMIT,
  TRAJECTORY_RETRY_MS,
  PollCoordinator,
  PollFailureTracker,
  canonicalHeadIdentity,
  canonicalHeadPollDelay,
  httpStatusOf as statusOf,
  isStaleWatchHead,
  watchSnapshotIdentity,
  watchSnapshotPollDelay,
} from "./canonicalPolling";

type CatalogWindow = "all" | "7" | "30" | "90";

function sessionDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function sessionLabel(session: CodexSession): string {
  return `${session.session_display_name ?? "Unnamed session"} · ${sessionDate(session.started_at)}`;
}

function shortTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(parsed);
}

function snapshotTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(parsed);
}

function watchFailureCopy(code: string | null): string {
  switch (code) {
    case "source_timeout":
      return "the local source timed out";
    case "provider_unavailable":
    case "provider_protocol_rejected":
      return "the local provider adapter was unavailable";
    case "source_selection_limit":
    case "source_provider_response_limit":
    case "source_thread_structure_limit":
    case "source_preview_window_limit":
    case "source_resource_limit":
      return "the selected source exceeded a bounded adapter limit";
    case "redacted_content_consent_required":
      return "redacted-content consent is no longer active";
    case "provider_compatibility_blocked":
      return "provider compatibility is not verified";
    case "session_not_in_safe_index":
      return "the selected session is no longer in the safe index";
    case "model_ensemble_persistence_failed":
      return "the completed receipt could not be stored";
    case "local_model_ensemble_execution_failed":
    case "model_ensemble_watch_execution_failed":
      return "a local model stage did not complete";
    default:
      return "the previous local update did not complete";
  }
}

function watchStatus(snapshot: ModelEnsembleWatchSnapshot): string {
  if (watchPauseCopy(snapshot.watch) !== null) return "Automatic updates paused · local runtime needs attention";
  switch (snapshot.watch.state) {
    case "queued": return "Waiting for the local model lane";
    case "running": return snapshot.watch.last_error_code === null
      ? `Updating · local pipeline ${snapshot.watch.progress_completed}/${snapshot.watch.progress_total}`
      : `Retrying · local pipeline ${snapshot.watch.progress_completed}/${snapshot.watch.progress_total}`;
    case "failed": return snapshot.latest_run === null
      ? "Update failed · no completed receipt"
      : "Update failed · retaining the last valid receipt";
    case "idle": return snapshot.latest_run === null
      ? "Waiting for the first completed receipt"
      : `Up to date · completed ${shortTime(snapshot.latest_run.completed_at)} UTC`;
    default: return "Watch stopped";
  }
}

function watchDetail(snapshot: ModelEnsembleWatchSnapshot): string {
  const prefix = `Newest ${snapshot.watch.max_messages} messages`;
  const paused = watchPauseCopy(snapshot.watch);
  if (paused !== null) return `${prefix} · ${paused}`;
  if (snapshot.watch.state === "running") {
    const retry = snapshot.watch.last_error_code === null
      ? ""
      : ` · retrying after ${watchFailureCopy(snapshot.watch.last_error_code)}`;
    return `${prefix} · stage names are unavailable in this v1 status receipt${retry}`;
  }
  if (snapshot.watch.state === "queued") {
    const retry = snapshot.watch.last_error_code === null
      ? ""
      : ` · retry queued after ${watchFailureCopy(snapshot.watch.last_error_code)}`;
    return `${prefix} · waiting for the serial local model lane${retry}`;
  }
  if (snapshot.watch.state === "failed") {
    const retry = snapshot.watch.quarantined === false
      ? `automatic retry ${shortTime(snapshot.watch.next_check_at)} UTC`
      : "automatic retry status unavailable";
    return `${prefix} · ${watchFailureCopy(snapshot.watch.last_error_code)} · ${retry}`;
  }
  if (snapshot.watch.state === "disabled") return `${prefix} · continuous updates are stopped`;
  return `${prefix} · next observation ${shortTime(snapshot.watch.next_check_at)} UTC · serial local lane`;
}

function canonicalStatus(head: ModelEnsembleCanonicalHead | null, snapshot: ModelEnsembleWatchSnapshot): string {
  if (watchPauseCopy(snapshot.watch) !== null) return watchStatus(snapshot);
  const attempt = head?.latest_attempt;
  if (attempt === null || attempt === undefined) return watchStatus(snapshot);
  if (attempt.state === "running") return `Updating · ${attempt.progress_completed}/${attempt.progress_total} pipeline steps`;
  if (snapshot.watch.state === "queued") return "Queued · waiting for the local model lane";
  if (attempt.state === "failed") return snapshot.latest_run === null ? "Update failed · no completed snapshot" : "Update failed · retaining the last valid snapshot";
  if (attempt.state === "cancelled") return snapshot.latest_run === null ? "Analysis cancelled · no completed snapshot" : "Analysis cancelled · last valid snapshot retained";
  if (attempt.state === "partial") return `Updated with ${attempt.warning_count} warning${attempt.warning_count === 1 ? "" : "s"}`;
  return snapshot.latest_run === null ? "Waiting for the first sealed snapshot" : `Up to date · completed ${shortTime(snapshot.latest_run.completed_at)} UTC`;
}

function canonicalDetail(head: ModelEnsembleCanonicalHead | null, snapshot: ModelEnsembleWatchSnapshot): string {
  const attempt = head?.latest_attempt;
  if (attempt?.state === "running") {
    const latestStage = head?.stages.at(-1);
    return latestStage === undefined
      ? "Preparing the first local measurement stage"
      : `Last completed: ${latestStage.stage_key.replaceAll("_", " ")} · ${stageCaseCountCopy(latestStage)}`;
  }
  return watchDetail(snapshot);
}

/** Null case counts are unavailable evidence; they are never rendered as 0/0. */
export function stageCaseCountCopy(
  stage: Pick<ModelEnsembleAttemptStage, "contributed_case_count" | "evaluated_case_count">,
): string {
  if (stage.contributed_case_count === null || stage.evaluated_case_count === null) {
    return "case counts unavailable";
  }
  return `${stage.contributed_case_count}/${stage.evaluated_case_count} cases contributed`;
}

/**
 * A just-created run cannot be cancelled by the second click of an Analyze
 * double-click. The controls are separate, and Cancel is briefly disarmed for
 * the exact attempt queued by this window.
 */
export const CANCEL_ARMING_DELAY_MS = 1_500;

const SMALL_VIEWPORT_QUERY = "(max-width: 500px), (max-height: 720px)";

function useSmallViewport(): boolean {
  const [small, setSmall] = useState(() =>
    typeof window.matchMedia === "function" && window.matchMedia(SMALL_VIEWPORT_QUERY).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(SMALL_VIEWPORT_QUERY);
    const update = () => setSmall(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return small;
}

type DesktopWindowApi = {
  close_window(): Promise<void>;
  minimize_window(): Promise<void>;
  toggle_maximize_window(): Promise<boolean>;
};

function desktopWindowApi(): DesktopWindowApi | null {
  const hostWindow = window as typeof window & {
    pywebview?: { api?: Partial<DesktopWindowApi> };
  };
  const api = hostWindow.pywebview?.api;
  return api !== undefined
    && typeof api.close_window === "function"
    && typeof api.minimize_window === "function"
    && typeof api.toggle_maximize_window === "function"
    ? api as DesktopWindowApi
    : null;
}

export function ModelEnsembleOverlay({
  transport,
  teamControlPlane = null,
}: {
  transport: PromptEnhancerTransport;
  teamControlPlane?: TeamControlPlanePort | null;
}) {
  const [snapshot, setSnapshot] = useState<ModelEnsembleWatchSnapshot | null>(null);
  const cleanupWarning = useModelCleanupWarning(snapshot?.watch);
  const [canonicalHead, setCanonicalHead] = useState<ModelEnsembleCanonicalHead | null>(null);
  const [trajectory, setTrajectory] = useState<ModelEnsembleTrajectoryPage | null>(null);
  const [trajectoryError, setTrajectoryError] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [lensId, setLensId] = useState<ModelEnsembleLensId>("task-framing");
  const [disconnected, setDisconnected] = useState(false);
  /**
   * Set when the compatibility gate refuses a fresh publication. While set, no
   * run is retained or rendered (all twenty values and guidance are cleared)
   * and the status never reads as "reconnecting": it is a client-update state.
   */
  const [definitionsOutOfDate, setDefinitionsOutOfDate] = useState<MetricDefinitionMismatch | null>(null);
  /**
   * The history page (not the live head) was published under other definitions.
   * Scoped to the history so a compatible live receipt is neither hidden nor
   * flashed: the head poll owns `definitionsOutOfDate`, this owns the drawer.
   */
  const [trajectoryDefinitionsMismatch, setTrajectoryDefinitionsMismatch] = useState<MetricDefinitionMismatch | null>(null);
  const [sessions, setSessions] = useState<CodexSession[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [scopeError, setScopeError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [catalogWindow, setCatalogWindow] = useState<CatalogWindow>("all");
  const [maxMessages, setMaxMessages] = useState(MODEL_ENSEMBLE_DEFAULT_MAX_MESSAGES);
  const [watchChanging, setWatchChanging] = useState(false);
  const [pendingAction, setPendingAction] = useState<"analyze" | "cancel" | null>(null);
  const [disarmedAttemptId, setDisarmedAttemptId] = useState<string | null>(null);
  const [scopeExpanded, setScopeExpanded] = useState(true);
  const [nativeHost, setNativeHost] = useState(() => desktopWindowApi() !== null);
  const [maximized, setMaximized] = useState(false);
  const smallViewport = useSmallViewport();
  const synchronizedWatch = useRef("");
  const followingLive = useRef(true);
  const snapshotRef = useRef<ModelEnsembleWatchSnapshot | null>(null);
  const canonicalHeadRef = useRef<ModelEnsembleCanonicalHead | null>(null);
  const coordinatorRef = useRef<PollCoordinator | null>(null);
  const pendingActionRef = useRef<"analyze" | "cancel" | null>(null);

  useEffect(() => {
    const ready = () => setNativeHost(desktopWindowApi() !== null);
    window.addEventListener("pywebviewready", ready);
    ready();
    return () => window.removeEventListener("pywebviewready", ready);
  }, []);

  useEffect(() => { snapshotRef.current = snapshot; }, [snapshot]);
  useEffect(() => { canonicalHeadRef.current = canonicalHead; }, [canonicalHead]);

  /** Applies a head/run pair atomically so watch status and sealed run never disagree. */
  function applyCanonical(head: ModelEnsembleCanonicalHead | null, latestSnapshot: ModelEnsembleWatchSnapshot | null) {
    canonicalHeadRef.current = head;
    snapshotRef.current = latestSnapshot;
    setCanonicalHead(head);
    setSnapshot(latestSnapshot);
  }

  useEffect(() => {
    const controller = new AbortController();
    setCatalogLoading(true);
    transport.listCodexSessions(100, 0, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setSessions(response.sessions);
        setCatalogError("");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setCatalogError("The indexed session catalog is unavailable. The current receipt can still be viewed.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [transport]);

  const trajectoryWatchId = snapshot?.watch.state === "disabled"
    ? null
    : snapshot?.watch.watch_id ?? null;
  const trajectoryHeadRunId = snapshot?.latest_run?.run_id ?? null;

  useEffect(() => {
    if (trajectoryWatchId === null || transport.getModelEnsembleTrajectory === undefined) {
      setTrajectory(null);
      setTrajectoryError(false);
      setTrajectoryDefinitionsMismatch(null);
      setSelectedRunId(null);
      followingLive.current = true;
      return;
    }
    if (followingLive.current && trajectoryHeadRunId !== null) setSelectedRunId(trajectoryHeadRunId);
    const controller = new AbortController();
    let retryTimer: number | undefined;
    let attempts = 0;
    const fetchTrajectory = transport.getModelEnsembleTrajectory;
    const load = () => {
      attempts += 1;
      fetchTrajectory(trajectoryWatchId, 24, undefined, controller.signal)
        .then((page) => {
          if (controller.signal.aborted || page.watch_id !== trajectoryWatchId) return;
          if (page.head_run_id !== trajectoryHeadRunId) {
            // Publication race: the exact head and the trajectory index were read
            // on different sides of a publish. Keep the previously loaded history
            // visible and retry a bounded number of times before waiting for the
            // next head change.
            setTrajectoryError(page.head_run_id !== null);
            if (attempts < TRAJECTORY_RETRY_LIMIT) {
              retryTimer = window.setTimeout(() => {
                retryTimer = undefined;
                if (!controller.signal.aborted) load();
              }, TRAJECTORY_RETRY_MS);
            }
            return;
          }
          setTrajectory(page);
          setTrajectoryError(false);
          setTrajectoryDefinitionsMismatch(null);
          setSelectedRunId((current) => {
            if (followingLive.current) return page.head_run_id;
            if (current !== null && page.points.some((point) => point.run_id === current)) {
              return current;
            }
            followingLive.current = true;
            return page.head_run_id;
          });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          if (error instanceof MetricDefinitionsOutOfDateError) {
            // History published under other definitions: withhold every history
            // point (no compact values, no comparison) and say why. The live head
            // stays governed by its own gate, so nothing compatible is hidden.
            setTrajectoryDefinitionsMismatch(error.mismatch);
            setTrajectory(null);
            setSelectedRunId(trajectoryHeadRunId);
            followingLive.current = true;
          }
          setTrajectoryError(true);
        });
    };
    load();
    return () => {
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [trajectoryHeadRunId, trajectoryWatchId, transport]);

  useEffect(() => {
    if (transport.getActiveModelEnsembleCanonicalHead === undefined && transport.getActiveModelEnsembleWatch === undefined) {
      setDisconnected(true);
      return;
    }
    const failures = new PollFailureTracker();
    const healthy = () => {
      failures.reset();
      setDisconnected(false);
    };
    /** A poll that could not be trusted keeps the last complete snapshot and retries. */
    const degraded = (delay: number) => {
      if (failures.recordFailure()) setDisconnected(true);
      coordinator.schedule(delay);
    };
    /**
     * The service published metrics this client's definitions are not bound
     * to. Clear every retained value and guidance receipt, keep the head so
     * the watch identity stays truthful, and keep polling at the idle cadence
     * so a fixed client or a service rollback is picked up.
     */
    const definitionsMismatch = (
      head: ModelEnsembleCanonicalHead | null,
      mismatch: MetricDefinitionMismatch,
    ) => {
      setDefinitionsOutOfDate(mismatch);
      applyCanonical(head, head === null ? null : { watch: head.watch, latest_run: null });
      healthy();
      coordinator.schedule(CANONICAL_POLL_IDLE_MS);
    };
    const coordinator = new PollCoordinator(async (ticket) => {
      const canonicalTransport = transport.getActiveModelEnsembleCanonicalHead !== undefined
        && transport.getModelEnsembleSnapshot !== undefined;
      let head: ModelEnsembleCanonicalHead | null = null;
      let legacy: ModelEnsembleWatchSnapshot | null = null;
      try {
        if (canonicalTransport) {
          head = await transport.getActiveModelEnsembleCanonicalHead!(ticket.signal);
        } else {
          legacy = await transport.getActiveModelEnsembleWatch!(ticket.signal);
        }
      } catch (error) {
        if (!ticket.isCurrent()) return;
        if (statusOf(error) === 404) {
          // A definitive "no active watch" from the head route is state, not a
          // failure; with no watch there is no publication left to be out of date.
          setDefinitionsOutOfDate(null);
          applyCanonical(null, null);
          healthy();
          coordinator.schedule(CANONICAL_POLL_IDLE_MS);
          return;
        }
        if (error instanceof MetricDefinitionsOutOfDateError) {
          // Legacy watch snapshot embeds the run: identity mismatch is a
          // client-update state, not a transport failure.
          definitionsMismatch(null, error.mismatch);
          return;
        }
        degraded(CANONICAL_POLL_RETRY_MS);
        return;
      }
      if (!ticket.isCurrent()) return;
      if (head !== null) {
        if (isStaleWatchHead(
          canonicalHeadRef.current === null ? null : canonicalHeadIdentity(canonicalHeadRef.current),
          canonicalHeadIdentity(head),
        )) {
          // Older generation for the same watch: never regress the displayed head.
          healthy();
          coordinator.schedule(canonicalHeadPollDelay(canonicalHeadRef.current!));
          return;
        }
        const existingRun = snapshotRef.current?.latest_run ?? null;
        let nextRun = existingRun;
        if (head.head_run_id === null) {
          nextRun = null;
        } else if (existingRun?.run_id !== head.head_run_id) {
          try {
            nextRun = await transport.getModelEnsembleSnapshot!(head.head_run_id, ticket.signal);
          } catch (error) {
            // The immutable snapshot route failed (including 404): the head is
            // known but its run is not readable yet. Retain the last complete
            // snapshot rather than showing a head without its run.
            if (!ticket.isCurrent()) return;
            if (error instanceof MetricDefinitionsOutOfDateError) {
              definitionsMismatch(head, error.mismatch);
              return;
            }
            degraded(CANONICAL_POLL_RETRY_MS);
            return;
          }
          if (!ticket.isCurrent()) return;
          if (nextRun.run_id !== head.head_run_id) {
            // Parser-valid snapshot for a different run: keep the last complete
            // snapshot visible and retry rather than stopping the poll loop.
            degraded(CANONICAL_POLL_WRONG_RUN_MS);
            return;
          }
        }
        setDefinitionsOutOfDate(null);
        applyCanonical(head, { watch: head.watch, latest_run: nextRun });
        healthy();
        coordinator.schedule(canonicalHeadPollDelay(head));
        return;
      }
      if (legacy !== null) {
        if (isStaleWatchHead(
          snapshotRef.current === null ? null : watchSnapshotIdentity(snapshotRef.current),
          watchSnapshotIdentity(legacy),
        )) {
          healthy();
          coordinator.schedule(watchSnapshotPollDelay(snapshotRef.current!));
          return;
        }
        setDefinitionsOutOfDate(null);
        applyCanonical(null, legacy);
        healthy();
        coordinator.schedule(watchSnapshotPollDelay(legacy));
      }
    });
    coordinatorRef.current = coordinator;
    const visible = () => {
      if (document.visibilityState === "visible") coordinator.pollNow();
    };
    document.addEventListener("visibilitychange", visible);
    coordinator.pollNow();
    return () => {
      coordinator.stop();
      if (coordinatorRef.current === coordinator) coordinatorRef.current = null;
      document.removeEventListener("visibilitychange", visible);
    };
  }, [transport]);

  useEffect(() => {
    if (snapshot === null || snapshot.watch.state === "disabled") return;
    const key = `${snapshot.watch.watch_id}:${snapshot.watch.max_messages}`;
    if (synchronizedWatch.current === key) return;
    synchronizedWatch.current = key;
    setProjectId(snapshot.watch.project_id);
    setSessionId(snapshot.watch.session_id);
    setMaxMessages(snapshot.watch.max_messages);
    setScopeExpanded(false);
  }, [snapshot]);

  const filteredSessions = useMemo(() => {
    if (catalogWindow === "all") return sessions;
    const cutoff = Date.now() - Number(catalogWindow) * 24 * 60 * 60 * 1000;
    return sessions.filter((session) => {
      const started = new Date(session.started_at).getTime();
      return Number.isFinite(started) && started >= cutoff;
    });
  }, [catalogWindow, sessions]);

  const projects = useMemo(() => {
    const projectMap = new Map<string, string>();
    for (const session of filteredSessions) {
      if (!projectMap.has(session.project_id)) {
        projectMap.set(session.project_id, session.project_display_name ?? "Unnamed project");
      }
    }
    if (
      snapshot !== null
      && snapshot.watch.state !== "disabled"
      && !projectMap.has(snapshot.watch.project_id)
    ) {
      projectMap.set(snapshot.watch.project_id, "Current watched project");
    }
    return [...projectMap.entries()].map(([id, label]) => ({ id, label }));
  }, [filteredSessions, snapshot]);

  const projectSessions = useMemo(
    () => filteredSessions.filter((session) => session.project_id === projectId),
    [filteredSessions, projectId],
  );

  useEffect(() => {
    const selectionIsActive = snapshot !== null
      && snapshot.watch.state !== "disabled"
      && snapshot.watch.project_id === projectId
      && snapshot.watch.session_id === sessionId;
    if (selectionIsActive) return;
    if (filteredSessions.length === 0) {
      setProjectId("");
      setSessionId("");
      return;
    }
    const selected = filteredSessions.find((session) => session.session_id === sessionId);
    if (selected !== undefined && selected.project_id === projectId) return;
    const nextProject = projects.some((project) => project.id === projectId)
      ? projectId
      : projects[0]?.id ?? "";
    const nextSession = filteredSessions.find((session) => session.project_id === nextProject);
    setProjectId(nextProject);
    setSessionId(nextSession?.session_id ?? "");
  }, [filteredSessions, projectId, projects, sessionId, snapshot]);

  const activeForSelection = snapshot !== null
    && snapshot.watch.state !== "disabled"
    && snapshot.watch.project_id === projectId
    && snapshot.watch.session_id === sessionId
    && snapshot.watch.max_messages === maxMessages;
  const activeForSession = snapshot !== null
    && snapshot.watch.state !== "disabled"
    && snapshot.watch.session_id === sessionId;
  const activeSessionOutsideCatalog = activeForSession
    && !projectSessions.some((session) => session.session_id === sessionId);
  const linkProjectId = projectId || snapshot?.watch.project_id || "";
  const linkSessionId = sessionId || snapshot?.watch.session_id || "";
  const category = lensId === "task-framing" || lensId === "collaboration-flow"
    ? "prompt-quality"
    : "reasoning";
  const visibleTrajectory = trajectory?.watch_id === trajectoryWatchId ? trajectory : null;
  const trajectoryPoints = visibleTrajectory?.points ?? [];
  const {
    selectedPoint,
    historicalRun,
    historicalRunRefused,
    selectedRadarRun,
    comparisonRadarRun,
  } = useTrajectorySelection({
    transport,
    points: trajectoryPoints,
    selectedRunId,
    headRun: snapshot?.latest_run ?? null,
  });

  function selectTrajectoryRun(runId: string | null) {
    followingLive.current = runId !== null && runId === trajectoryHeadRunId;
    setSelectedRunId(runId);
  }

  const runningAttempt = canonicalHead?.latest_attempt?.state === "running"
    ? canonicalHead.latest_attempt
    : null;
  const analyzeAvailable = snapshot !== null
    && snapshot.watch.state !== "disabled"
    && snapshot.watch.state !== "queued"
    && snapshot.watch.state !== "running"
    && runningAttempt === null
    && pendingAction === null;
  const cancelArmed = runningAttempt !== null && runningAttempt.attempt_id !== disarmedAttemptId;
  const cancelAvailable = snapshot !== null && cancelArmed && pendingAction === null;

  useEffect(() => {
    if (disarmedAttemptId === null) return undefined;
    const timer = window.setTimeout(() => setDisarmedAttemptId(null), CANCEL_ARMING_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [disarmedAttemptId]);

  function beginAction(action: "analyze" | "cancel"): boolean {
    if (pendingActionRef.current !== null) return false;
    pendingActionRef.current = action;
    setPendingAction(action);
    return true;
  }

  function endAction(): void {
    pendingActionRef.current = null;
    setPendingAction(null);
  }

  /**
   * A command result (watch change, analyze, cancel) that the compatibility
   * gate refused. The refused publication is the newest truth for this watch,
   * so the previously displayed run must not stay visible beside a generic
   * error: clear it and show the update-client state. A later compatible poll
   * or command clears the state again.
   */
  function refuseCommandDefinitions(mismatch: MetricDefinitionMismatch) {
    setDefinitionsOutOfDate(mismatch);
    const current = snapshotRef.current;
    applyCanonical(canonicalHeadRef.current, current === null ? null : { ...current, latest_run: null });
  }

  /**
   * Resolves the exact sealed run for a command's canonical head. Reuses the
   * displayed run when the head did not move; otherwise fetches the immutable
   * snapshot and refuses any run whose id differs from the head.
   */
  async function resolveCommandRun(head: ModelEnsembleCanonicalHead): Promise<ModelEnsembleRun | null> {
    const current = snapshotRef.current;
    if (
      current === null
      || head.watch.watch_id !== current.watch.watch_id
      || head.watch.session_id !== current.watch.session_id
    ) throw new Error("durable_watch_identity_mismatch");
    if (head.head_run_id === null) return null;
    if (current.latest_run?.run_id === head.head_run_id) return current.latest_run;
    if (transport.getModelEnsembleSnapshot === undefined) throw new Error("durable_snapshot_unavailable");
    const exactRun = await transport.getModelEnsembleSnapshot(head.head_run_id);
    if (exactRun.run_id !== head.head_run_id) throw new Error("durable_snapshot_identity_mismatch");
    return exactRun;
  }

  async function changeWatch() {
    if (watchChanging || sessionId === "" || projectId === "") return;
    setWatchChanging(true);
    setScopeError("");
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      if (activeForSelection && snapshot !== null) {
        if (transport.disableModelEnsembleWatch === undefined) throw new Error("unavailable");
        await transport.disableModelEnsembleWatch(snapshot.watch.watch_id);
        synchronizedWatch.current = "";
        followingLive.current = true;
        applyCanonical(null, null);
        resumeDelay = CANONICAL_POLL_IDLE_MS;
      } else {
        if (transport.enableModelEnsembleWatch === undefined) throw new Error("unavailable");
        const next = await transport.enableModelEnsembleWatch(sessionId, {
          project_id: projectId,
          max_messages: maxMessages,
          confirmation: "continuously_analyze_selected_redacted_session",
        });
        // A parsed run supersedes an earlier refusal; a run-less watch leaves the
        // head poll to decide.
        if (next.latest_run !== null) setDefinitionsOutOfDate(null);
        applyCanonical(null, next);
        followingLive.current = true;
        setScopeExpanded(false);
        resumeDelay = watchSnapshotPollDelay(next);
      }
    } catch (changeError) {
      if (changeError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(changeError.mismatch);
      } else {
        setScopeError("The live watch could not be changed. No session content was retained.");
      }
    } finally {
      setWatchChanging(false);
      coordinator?.endCommand(resumeDelay);
    }
  }

  async function analyzeNow() {
    if (!analyzeAvailable || snapshot === null || !beginAction("analyze")) return;
    setScopeError("");
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      if (transport.enqueueModelEnsembleAnalysis !== undefined) {
        const head = await transport.enqueueModelEnsembleAnalysis(snapshot.watch.watch_id);
        const exactRun = await resolveCommandRun(head);
        if (head.latest_attempt?.state === "running") setDisarmedAttemptId(head.latest_attempt.attempt_id);
        if (exactRun !== null) setDefinitionsOutOfDate(null);
        applyCanonical(head, { watch: head.watch, latest_run: exactRun });
        resumeDelay = canonicalHeadPollDelay(head);
      } else {
        if (transport.refreshModelEnsembleWatch === undefined) throw new Error("unavailable");
        const next = await transport.refreshModelEnsembleWatch(snapshot.watch.watch_id);
        if (next.latest_run !== null) setDefinitionsOutOfDate(null);
        applyCanonical(null, next);
        resumeDelay = watchSnapshotPollDelay(next);
      }
      followingLive.current = true;
    } catch (queueError) {
      if (queueError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(queueError.mismatch);
      } else {
        setScopeError("Analysis could not be queued. The last complete receipt remains visible.");
      }
    } finally {
      endAction();
      coordinator?.endCommand(resumeDelay);
    }
  }

  async function cancelAnalysis() {
    if (!cancelAvailable || snapshot === null || !beginAction("cancel")) return;
    setScopeError("");
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      if (transport.cancelModelEnsembleAnalysis === undefined) throw new Error("unavailable");
      const next = await transport.cancelModelEnsembleAnalysis(snapshot.watch.watch_id);
      const exactRun = await resolveCommandRun(next);
      if (exactRun !== null) setDefinitionsOutOfDate(null);
      applyCanonical(next, { watch: next.watch, latest_run: exactRun });
      resumeDelay = canonicalHeadPollDelay(next);
    } catch (cancelError) {
      if (cancelError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(cancelError.mismatch);
      } else {
        setScopeError("Cancellation could not be confirmed. The latest sealed snapshot remains visible.");
      }
    } finally {
      endAction();
      coordinator?.endCommand(resumeDelay);
    }
  }

  async function minimizeWindow() {
    try {
      await desktopWindowApi()?.minimize_window();
    } catch {
      setNativeHost(false);
    }
  }

  async function toggleMaximizeWindow() {
    try {
      const next = await desktopWindowApi()?.toggle_maximize_window();
      if (typeof next === "boolean") setMaximized(next);
    } catch {
      setNativeHost(false);
    }
  }

  async function closeWindow() {
    try {
      await desktopWindowApi()?.close_window();
    } catch {
      setNativeHost(false);
    }
  }

  const statusCopy = definitionsOutOfDate !== null
    ? METRIC_DEFINITIONS_OUT_OF_DATE_TITLE
    : disconnected
      ? "Reconnecting · last receipt retained"
      : snapshot === null ? cleanupWarning ? "No active watch · model cleanup still unconfirmed" : "No active watch" : canonicalStatus(canonicalHead, snapshot);
  const progressTotal = canonicalHead?.latest_attempt?.progress_total ?? snapshot?.watch.progress_total ?? 0;
  const progressCompleted = canonicalHead?.latest_attempt?.progress_completed ?? snapshot?.watch.progress_completed ?? 0;

  return (
    <main
      aria-labelledby="model-ensemble-overlay-title"
      className={`model-ensemble-overlay${nativeHost ? " model-ensemble-overlay--native" : ""}`}
      data-host={nativeHost ? "native" : "browser"}
      data-viewport={smallViewport ? "small" : "regular"}
    >
      <div className="model-ensemble-overlay__chrome" aria-label="Prompt Enhancer window">
        <div
          className="model-ensemble-overlay__drag pywebview-drag-region"
          onDoubleClick={() => void toggleMaximizeWindow()}
        >
          <span aria-hidden="true" className="model-ensemble-overlay__brand-mark">P</span>
          <span className="model-ensemble-overlay__brand-copy">
            <strong>Prompt Enhancer</strong>
            <small>Live intelligence</small>
          </span>
        </div>
        {nativeHost ? (
          <div className="model-ensemble-overlay__window-controls" aria-label="Window controls">
            <button aria-label="Minimize window" onClick={() => void minimizeWindow()} type="button">
              <svg aria-hidden="true" viewBox="0 0 12 12"><path d="M2 8.5h8" /></svg>
            </button>
            <button
              aria-label={maximized ? "Restore window" : "Maximize window"}
              onClick={() => void toggleMaximizeWindow()}
              type="button"
            >
              {maximized
                ? <svg aria-hidden="true" viewBox="0 0 12 12"><path d="M4 2.5h5.5V8M2.5 4H8v5.5H2.5z" /></svg>
                : <svg aria-hidden="true" viewBox="0 0 12 12"><path d="M2.5 2.5h7v7h-7z" /></svg>}
            </button>
            <button aria-label="Close window" className="is-close" onClick={() => void closeWindow()} type="button">
              <svg aria-hidden="true" viewBox="0 0 12 12"><path d="m3 3 6 6m0-6L3 9" /></svg>
            </button>
          </div>
        ) : null}
      </div>
      <header className="model-ensemble-overlay__title">
        <div>
          <p className="eyebrow">Continuous local measurement</p>
          <h1 id="model-ensemble-overlay-title">Live metric watch</h1>
        </div>
        <span
          className={`model-ensemble-overlay__connection${disconnected && definitionsOutOfDate === null ? " is-stale" : ""}`}
          data-definitions={definitionsOutOfDate === null ? undefined : "out_of_date"}
          role="status"
        >
          {statusCopy}
        </span>
      </header>
      <section aria-label="Live watch scope" className="model-ensemble-overlay__scope">
        <div className="model-ensemble-overlay__scope-title">
          <div>
            <strong>Watch scope</strong>
            <span>{snapshot === null ? "Choose one indexed session" : `Newest ${snapshot.watch.max_messages} messages`}</span>
          </div>
          {snapshot !== null ? (
            <button onClick={() => setScopeExpanded((value) => !value)} type="button">
              {scopeExpanded ? "Done" : "Change"}
            </button>
          ) : null}
        </div>
        {snapshot !== null && !scopeExpanded ? (
          <p className="model-ensemble-overlay__scope-summary">
            {projects.find((project) => project.id === snapshot.watch.project_id)?.label ?? "Indexed project"}
            <span>·</span>
            {sessions.find((session) => session.session_id === snapshot.watch.session_id)?.session_display_name ?? "Selected session"}
          </p>
        ) : (
          <>
            <div className="model-ensemble-overlay__scope-grid">
              <label>
                <span>Project</span>
                <select
                  aria-label="Watch project"
                  disabled={catalogLoading || projects.length === 0}
                  onChange={(event) => {
                    const nextProject = event.target.value;
                    setProjectId(nextProject);
                    setSessionId(filteredSessions.find((session) => session.project_id === nextProject)?.session_id ?? "");
                  }}
                  value={projectId}
                >
                  {projects.length === 0 ? <option value="">No indexed projects</option> : null}
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.label}</option>)}
                </select>
              </label>
              <label>
                <span>Session</span>
                <select
                  aria-label="Watch session"
                  disabled={catalogLoading || projectSessions.length === 0}
                  onChange={(event) => setSessionId(event.target.value)}
                  value={sessionId}
                >
                  {projectSessions.length === 0 ? <option value="">No sessions in this filter</option> : null}
                  {activeSessionOutsideCatalog ? <option value={sessionId}>Current watched session · outside catalog page</option> : null}
                  {projectSessions.map((session) => (
                    <option key={session.session_id} value={session.session_id}>{sessionLabel(session)}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Session catalog date</span>
                <select
                  aria-label="Session catalog date"
                  onChange={(event) => setCatalogWindow(event.target.value as CatalogWindow)}
                  value={catalogWindow}
                >
                  <option value="all">All indexed dates</option>
                  <option value="7">Started in last 7 days</option>
                  <option value="30">Started in last 30 days</option>
                  <option value="90">Started in last 90 days</option>
                </select>
              </label>
              <label>
                <span>Analysis window</span>
                <select
                  aria-label="Analysis message window"
                  onChange={(event) => setMaxMessages(Number(event.target.value))}
                  value={maxMessages}
                >
                  {MODEL_ENSEMBLE_MESSAGE_WINDOWS.map((count) => <option key={count} value={count}>Newest {count} messages</option>)}
                </select>
              </label>
            </div>
            <p>
              The date control filters session choices. Analysis reads the newest {maxMessages} messages;
              exact within-session date cutoffs need complete provider timestamps and are not inferred.
            </p>
            {catalogError !== "" ? <p className="model-ensemble-overlay__scope-error" role="alert">{catalogError}</p> : null}
            {scopeError !== "" ? <p className="model-ensemble-overlay__scope-error" role="alert">{scopeError}</p> : null}
            <button
              className="model-ensemble-overlay__watch-button"
              disabled={watchChanging || sessionId === "" || projectId === ""}
              onClick={() => void changeWatch()}
              type="button"
            >
              {watchChanging
                ? "Updating…"
                : activeForSelection
                  ? "Stop this watch"
                  : activeForSession
                    ? "Apply message window"
                    : snapshot === null ? "Watch selected session" : "Switch live watch"}
            </button>
          </>
        )}
      </section>
      {definitionsOutOfDate !== null ? (
        <MetricDefinitionsOutOfDateAlert compact mismatch={definitionsOutOfDate} />
      ) : snapshot === null ? (
        <section className="model-ensemble__empty" role="status">
          {cleanupWarning ? MODEL_CLEANUP_RECOVERY : "No live watch is active. Choose a project, session, and message window above; reading starts only after you explicitly enable it."}
        </section>
      ) : (
        <>
          <section aria-labelledby="model-ensemble-overlay-progress-status" className="model-ensemble-overlay__progress">
            <div aria-live="polite" className="model-ensemble-overlay__progress-copy">
              <strong id="model-ensemble-overlay-progress-status">{canonicalStatus(canonicalHead, snapshot)}</strong>
              <span id="model-ensemble-overlay-progress-detail">{canonicalDetail(canonicalHead, snapshot)}</span>
            </div>
            <label className="model-ensemble-overlay__progress-bar">
              <span className="sr-only">Local pipeline progress</span>
              <progress
                aria-describedby="model-ensemble-overlay-progress-detail"
                aria-valuetext={`${progressCompleted} of ${progressTotal} pipeline steps`}
                max={Math.max(progressTotal, 1)}
                value={progressCompleted}
              />
            </label>
            <div className="model-ensemble-overlay__actions">
              <button
                aria-busy={pendingAction === "analyze"}
                className="model-ensemble-overlay__watch-button"
                disabled={!analyzeAvailable}
                onClick={() => void analyzeNow()}
                type="button"
              >
                {pendingAction === "analyze"
                  ? "Queueing analysis…"
                  : runningAttempt !== null
                    ? `Analysis running · ${runningAttempt.progress_completed}/${runningAttempt.progress_total}`
                    : snapshot.watch.state === "running"
                      ? `Analysis running · ${snapshot.watch.progress_completed}/${snapshot.watch.progress_total}`
                      : snapshot.watch.state === "queued"
                        ? "Analysis queued…"
                        : snapshot.watch.state === "failed" ? "Retry analysis" : "Analyze now"}
              </button>
              <button
                aria-busy={pendingAction === "cancel"}
                aria-describedby={runningAttempt !== null && !cancelArmed ? "model-ensemble-overlay-cancel-hint" : undefined}
                className="model-ensemble-overlay__watch-button model-ensemble-overlay__watch-button--secondary"
                disabled={!cancelAvailable}
                onClick={() => void cancelAnalysis()}
                title={runningAttempt !== null && !cancelArmed ? "Cancel becomes available a moment after the run starts" : undefined}
                type="button"
              >
                {pendingAction === "cancel" ? "Cancelling…" : "Cancel analysis"}
              </button>
              <span className="sr-only" id="model-ensemble-overlay-cancel-hint">Cancel becomes available a moment after the run starts.</span>
            </div>
          </section>
          {snapshot.latest_run === null ? (
            <p className="model-ensemble__empty">The first typed measurement and experimental model range have not completed yet.</p>
          ) : (
            <>
              {trajectoryDefinitionsMismatch !== null ? (
                <p className="model-ensemble-overlay__trajectory-error" data-history-definitions="out_of_date">
                  Snapshot history was published under other metric definitions and is withheld until this client is updated; the live receipt passed the compatibility gate and remains visible.
                </p>
              ) : trajectoryError ? (
                <p className="model-ensemble-overlay__trajectory-error">Trajectory history is temporarily unavailable; the last live receipt remains visible.</p>
              ) : null}
              {historicalRunRefused !== null ? (
                <p className="model-ensemble-overlay__trajectory-error" data-history-definitions="snapshot_out_of_date">
                  The exact sealed snapshot for this earlier point was published under other metric definitions, so only its compact state facts are shown and no guidance receipt is read from it; update this client to open that snapshot.
                </p>
              ) : null}
              {selectedRadarRun !== null ? (
                <MetricWorkspace
                  comparisonLabel="previous comparable publication"
                  comparisonRun={comparisonRadarRun}
                  history={visibleTrajectory === null ? undefined : {
                    points: trajectoryPoints,
                    headRunId: trajectoryHeadRunId ?? visibleTrajectory.head_run_id,
                    selectedRunId: selectedPoint?.run_id ?? snapshot.latest_run.run_id,
                    onSelectRun: selectTrajectoryRun,
                    error: trajectoryError,
                  }}
                  lensId={lensId}
                  mode="compact"
                  onLensChange={setLensId}
                  run={selectedRadarRun}
                  runId={selectedPoint?.run_id ?? snapshot.latest_run.run_id}
                  scopeLabel={`Newest ${selectedPoint?.max_messages ?? snapshot.watch.max_messages} messages`}
                  snapshotLabel={selectedPoint === null
                    ? "Current sealed receipt"
                    : selectedPoint.run_id === visibleTrajectory?.head_run_id
                      ? "Live published head"
                      : "Earlier published snapshot"}
                  stageRun={selectedPoint === null || selectedPoint.run_id === snapshot.latest_run.run_id
                    ? snapshot.latest_run
                    : historicalRun}
                  attemptStages={selectedPoint === null || selectedPoint.run_id === snapshot.latest_run.run_id
                    ? canonicalHead?.stages ?? []
                    : []}
                  evidenceEnabled={selectedPoint === null || selectedPoint.run_id === snapshot.latest_run.run_id}
                  evidenceSessionId={snapshot.watch.session_id}
                  transport={transport}
                />
              ) : null}
            </>
          )}
        </>
      )}
      {teamControlPlane === null ? null : <TeamContextDrawer lensId={lensId} port={teamControlPlane} />}
      {linkProjectId !== "" && linkSessionId !== "" ? <a
        className="model-ensemble-overlay__open"
        href={`/projects/${linkProjectId}/sessions/${linkSessionId}/metrics/${category}`}
        rel="noopener noreferrer"
        target="_blank"
      >
        Open selected session in dashboard
        <small>{nativeHost ? "opens in your browser" : "opens in a new tab"}</small>
      </a> : null}
      <footer>Typed local metrics + experimental model ranges · no text persisted · blocking work is not forcibly preempted</footer>
    </main>
  );
}
