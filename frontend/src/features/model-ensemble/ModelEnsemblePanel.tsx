import { useEffect, useId, useRef, useState } from "react";
import type {
  ModelEnsembleAttempt,
  ModelEnsembleRun,
  ModelEnsembleCanonicalHead,
  ModelEnsembleTrajectoryPage,
  ModelEnsembleWatchSnapshot,
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
  SessionTextAnalysisCapability,
} from "../../shared/api/contracts";
import { nextIdempotencyKey } from "../../shared/api/idempotency";
import { MetricDefinitionsOutOfDateError, type MetricDefinitionMismatch } from "../../shared/api/metricPublicationV2Contract";
import type { MetricCategory } from "../../shared/platform/platform";
import { promptTextCompatibilityBlocker } from "../provider-compatibility";
import type { ModelEnsembleLensId } from "./metricAxisModel";
import { MetricDefinitionsOutOfDateAlert } from "./MetricDefinitionsAlert";
import { MetricWorkspace } from "./MetricWorkspace";
import { DeclaredTaskProfilePanel } from "./DeclaredTaskProfilePanel";
import { MODEL_ENSEMBLE_DEFAULT_MAX_MESSAGES } from "./modelEnsembleConstants";
import { useTrajectorySelection } from "./useTrajectorySelection";
import {
  CANONICAL_POLL_IDLE_MS,
  CANONICAL_POLL_RETRY_MS,
  CANONICAL_POLL_WRONG_RUN_MS,
  TRAJECTORY_RETRY_LIMIT,
  TRAJECTORY_RETRY_MS,
  PollFailureTracker,
  PollCoordinator,
  canonicalHeadIdentity,
  canonicalHeadPollDelay,
  httpStatusOf as statusOf,
  isStaleWatchHead,
  watchSnapshotIdentity,
  watchSnapshotPollDelay,
} from "./canonicalPolling";
import { ErrorState } from "../../shared/ui/AsyncState";
import { MODEL_CLEANUP_RECOVERY, MODEL_CLEANUP_UNCONFIRMED, useModelCleanupWarning, watchPauseCopy } from "./modelEnsembleFailureCopy";

type ReceiptAuthority = "checking" | "verified" | "unknown";
type PendingMutation = "start" | "cancel" | "watch";

const TERMINAL_SOURCE_REASONS = new Set([
  "source_selection_limit",
  "source_provider_response_limit",
  "source_thread_structure_limit",
  "source_preview_window_limit",
  "source_resource_limit",
]);

function reasonOf(error: unknown): string | null {
  return typeof error === "object" && error !== null && "reasonCode" in error &&
    typeof error.reasonCode === "string" ? error.reasonCode : null;
}

function runErrorCopy(error: unknown): string {
  const reason = reasonOf(error);
  if (reason === MODEL_CLEANUP_UNCONFIRMED) return MODEL_CLEANUP_RECOVERY;
  if (reason === "redacted_content_consent_required") {
    return "Grant redacted-text access in Data sources before running the ensemble.";
  }
  if (reason === "session_not_in_safe_index") {
    return "This session is no longer in the safe index. Refresh Data sources first.";
  }
  if (reason === "provider_compatibility_blocked") {
    return "Installed Codex compatibility is not verified. Recheck it before running models.";
  }
  if (reason === "local_model_ensemble_execution_failed") {
    return "One or more pinned local models could not complete the serial pipeline. Verify the local model cache and runtime dependencies.";
  }
  if (reason === "model_ensemble_persistence_failed") {
    return "The content-free chunk and model receipts could not be stored locally.";
  }
  if (TERMINAL_SOURCE_REASONS.has(reason ?? "")) {
    return "The selected session is outside this adapter version's bounded local read. No shadow result was stored.";
  }
  if (reason === "source_timeout" || reason === "provider_unavailable") {
    return "The local Codex read timed out or became unavailable. Keep Codex open and retry once.";
  }
  if (statusOf(error) === 501) {
    return "The local probabilistic analysis is available only in the integrated local app.";
  }
  return "The local analysis did not complete. The error contains no session text.";
}

function blocker(
  capability: SessionTextAnalysisCapability | null,
  compatibility: ProviderCompatibilityStatus | null,
  compatibilityLoading: boolean,
): string | null {
  if (capability === null) return "Checking local redacted-text access.";
  if (!capability.available) {
    return capability.reason_code === "redacted_content_consent_required"
      ? "Grant redacted-text access in Data sources first."
      : "This installation cannot read the selected session through the bounded adapter.";
  }
  if (compatibilityLoading) return "Checking installed Codex compatibility.";
  return promptTextCompatibilityBlocker(compatibility) === null
    ? null
    : "Recheck installed Codex compatibility before running the ensemble.";
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function terminalAttemptStatus(
  attempt: ModelEnsembleAttempt | null | undefined,
  run: ModelEnsembleRun | null,
): string | null {
  if (attempt === null || attempt === undefined || attempt.state === "running") return null;
  if (attempt.error_code === MODEL_CLEANUP_UNCONFIRMED) return MODEL_CLEANUP_RECOVERY;
  const retained = run === null
    ? "No new sealed snapshot is available."
    : "The last sealed snapshot remains visible.";
  if (attempt.state === "failed") return `Local analysis failed. ${retained}`;
  if (attempt.state === "cancelled") return `Local analysis was cancelled. ${retained}`;
  if (attempt.state === "partial") {
    const warnings = `${attempt.warning_count} warning${attempt.warning_count === 1 ? "" : "s"}`;
    return `Local analysis completed with ${warnings}. ${retained}`;
  }
  return run === null
    ? "Local analysis completed, but no sealed snapshot is available."
    : `Stored local analysis completed ${formatTimestamp(run.completed_at)}.`;
}

export function ModelEnsemblePanel({
  projectId,
  sessionId,
  category,
  transport,
  analysisCapability,
  providerCompatibility,
  compatibilityLoading = false,
}: {
  projectId: string;
  sessionId: string;
  category: MetricCategory;
  transport: PromptEnhancerTransport;
  analysisCapability: SessionTextAnalysisCapability | null;
  providerCompatibility: ProviderCompatibilityStatus | null;
  compatibilityLoading?: boolean;
}) {
  const [run, setRun] = useState<ModelEnsembleRun | null>(null);
  const [receiptAuthority, setReceiptAuthority] = useState<ReceiptAuthority>("checking");
  const [pendingMutation, setPendingMutation] = useState<PendingMutation | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [disconnected, setDisconnected] = useState(false);
  const [legacyLoadRevision, setLegacyLoadRevision] = useState(0);
  /** Compatibility-gate refusal: clears every retained value; never rendered as a load error. */
  const [definitionsOutOfDate, setDefinitionsOutOfDate] = useState<MetricDefinitionMismatch | null>(null);
  const [watch, setWatch] = useState<ModelEnsembleWatchSnapshot | null>(null);
  const [canonicalHead, setCanonicalHead] = useState<ModelEnsembleCanonicalHead | null>(null);
  const [trajectory, setTrajectory] = useState<ModelEnsembleTrajectoryPage | null>(null);
  const [trajectoryError, setTrajectoryError] = useState(false);
  const [trajectoryReadRevision, setTrajectoryReadRevision] = useState(0);
  /**
   * The history page (not the live head) was published under other definitions.
   * Scoped to the history so a compatible live receipt is neither hidden nor
   * flashed: the head poll owns `definitionsOutOfDate`, this owns the drawer.
   */
  const [trajectoryDefinitionsMismatch, setTrajectoryDefinitionsMismatch] = useState<MetricDefinitionMismatch | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [lensId, setLensId] = useState<ModelEnsembleLensId>(
    category === "prompt-quality" ? "task-framing" : "reasoning-trace",
  );
  const controllerRef = useRef<AbortController | null>(null);
  const pendingMutationRef = useRef<PendingMutation | null>(null);
  const contextEpochRef = useRef(0);
  const receiptAuthorityRef = useRef<ReceiptAuthority>("checking");
  const legacyWatchRevisionRef = useRef(0);
  const runRef = useRef<ModelEnsembleRun | null>(null);
  const watchRef = useRef<ModelEnsembleWatchSnapshot | null>(null);
  const canonicalHeadRef = useRef<ModelEnsembleCanonicalHead | null>(null);
  const coordinatorRef = useRef<PollCoordinator | null>(null);
  const followingLive = useRef(true);
  const blocked = blocker(analysisCapability, providerCompatibility, compatibilityLoading);
  const supportsCanonicalSnapshots = transport.getSessionModelEnsembleCanonicalHead !== undefined
    && transport.getModelEnsembleSnapshot !== undefined;
  const titleId = useId();
  const statusId = useId();
  const cleanupWarning = useModelCleanupWarning(watch?.watch, error === MODEL_CLEANUP_RECOVERY);

  useEffect(() => {
    contextEpochRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    pendingMutationRef.current = null;
    setPendingMutation(null);
    legacyWatchRevisionRef.current = 0;
    return () => {
      contextEpochRef.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
      pendingMutationRef.current = null;
    };
  }, [projectId, sessionId, transport]);

  useEffect(() => {
    const controller = new AbortController();
    const legacyWatchRevision = legacyWatchRevisionRef.current;
    receiptAuthorityRef.current = "checking";
    setReceiptAuthority("checking");
    setError("");
    setLoadError("");
    setNotice("");
    setDisconnected(false);
    setRun(null);
    runRef.current = null;
    setDefinitionsOutOfDate(null);
    if (supportsCanonicalSnapshots) {
      return () => controller.abort();
    }
    transport.getLatestModelEnsemble(sessionId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        if (legacyWatchRevisionRef.current !== legacyWatchRevision) return;
        const exactHead = canonicalHeadRef.current;
        if (
          exactHead?.watch.session_id === sessionId
          && exactHead.head_run_id !== value.run_id
        ) return;
        receiptAuthorityRef.current = "verified";
        setReceiptAuthority("verified");
        setLoadError("");
        setDefinitionsOutOfDate(null);
        runRef.current = value;
        setRun(value);
      })
      .catch((loadError: unknown) => {
        if (controller.signal.aborted) return;
        if (legacyWatchRevisionRef.current !== legacyWatchRevision) return;
        if (loadError instanceof MetricDefinitionsOutOfDateError) {
          receiptAuthorityRef.current = "verified";
          setReceiptAuthority("verified");
          setDefinitionsOutOfDate(loadError.mismatch);
          runRef.current = null;
          setRun(null);
          return;
        }
        receiptAuthorityRef.current = statusOf(loadError) === 404 ? "verified" : "unknown";
        setReceiptAuthority(receiptAuthorityRef.current);
        if (statusOf(loadError) !== 404) {
          setLoadError("Stored local-analysis receipts could not be checked. Their availability remains unknown.");
        }
      });
    return () => controller.abort();
  }, [legacyLoadRevision, sessionId, supportsCanonicalSnapshots, transport]);

  const trajectoryWatchId = watch?.watch.session_id === sessionId
    && watch.watch.state !== "disabled"
    ? watch.watch.watch_id
    : null;
  const trajectoryHeadRunId = run?.run_id ?? null;

  useEffect(() => {
    if (trajectoryWatchId === null || trajectoryHeadRunId === null || transport.getModelEnsembleTrajectory === undefined) {
      setTrajectory(null);
      setTrajectoryError(false);
      setTrajectoryDefinitionsMismatch(null);
      setSelectedRunId(null);
      followingLive.current = true;
      return;
    }
    if (followingLive.current) setSelectedRunId(trajectoryHeadRunId);
    const controller = new AbortController();
    let retryTimer: number | undefined;
    let attempts = 0;
    const fetchTrajectory = transport.getModelEnsembleTrajectory;
    const load = () => {
      attempts += 1;
      fetchTrajectory(trajectoryWatchId, 24, undefined, controller.signal)
        .then((page) => {
          if (controller.signal.aborted) return;
          if (page.watch_id !== trajectoryWatchId) throw new Error("trajectory-owner-mismatch");
          if (page.head_run_id !== trajectoryHeadRunId) {
            // Publication race between the exact head and the trajectory index:
            // keep the previously loaded history and retry a bounded number of times.
            setTrajectoryError(true);
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
            if (current !== null && page.points.some((point) => point.run_id === current)) return current;
            followingLive.current = true;
            return page.head_run_id;
          });
        })
        .catch((trajectoryFailure: unknown) => {
          if (controller.signal.aborted) return;
          if (trajectoryFailure instanceof MetricDefinitionsOutOfDateError) {
            // History published under other definitions: withhold every history
            // point (no compact values, no comparison) and say why. The live head
            // stays governed by its own gate, so nothing compatible is hidden.
            setTrajectoryDefinitionsMismatch(trajectoryFailure.mismatch);
            setTrajectory(null);
            setSelectedRunId(trajectoryHeadRunId);
            followingLive.current = true;
            setTrajectoryError(true);
            return;
          }
          setTrajectoryError(true);
          // Transient read failure: reuse the same bounded retry budget as the
          // head-mismatch publication race; once exhausted the drawer offers a
          // manual read-only retry instead of retrying forever.
          if (attempts < TRAJECTORY_RETRY_LIMIT) {
            retryTimer = window.setTimeout(() => {
              retryTimer = undefined;
              if (!controller.signal.aborted) load();
            }, TRAJECTORY_RETRY_MS);
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [trajectoryHeadRunId, trajectoryReadRevision, trajectoryWatchId, transport]);

  useEffect(() => { runRef.current = run; }, [run]);
  useEffect(() => { watchRef.current = watch; }, [watch]);
  useEffect(() => { canonicalHeadRef.current = canonicalHead; }, [canonicalHead]);

  /**
   * Applies head, watch, and run together so they can never disagree mid-render.
   * `nextRun === undefined` leaves the displayed run untouched (legacy watch
   * receipts for another session must not clear this session's stored run).
   */
  function applyCanonical(
    head: ModelEnsembleCanonicalHead | null,
    nextWatch: ModelEnsembleWatchSnapshot | null,
    nextRun: ModelEnsembleRun | null | undefined,
  ) {
    canonicalHeadRef.current = head;
    watchRef.current = nextWatch;
    setCanonicalHead(head);
    setWatch(nextWatch);
    if (nextRun !== undefined) {
      runRef.current = nextRun;
      setRun(nextRun);
    }
  }

  useEffect(() => {
    setLensId(category === "prompt-quality" ? "task-framing" : "reasoning-trace");
  }, [category]);

  useEffect(() => {
    if (transport.getSessionModelEnsembleCanonicalHead === undefined && transport.getActiveModelEnsembleWatch === undefined) return;
    const failures = new PollFailureTracker();
    const healthy = (authority: ReceiptAuthority = "verified") => {
      failures.reset();
      receiptAuthorityRef.current = authority;
      setReceiptAuthority(authority);
      setDisconnected(false);
      setLoadError("");
      // Poll recovery clears only polling notices. Errors from explicit
      // start/cancel/watch commands stay visible until the next explicit
      // command clears its own error.
      setNotice("");
    };
    const degraded = (delay: number) => {
      if (failures.recordFailure()) {
        setDisconnected(true);
        if (runRef.current === null) {
          receiptAuthorityRef.current = "unknown";
          setReceiptAuthority("unknown");
        }
      }
      coordinator.schedule(delay);
    };
    const coordinator = new PollCoordinator(async (ticket) => {
      let head: ModelEnsembleCanonicalHead | null = null;
      let legacy: ModelEnsembleWatchSnapshot | null = null;
      try {
        if (supportsCanonicalSnapshots) {
          head = await transport.getSessionModelEnsembleCanonicalHead!(sessionId, ticket.signal);
        } else {
          legacy = await transport.getActiveModelEnsembleWatch!(ticket.signal);
        }
      } catch (watchError) {
        if (!ticket.isCurrent()) return;
        if (watchError instanceof MetricDefinitionsOutOfDateError) {
          // Legacy watch snapshot embeds the run: a definitions mismatch clears
          // every retained value and is shown as a client-update state.
          legacyWatchRevisionRef.current += 1;
          setDefinitionsOutOfDate(watchError.mismatch);
          applyCanonical(null, null, null);
          healthy();
          coordinator.schedule(CANONICAL_POLL_IDLE_MS);
          return;
        }
        if (statusOf(watchError) === 404) {
          // Definitive: no durable watch or head for this session.
          // A missing *legacy watch* says nothing about the independently
          // stored latest run.  Pass `undefined` so an in-flight initial run
          // load cannot be overwritten through a stale ref.  The canonical
          // v2 route is authoritative for both head and run, so its 404 does
          // intentionally clear the displayed run — and with it any refused
          // publication: there is nothing left to be out of date about.
          if (supportsCanonicalSnapshots) setDefinitionsOutOfDate(null);
          applyCanonical(null, null, supportsCanonicalSnapshots ? null : undefined);
          if (supportsCanonicalSnapshots) healthy();
          else {
            failures.reset();
            setDisconnected(false);
          }
          coordinator.schedule(CANONICAL_POLL_IDLE_MS);
          return;
        }
        // Transport failure: keep the last complete snapshot and retry sooner.
        degraded(CANONICAL_POLL_RETRY_MS);
        return;
      }
      if (!ticket.isCurrent()) return;
      if (head !== null) {
        if (head.watch.session_id !== sessionId) {
          // Never admit another session's head; keep the current view and retry.
          degraded(CANONICAL_POLL_RETRY_MS);
          return;
        }
        if (isStaleWatchHead(
          canonicalHeadRef.current === null ? null : canonicalHeadIdentity(canonicalHeadRef.current),
          canonicalHeadIdentity(head),
        )) {
          healthy();
          coordinator.schedule(canonicalHeadPollDelay(canonicalHeadRef.current!));
          return;
        }
        let latestRun = runRef.current;
        if (head.head_run_id === null) {
          latestRun = null;
        } else if (latestRun?.run_id !== head.head_run_id) {
          try {
            latestRun = await transport.getModelEnsembleSnapshot!(head.head_run_id, ticket.signal);
          } catch (snapshotError) {
            // The immutable snapshot is not readable (including 404): retain the
            // last complete run rather than presenting a head without it.
            if (!ticket.isCurrent()) return;
            if (snapshotError instanceof MetricDefinitionsOutOfDateError) {
              // Client definitions are out of date for this exact head: clear
              // every retained value and guidance; keep polling at idle cadence.
              setDefinitionsOutOfDate(snapshotError.mismatch);
              applyCanonical(head, { watch: head.watch, latest_run: null }, null);
              healthy();
              coordinator.schedule(CANONICAL_POLL_IDLE_MS);
              return;
            }
            degraded(CANONICAL_POLL_RETRY_MS);
            return;
          }
          if (!ticket.isCurrent()) return;
          if (latestRun.run_id !== head.head_run_id) {
            // Parser-valid snapshot for the wrong run: keep polling instead of stopping.
            degraded(CANONICAL_POLL_WRONG_RUN_MS);
            return;
          }
        }
        setDefinitionsOutOfDate(null);
        applyCanonical(head, { watch: head.watch, latest_run: latestRun }, latestRun);
        healthy();
        coordinator.schedule(canonicalHeadPollDelay(head));
        return;
      }
      if (legacy !== null) {
        if (isStaleWatchHead(
          watchRef.current === null ? null : watchSnapshotIdentity(watchRef.current),
          watchSnapshotIdentity(legacy),
        )) {
          healthy(receiptAuthorityRef.current);
          coordinator.schedule(watchSnapshotPollDelay(watchRef.current!));
          return;
        }
        if (legacy.watch.session_id !== sessionId) {
          degraded(CANONICAL_POLL_RETRY_MS);
          return;
        }
        legacyWatchRevisionRef.current += 1;
        setDefinitionsOutOfDate(null);
        applyCanonical(null, legacy, legacy.latest_run);
        healthy();
        coordinator.schedule(watchSnapshotPollDelay(legacy));
      }
    });
    coordinatorRef.current = coordinator;
    coordinator.pollNow();
    return () => {
      coordinator.stop();
      if (coordinatorRef.current === coordinator) coordinatorRef.current = null;
    };
  }, [sessionId, supportsCanonicalSnapshots, transport]);

  /**
   * A command result (start, enqueue, cancel, watch change) that the
   * compatibility gate refused. The refused publication is the newest truth
   * for this session, so the previously displayed run must not stay visible
   * beside a generic error: clear it and show the update-client state. A later
   * compatible poll or command clears the state again.
   */
  function refuseCommandDefinitions(mismatch: MetricDefinitionMismatch) {
    legacyWatchRevisionRef.current += 1;
    receiptAuthorityRef.current = "verified";
    setReceiptAuthority("verified");
    setDefinitionsOutOfDate(mismatch);
    runRef.current = null;
    setRun(null);
  }

  function beginMutation(kind: PendingMutation): { controller: AbortController; epoch: number } | null {
    if (pendingMutationRef.current !== null) return null;
    const controller = new AbortController();
    pendingMutationRef.current = kind;
    controllerRef.current = controller;
    setPendingMutation(kind);
    setError("");
    setNotice("");
    return { controller, epoch: contextEpochRef.current };
  }

  function mutationIsCurrent(mutation: { controller: AbortController; epoch: number }): boolean {
    return !mutation.controller.signal.aborted
      && mutation.epoch === contextEpochRef.current
      && controllerRef.current === mutation.controller;
  }

  function finishMutation(kind: PendingMutation, controller: AbortController) {
    if (controllerRef.current === controller) controllerRef.current = null;
    if (pendingMutationRef.current === kind) {
      pendingMutationRef.current = null;
      setPendingMutation(null);
    }
  }

  /**
   * Resolves the exact sealed run for a command's canonical head, refusing any
   * head or snapshot that does not belong to this session or head run id.
   */
  async function resolveCommandRun(
    head: ModelEnsembleCanonicalHead,
    signal?: AbortSignal,
  ): Promise<ModelEnsembleRun | null> {
    if (head.watch.session_id !== sessionId) throw new Error("durable_watch_identity_mismatch");
    if (head.head_run_id === null) return null;
    const current = runRef.current;
    if (current?.run_id === head.head_run_id) return current;
    if (transport.getModelEnsembleSnapshot === undefined) throw new Error("durable_snapshot_unavailable");
    const exactRun = await transport.getModelEnsembleSnapshot(head.head_run_id, signal);
    if (exactRun.run_id !== head.head_run_id) throw new Error("durable_snapshot_identity_mismatch");
    return exactRun;
  }

  async function start() {
    if (
      pendingMutationRef.current !== null
      || blocked !== null
      || definitionsOutOfDate !== null
      || durableAttemptRunning
      || watchQueued
      || legacyWatchBusy
    ) return;
    const mutation = beginMutation("start");
    if (mutation === null) return;
    const { controller } = mutation;
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      if (transport.enqueueModelEnsembleAnalysis !== undefined) {
        let activeWatch = watchRef.current;
        if (
          activeWatch === null
          || activeWatch.watch.session_id !== sessionId
          || activeWatch.watch.state === "disabled"
        ) {
          if (transport.enableModelEnsembleWatch === undefined) throw new Error("durable_watch_unavailable");
          activeWatch = await transport.enableModelEnsembleWatch(sessionId, {
            project_id: projectId,
            max_messages: MODEL_ENSEMBLE_DEFAULT_MAX_MESSAGES,
            confirmation: "continuously_analyze_selected_redacted_session",
          }, controller.signal);
          if (!mutationIsCurrent(mutation)) return;
          legacyWatchRevisionRef.current += 1;
          applyCanonical(null, activeWatch, activeWatch.latest_run);
        }
        const head = await transport.enqueueModelEnsembleAnalysis(activeWatch.watch.watch_id, controller.signal);
        if (!mutationIsCurrent(mutation)) return;
        const exactRun = await resolveCommandRun(head, controller.signal);
        if (!mutationIsCurrent(mutation)) return;
        setDefinitionsOutOfDate(null);
        applyCanonical(head, { watch: head.watch, latest_run: exactRun }, exactRun);
        receiptAuthorityRef.current = "verified";
        setReceiptAuthority("verified");
        setDisconnected(false);
        setLoadError("");
        followingLive.current = true;
        resumeDelay = canonicalHeadPollDelay(head);
      } else {
        const outcome = await transport.startModelEnsemble(
          sessionId,
          { confirmation: "run_local_metric_cascade_on_selected_redacted_text" },
          nextIdempotencyKey("model-ensemble"),
          controller.signal,
        );
        if (mutationIsCurrent(mutation)) {
          legacyWatchRevisionRef.current += 1;
          setDefinitionsOutOfDate(null);
          runRef.current = outcome.run;
          setRun(outcome.run);
          receiptAuthorityRef.current = "verified";
          setReceiptAuthority("verified");
          setDisconnected(false);
          setLoadError("");
        }
      }
    } catch (runError) {
      if (!mutationIsCurrent(mutation)) return;
      if (runError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(runError.mismatch);
        return;
      }
      setError(runErrorCopy(runError));
    } finally {
      finishMutation("start", controller);
      coordinator?.endCommand(resumeDelay);
    }
  }

  function cancelWait() {
    if (pendingMutationRef.current !== "start") return;
    const controller = controllerRef.current;
    controller?.abort();
    if (controller !== null) finishMutation("start", controller);
    setNotice("Stopped waiting for the queue response. Durable work may already have started; checking the authoritative local status.");
  }

  async function cancelAnalysis() {
    if (
      pendingMutationRef.current !== null
      || canonicalHead?.latest_attempt?.state !== "running"
      || transport.cancelModelEnsembleAnalysis === undefined
    ) return;
    const mutation = beginMutation("cancel");
    if (mutation === null) return;
    const { controller } = mutation;
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      const head = await transport.cancelModelEnsembleAnalysis(canonicalHead.watch.watch_id, controller.signal);
      if (!mutationIsCurrent(mutation)) return;
      const exactRun = await resolveCommandRun(head, controller.signal);
      if (!mutationIsCurrent(mutation)) return;
      legacyWatchRevisionRef.current += 1;
      setDefinitionsOutOfDate(null);
      applyCanonical(head, { watch: head.watch, latest_run: exactRun }, exactRun);
      receiptAuthorityRef.current = "verified";
      setReceiptAuthority("verified");
      setDisconnected(false);
      resumeDelay = canonicalHeadPollDelay(head);
    } catch (cancelError) {
      if (!mutationIsCurrent(mutation)) return;
      if (cancelError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(cancelError.mismatch);
      } else {
        setError("Cancellation could not be confirmed. The latest sealed snapshot remains visible.");
      }
    } finally {
      finishMutation("cancel", controller);
      coordinator?.endCommand(resumeDelay);
    }
  }

  async function toggleWatch() {
    const currentWatch = watchRef.current;
    const currentForSession = currentWatch?.watch.session_id === sessionId && currentWatch.watch.state !== "disabled";
    if (
      pendingMutationRef.current !== null
      || (!currentForSession && (blocked !== null || definitionsOutOfDate !== null))
    ) return;
    const mutation = beginMutation("watch");
    if (mutation === null) return;
    const { controller } = mutation;
    const coordinator = coordinatorRef.current;
    coordinator?.beginCommand();
    let resumeDelay: number | undefined;
    try {
      const snapshot = currentForSession
        ? await transport.disableModelEnsembleWatch?.(currentWatch.watch.watch_id, controller.signal)
        : await transport.enableModelEnsembleWatch?.(sessionId, {
            project_id: projectId,
            max_messages: MODEL_ENSEMBLE_DEFAULT_MAX_MESSAGES,
            confirmation: "continuously_analyze_selected_redacted_session",
          }, controller.signal);
      if (!mutationIsCurrent(mutation)) return;
      if (snapshot !== undefined) {
        const disabled = snapshot.watch.state === "disabled";
        legacyWatchRevisionRef.current += 1;
        applyCanonical(null, disabled ? null : snapshot, snapshot.latest_run);
        receiptAuthorityRef.current = "verified";
        setReceiptAuthority("verified");
        setDisconnected(false);
        setLoadError("");
        resumeDelay = disabled ? CANONICAL_POLL_IDLE_MS : watchSnapshotPollDelay(snapshot);
      } else {
        setError("Continuous local analysis is available only in the integrated desktop app.");
      }
    } catch (watchChangeError) {
      if (!mutationIsCurrent(mutation)) return;
      if (watchChangeError instanceof MetricDefinitionsOutOfDateError) {
        refuseCommandDefinitions(watchChangeError.mismatch);
      } else {
        setError("The continuous local watch could not be changed. No session text was retained.");
      }
    } finally {
      finishMutation("watch", controller);
      coordinator?.endCommand(resumeDelay);
    }
  }

  const durableAttemptRunning = canonicalHead?.watch.session_id === sessionId
    && canonicalHead.latest_attempt?.state === "running";
  const currentAttempt = canonicalHead?.watch.session_id === sessionId
    ? canonicalHead.latest_attempt
    : null;
  const watchQueued = watch?.watch.session_id === sessionId
    && watch.watch.state === "queued"
    && !durableAttemptRunning;
  const legacyWatchBusy = canonicalHead === null
    && watch?.watch.session_id === sessionId
    && watch.watch.state === "running";
  const watchActiveForSession = watch?.watch.session_id === sessionId
    && watch.watch.state !== "disabled";
  const visibleTrajectory = trajectory?.watch_id === trajectoryWatchId
    && trajectory.head_run_id === trajectoryHeadRunId
    ? trajectory
    : null;
  const trajectoryPoints = visibleTrajectory?.points ?? [];
  const {
    selectedPoint,
    historicalRun,
    historicalRunRefused,
    selectedExactRun,
    selectedRadarRun,
    comparisonRadarRun,
  } = useTrajectorySelection({ transport, points: trajectoryPoints, selectedRunId, headRun: run });
  const profileUsesHistoricalSelection = selectedPoint !== null && selectedPoint.run_id !== run?.run_id;
  const policyBlocker = definitionsOutOfDate !== null
    ? "Update this client before starting a new analysis or continuous watch. Existing local work can still be stopped."
    : blocked;
  const terminalStatus = terminalAttemptStatus(currentAttempt, run);
  const pauseStatus = cleanupWarning ? MODEL_CLEANUP_RECOVERY
    : watch?.watch.session_id === sessionId ? watchPauseCopy(watch.watch) : null;
  const runPaused = pauseStatus !== null || error === MODEL_CLEANUP_RECOVERY || currentAttempt?.error_code === MODEL_CLEANUP_UNCONFIRMED;
  const statusCopy = definitionsOutOfDate !== null
    ? pendingMutation === "cancel"
      ? "Cancelling local analysis. Metric values remain withheld until this client is updated."
      : pendingMutation === "watch"
        ? "Stopping continuous updates. Metric values remain withheld until this client is updated."
        : "New analysis and watch actions are paused; update this client. Existing local work can still be stopped."
    : pendingMutation === "cancel"
      ? "Cancelling the durable local analysis. The last sealed snapshot remains visible."
      : pendingMutation === "watch"
        ? watchActiveForSession
          ? "Stopping continuous local updates and the current continuous attempt."
          : "Starting continuous local updates for this session."
        : pendingMutation === "start"
          ? transport.enqueueModelEnsembleAnalysis === undefined
            ? "Running the local factor pipeline one child at a time. Stopping only ends this browser wait."
            : "Waiting for the durable queue response. Local work may start before this response returns."
          : notice !== ""
            ? notice
            : disconnected
              ? run === null
                ? "Stored receipt availability is temporarily unknown while the local connection retries."
                : "Live analysis updates are reconnecting. The last sealed snapshot remains visible."
              : receiptAuthority === "checking"
                ? "Checking for stored content-free local-analysis receipts."
                : receiptAuthority === "unknown"
                  ? "Stored receipt availability is unknown. No absence is inferred."
                  : blocked !== null
                    ? blocked
                    : durableAttemptRunning
                      ? `Durable local analysis is running · ${currentAttempt!.progress_completed}/${currentAttempt!.progress_total} pipeline steps. The last sealed snapshot remains visible.`
                      : watchQueued
                        ? "Analysis is queued for the serial local model lane. The last sealed snapshot remains visible."
                        : legacyWatchBusy
                          ? `The local watch is ${watch!.watch.state}. The last sealed snapshot remains visible while canonical stage status loads.`
                          : pauseStatus ?? terminalStatus ?? (run
                            ? `Stored local analysis completed ${formatTimestamp(run.completed_at)}.`
                            : "No measured + predictive analysis is stored for this session yet.");

  function selectTrajectoryRun(runId: string) {
    followingLive.current = runId === trajectoryHeadRunId;
    setSelectedRunId(runId);
  }

  /** Manual read-only history retry once bounded automatic retries are spent. */
  function retryTrajectoryRead() {
    setTrajectoryReadRevision((revision) => revision + 1);
  }

  return (
    <section aria-busy={receiptAuthority === "checking"} aria-labelledby={titleId} className="model-ensemble">
      <header className="model-ensemble__header">
        <div>
          <p className="eyebrow">Typed evidence + experimental model ranges</p>
          <h2 id={titleId}>Measure the analyzed window, then estimate every eligible axis locally</h2>
          <p>
            Typed evidence forms the solid radar. A gated multilingual factor lane
            runs pinned small models one at a time to produce a separate experimental
            range. Each child exits before the next model can use RAM or GPU memory.
          </p>
        </div>
        {durableAttemptRunning ? (
          <button
            aria-busy={pendingMutation === "cancel"}
            className="button button--secondary"
            disabled={pendingMutation !== null}
            onClick={() => void cancelAnalysis()}
            type="button"
          >
            {pendingMutation === "cancel" ? "Cancelling…" : "Cancel analysis"}
          </button>
        ) : watchQueued ? (
          <span className="model-ensemble__action-status">Analysis queued</span>
        ) : legacyWatchBusy ? (
          <span className="model-ensemble__action-status">Analysis active</span>
        ) : pendingMutation === "start" ? (
          <button className="button button--secondary" onClick={cancelWait} type="button">
            {transport.enqueueModelEnsembleAnalysis === undefined
              ? "Stop browser wait"
              : "Stop waiting for queue response"}
          </button>
        ) : (
          <button
            aria-describedby={policyBlocker === null ? undefined : statusId}
            aria-disabled={policyBlocker === null ? undefined : true}
            className="button button--primary"
            disabled={pendingMutation !== null}
            onClick={() => void start()}
            type="button"
          >
            {currentAttempt?.state === "failed" || (watch?.watch.session_id === sessionId && watch.watch.state === "failed") ? "Retry analysis" : "Analyze metric ranges"}
          </button>
        )}
      </header>
      <div className="model-ensemble__boundary" role="note">
          <strong>Solid measurements and model ranges stay separate</strong>
          <span>
          Versioned contracts supply evidence-backed numerators and denominators.
          Separate model markers are explicitly experimental until a metric passes
          calibration. They never erase evidence, turn missing states into zero, or
          treat prose as proof of an objective outcome.
        </span>
      </div>
      {transport.getDeclaredTaskProfile !== undefined && transport.saveDeclaredTaskProfile !== undefined && (
        <DeclaredTaskProfilePanel
          sealedMetricProfileBinding={selectedExactRun?.metric_profile_binding ?? null}
          sealedMetricProjectionVersion={selectedExactRun?.metric_publication_v2?.projection_version ?? null}
          sealedRunContext={profileUsesHistoricalSelection ? "historical_selection" : "latest_head"}
          sealedRunId={profileUsesHistoricalSelection ? selectedPoint.run_id : run?.run_id ?? null}
          sessionId={sessionId}
          transport={transport}
        />
      )}
      <div className="model-ensemble__watch">
        <div>
          <strong>Continuous local updates</strong>
          <span>
            {watch?.watch.session_id === sessionId
              ? pauseStatus !== null
                ? "paused · automatic retries disabled"
                : watch.watch.state === "queued"
                ? "queued · waiting for the local model lane"
                : canonicalHead?.latest_attempt === null || canonicalHead?.latest_attempt === undefined
                ? `${watch.watch.state} · local pipeline ${watch.watch.progress_completed}/${watch.watch.progress_total}`
                : `${canonicalHead.latest_attempt.state} · ${canonicalHead.latest_attempt.progress_completed}/${canonicalHead.latest_attempt.progress_total} pipeline steps`
              : "Off for this session. One selected session can use the serial GPU/CPU lane."}
          </span>
        </div>
        <button
          aria-busy={pendingMutation === "watch"}
          aria-describedby={!watchActiveForSession && policyBlocker !== null ? statusId : undefined}
          aria-disabled={!watchActiveForSession && policyBlocker !== null ? true : undefined}
          className="button button--secondary"
          disabled={pendingMutation !== null}
          onClick={() => void toggleWatch()}
          type="button"
        >
          {pendingMutation === "watch"
            ? watchActiveForSession ? "Stopping…" : "Starting…"
            : watchActiveForSession
              ? "Stop continuous updates"
              : "Watch this session"}
        </button>
      </div>
      <p
        aria-live={definitionsOutOfDate === null ? "polite" : "off"}
        className="model-ensemble__status"
        id={statusId}
        role="status"
      >
        {statusCopy}
      </p>
      {loadError !== "" && (
        <ErrorState message={loadError} onRetry={() => setLegacyLoadRevision((revision) => revision + 1)} />
      )}
      {error && <p className="model-ensemble__error" role="alert">{error}</p>}
      {receiptAuthority === "checking" ? (
        <p aria-hidden="true" className="model-ensemble__empty">Loading stored content-free receipts…</p>
      ) : definitionsOutOfDate !== null ? (
        <MetricDefinitionsOutOfDateAlert mismatch={definitionsOutOfDate} />
      ) : selectedRadarRun ? (
        <>
          {selectedPoint === null && run?.source_coverage_state === "incomplete_source" && (
            <p className="model-ensemble__error" role="note">
              The adapter could not prove the selected source window complete.
              This shadow shape reflects retained content only and is not a
              complete-session judgment.
            </p>
          )}
          {trajectoryDefinitionsMismatch !== null && (
            <p className="model-ensemble__error" data-history-definitions="out_of_date" role="note">
              Snapshot history was published under other metric definitions and is withheld
              until this client is updated; no earlier point is shown or compared. The current
              sealed receipt passed the compatibility gate and remains visible.
            </p>
          )}
          {historicalRunRefused !== null && (
            <p className="model-ensemble__error" data-history-definitions="snapshot_out_of_date" role="note">
              The exact sealed snapshot for this earlier point was published under other metric
              definitions, so only its compact state facts are shown and no guidance receipt is
              read from it; update this client to open that snapshot.
            </p>
          )}
          <MetricWorkspace
            comparisonLabel="previous comparable publication"
            comparisonRun={comparisonRadarRun}
            history={visibleTrajectory !== null ? {
              points: trajectoryPoints,
              headRunId: trajectoryHeadRunId ?? visibleTrajectory.head_run_id,
              selectedRunId: selectedPoint?.run_id ?? run?.run_id ?? null,
              onSelectRun: selectTrajectoryRun,
              error: trajectoryError,
              onRetry: trajectoryError ? retryTrajectoryRead : undefined,
            } : trajectoryError && trajectoryDefinitionsMismatch === null ? {
              // A failed read with no loaded page still renders as explicit
              // delayed history, never as "not exposed".
              points: [],
              headRunId: trajectoryHeadRunId,
              selectedRunId: run?.run_id ?? null,
              onSelectRun: selectTrajectoryRun,
              error: true,
              onRetry: retryTrajectoryRead,
            } : undefined}
            lensId={lensId}
            mode="full"
            onLensChange={setLensId}
            run={selectedRadarRun}
            runId={selectedPoint?.run_id ?? run?.run_id ?? ""}
            scopeLabel={selectedPoint !== null
              ? `Newest ${selectedPoint.max_messages} messages`
              : watch?.watch.session_id === sessionId
              ? `Newest ${watch.watch.max_messages} messages`
              : "Scope not exposed"}
            snapshotLabel={selectedPoint === null
              ? run?.source_coverage_state === "complete_window" ? "Sealed source window" : "Incomplete source window"
              : selectedPoint.run_id === visibleTrajectory?.head_run_id
                ? "Live published head"
                : "Earlier published snapshot"}
            stageRun={selectedPoint === null || selectedPoint.run_id === run?.run_id ? run : historicalRun}
            attemptStages={
              (selectedPoint === null || selectedPoint.run_id === run?.run_id)
              && canonicalHead?.watch.session_id === sessionId
                ? canonicalHead.stages
                : []
            }
            evidenceEnabled={selectedPoint === null || selectedPoint.run_id === run?.run_id}
            evidenceSessionId={sessionId}
            transport={transport}
          />
        </>
      ) : receiptAuthority === "verified" ? (
        <p className="model-ensemble__empty">
          {runPaused
            ? "No completed snapshot is available here. Resolve the pause reason above before retrying."
            : "Start one explicit run to create typed metric receipts plus content-free experimental ranges."}
        </p>
      ) : (
        <p className="model-ensemble__empty">
          Stored receipt availability is temporarily unknown. The app will retry locally without treating missing data as zero or absence.
        </p>
      )}
    </section>
  );
}
