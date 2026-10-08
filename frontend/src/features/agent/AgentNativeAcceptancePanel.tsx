import { useState } from "react";

import type {
  AgentEvent,
  AgentSessionView,
  LocalRuntimeCoordinatorStatus,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import "./AgentNativeAcceptancePanel.css";

type AcceptanceTransport = Partial<Pick<
  PromptEnhancerTransport,
  "beginAgentNativeAcceptance" | "getAgentChangeSet" | "getAgentWorkspaceTree" | "getLocalRuntime"
>>;

type Baseline = {
  artifactViewRevision: number;
  eventSeq: number;
  runtimeRevision: number;
  sessionId: string;
};

export type NativeAcceptanceRun = {
  approvedCommand: boolean;
  approvedWrite: boolean;
  artifactViewed: boolean;
  baseline: Baseline | null;
  cleanupProblem: "failed" | "unknown" | null;
  completedChat: boolean;
  contextTruthObserved: boolean;
  gpuCleanup: "waiting" | "not_required" | "measured";
  latestReadyGpuLayers: number | null;
  latestReadyRevision: number | null;
  modelSwitchObserved: boolean;
  nativeOwnerConfirmed: true;
  processExitConfirmed: boolean;
  recoveredSessionObserved: boolean;
  reviewContractObserved: boolean;
  sessionMismatch: boolean;
  startupAlias: string | null;
  startupGpuLayers: number | null;
  startupObserved: boolean;
  startupRevision: number | null;
  stoppedResponse: boolean;
  unloaded: boolean;
  workspaceContractObserved: boolean;
};

type Observation = {
  artifactViewRevision: number;
  current: AgentSessionView | null;
  events: AgentEvent[];
  reviewContractObserved: boolean;
  runtime: LocalRuntimeCoordinatorStatus;
  workspaceContractObserved: boolean;
};

const INITIAL_RUN: NativeAcceptanceRun = {
  approvedCommand: false,
  approvedWrite: false,
  artifactViewed: false,
  baseline: null,
  cleanupProblem: null,
  completedChat: false,
  contextTruthObserved: false,
  gpuCleanup: "waiting",
  latestReadyGpuLayers: null,
  latestReadyRevision: null,
  modelSwitchObserved: false,
  nativeOwnerConfirmed: true,
  processExitConfirmed: false,
  recoveredSessionObserved: false,
  reviewContractObserved: false,
  sessionMismatch: false,
  startupAlias: null,
  startupGpuLayers: null,
  startupObserved: false,
  startupRevision: null,
  stoppedResponse: false,
  unloaded: false,
  workspaceContractObserved: false,
};

function cleanIdleBaseline(
  runtime: LocalRuntimeCoordinatorStatus,
  current: AgentSessionView | null,
): current is AgentSessionView {
  return current !== null
    && !current.running
    && !current.stopping
    && !current.closing
    && !current.cleanup_unconfirmed
    && current.pending_approval_id === null
    && runtime.state === "idle"
    && runtime.served === null
    && runtime.active_requests === 0
    && runtime.cleanup.process_exit_confirmed
    && runtime.cleanup.state !== "unknown"
    && runtime.cleanup.state !== "failed";
}

function newestEventSeq(events: AgentEvent[]): number {
  return events.reduce((latest, event) => Math.max(latest, event.seq), 0);
}

function approvedToolSucceeded(event: AgentEvent, tool: "run_command" | "write_file"): boolean {
  return event.kind === "tool_result"
    && event.tool === tool
    && event.ok === true
    && event.tool_state === "succeeded"
    && event.execution_receipt?.approval_state === "approved";
}

export function observeNativeAcceptance(
  run: NativeAcceptanceRun,
  observation: Observation,
): NativeAcceptanceRun {
  const {
    artifactViewRevision,
    current,
    events,
    reviewContractObserved,
    runtime,
    workspaceContractObserved,
  } = observation;
  if (run.baseline === null) {
    if (!cleanIdleBaseline(runtime, current)) {
      return {
        ...run,
        cleanupProblem: runtime.cleanup.state === "failed"
          ? "failed"
          : runtime.cleanup.state === "unknown" ? "unknown" : null,
      };
    }
    return {
      ...run,
      baseline: {
        artifactViewRevision,
        eventSeq: newestEventSeq(events),
        runtimeRevision: runtime.revision,
        sessionId: current.session_id,
      },
      cleanupProblem: null,
      recoveredSessionObserved: current.recovered
        && current.settings.retention_policy === "local_history",
    };
  }

  if (current === null || current.session_id !== run.baseline.sessionId) {
    return { ...run, sessionMismatch: true };
  }

  const fresh = events.filter((event) => event.seq > run.baseline!.eventSeq);
  const approvedWrite = run.approvedWrite || fresh.some(
    (event) => approvedToolSucceeded(event, "write_file")
      && event.write_receipt?.state === "verified"
      && event.execution_receipt?.evidence_state === "verified_workspace_effect",
  );
  const approvedCommand = run.approvedCommand || fresh.some(
    (event) => approvedToolSucceeded(event, "run_command"),
  );
  const completedChat = run.completedChat || fresh.some(
    (event) => event.kind === "done" && event.turn_summary?.status === "completed",
  );
  const stoppedResponse = run.stoppedResponse || fresh.some(
    (event) => event.kind === "done"
      && event.turn_summary?.status === "stopped"
      && event.turn_summary.reason === "stop_requested",
  );
  const readyNow = runtime.state === "ready"
    && runtime.served !== null
    && runtime.capabilities.state === "verified"
    && runtime.active_requests === 0
    && runtime.revision > run.baseline.runtimeRevision;
  const startupObserved = run.startupObserved || readyNow;
  const startupRevision = run.startupRevision ?? (readyNow ? runtime.revision : null);
  const startupGpuLayers = run.startupGpuLayers ?? (readyNow ? runtime.served!.gpu_layers : null);
  const newlyObservedReady = readyNow && (
    run.latestReadyRevision === null || runtime.revision > run.latestReadyRevision
  );
  const startupAlias = run.startupAlias ?? (readyNow ? runtime.served!.alias : null);
  const modelSwitchObserved = run.modelSwitchObserved || (
    newlyObservedReady
    && startupAlias !== null
    && runtime.served!.alias !== startupAlias
  );
  const latestReadyRevision = newlyObservedReady
    ? runtime.revision
    : run.latestReadyRevision;
  const latestReadyGpuLayers = newlyObservedReady
    ? runtime.served!.gpu_layers
    : run.latestReadyGpuLayers;
  const contextTruthObserved = run.contextTruthObserved || (
    completedChat
    && startupObserved
    && (runtime.context.state === "known" || runtime.context.state === "unknown")
  );
  const cleanUnload = latestReadyRevision !== null
    && runtime.revision > latestReadyRevision
    && runtime.state === "idle"
    && runtime.served === null
    && runtime.active_requests === 0
    && runtime.cleanup.process_exit_confirmed
    && runtime.cleanup.state !== "unknown"
    && runtime.cleanup.state !== "failed";
  const processExitConfirmed = newlyObservedReady ? false : run.processExitConfirmed || cleanUnload;
  const unloaded = newlyObservedReady ? false : run.unloaded || cleanUnload;
  let gpuCleanup = newlyObservedReady ? "waiting" as const : run.gpuCleanup;
  if (cleanUnload && latestReadyGpuLayers !== null) {
    if (latestReadyGpuLayers === 0 && runtime.cleanup.state === "not_required") {
      gpuCleanup = "not_required";
    } else if (latestReadyGpuLayers > 0 && runtime.cleanup.state === "measured") {
      gpuCleanup = "measured";
    }
  }
  return {
    ...run,
    approvedCommand,
    approvedWrite,
    artifactViewed: run.artifactViewed
      || artifactViewRevision > run.baseline.artifactViewRevision,
    cleanupProblem: runtime.cleanup.state === "failed"
      ? "failed"
      : runtime.cleanup.state === "unknown" ? "unknown" : null,
    completedChat,
    contextTruthObserved,
    gpuCleanup,
    latestReadyGpuLayers,
    latestReadyRevision,
    modelSwitchObserved,
    processExitConfirmed,
    recoveredSessionObserved: run.recoveredSessionObserved || (
      current.recovered && current.settings.retention_policy === "local_history"
    ),
    reviewContractObserved: run.reviewContractObserved || reviewContractObserved,
    sessionMismatch: false,
    startupGpuLayers,
    startupAlias,
    startupObserved,
    startupRevision,
    stoppedResponse,
    unloaded,
    workspaceContractObserved: run.workspaceContractObserved || workspaceContractObserved,
  };
}

function isComplete(run: NativeAcceptanceRun): boolean {
  return run.baseline !== null
    && run.recoveredSessionObserved
    && run.workspaceContractObserved
    && run.startupObserved
    && run.completedChat
    && run.stoppedResponse
    && run.approvedWrite
    && run.approvedCommand
    && run.reviewContractObserved
    && run.artifactViewed
    && run.contextTruthObserved
    && run.modelSwitchObserved
    && run.processExitConfirmed
    && run.unloaded
    && run.gpuCleanup !== "waiting"
    && run.cleanupProblem === null
    && !run.sessionMismatch;
}

function phaseState(passed: boolean): "passed" | "waiting" {
  return passed ? "passed" : "waiting";
}

export function AgentNativeAcceptancePanel({
  acceptanceRun,
  artifactViewRevision = 0,
  current,
  events,
  onAcceptanceRunChange,
  onRuntimeStatus,
  reviewOpen,
  transport,
  userPresenceAvailable,
}: {
  acceptanceRun?: NativeAcceptanceRun | null;
  artifactViewRevision?: number;
  current: AgentSessionView | null;
  events: AgentEvent[];
  onAcceptanceRunChange?: (run: NativeAcceptanceRun | null) => void;
  onRuntimeStatus: (runtime: LocalRuntimeCoordinatorStatus) => void;
  reviewOpen: boolean;
  transport: AcceptanceTransport;
  userPresenceAvailable: boolean;
}) {
  const [localRun, setLocalRun] = useState<NativeAcceptanceRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = acceptanceRun === undefined ? localRun : acceptanceRun;
  function setRun(value: NativeAcceptanceRun | null): void {
    if (acceptanceRun === undefined) setLocalRun(value);
    onAcceptanceRunChange?.(value);
  }
  const available = transport.beginAgentNativeAcceptance !== undefined
    && transport.getLocalRuntime !== undefined;
  const complete = run !== null && isComplete(run);

  async function readObservation(base: NativeAcceptanceRun): Promise<NativeAcceptanceRun> {
    const runtime = await transport.getLocalRuntime!();
    onRuntimeStatus(runtime);
    let reviewContractObserved = false;
    let workspaceContractObserved = false;
    if (
      base.baseline !== null
      && current?.session_id === base.baseline.sessionId
    ) {
      if (transport.getAgentWorkspaceTree !== undefined) {
        try {
          await transport.getAgentWorkspaceTree(current.session_id, "");
          workspaceContractObserved = true;
        } catch {
          workspaceContractObserved = false;
        }
      }
      if (reviewOpen && transport.getAgentChangeSet !== undefined) {
        try {
          await transport.getAgentChangeSet(current.session_id);
          reviewContractObserved = true;
        } catch {
          reviewContractObserved = false;
        }
      }
    }
    return observeNativeAcceptance(base, {
      artifactViewRevision,
      current,
      events,
      reviewContractObserved,
      runtime,
      workspaceContractObserved,
    });
  }

  async function begin(): Promise<void> {
    if (!available || !userPresenceAvailable || busy) return;
    setBusy(true);
    setError("");
    try {
      await transport.beginAgentNativeAcceptance!({
        confirmation: "begin_guarded_agent_native_acceptance",
      });
      const initial = { ...INITIAL_RUN };
      try {
        setRun(await readObservation(initial));
      } catch {
        setRun(initial);
        setError("Owner confirmation succeeded, but runtime evidence is unavailable. Reconnect locally and check again.");
      }
    } catch {
      setError("Native owner confirmation did not complete. No acceptance run, model, process, or workspace action was started.");
    } finally {
      setBusy(false);
    }
  }

  async function check(): Promise<void> {
    if (run === null || busy || transport.getLocalRuntime === undefined) return;
    setBusy(true);
    setError("");
    try {
      setRun(await readObservation(run));
    } catch {
      setError("Current evidence could not be read. No action was retried or started.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-busy={busy} aria-label="Guarded native Agent acceptance" className="agent-acceptance">
      <header>
        <span>
          <small>Release acceptance</small>
          <strong>Owner-run lifecycle check</strong>
        </span>
        <span aria-hidden="true" className="agent-acceptance__state" data-state={complete ? "passed" : run ? "active" : "idle"}>
          {complete ? "Complete" : run ? "In progress" : "Off"}
        </span>
      </header>
      <p>
        This guide never starts or stops a model, sends a prompt, writes, or runs
        a command. Begin only in the native desktop window with a local-history
        chat that has survived an app restart. Then use the normal Agent controls
        and ask this card to check their content-free receipts.
      </p>
      <p className="agent-acceptance__memory">The receipt stays in this page only, survives closing Settings, and clears on reload. Paths, prompts, command output and artifact bytes are not copied into it.</p>

      {run === null ? (
        <button
          className="button button--ghost"
          disabled={!available || !userPresenceAvailable || busy}
          onClick={() => void begin()}
          type="button"
        >
          {busy ? "Confirming…" : userPresenceAvailable ? "Begin guarded acceptance" : "Native confirmation required"}
        </button>
      ) : (
        <>
          <ol className="agent-acceptance__phases">
            <li data-state="passed"><span>Native owner gate</span><strong>Passed</strong></li>
            <li data-state={phaseState(run.recoveredSessionObserved)}><span>Chat survived app restart</span><strong>{run.recoveredSessionObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.baseline !== null)}><span>Clean stopped baseline</span><strong>{run.baseline ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.workspaceContractObserved)}><span>Workspace root admitted</span><strong>{run.workspaceContractObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.startupObserved)}><span>Verified model startup</span><strong>{run.startupObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.completedChat)}><span>Completed streamed chat</span><strong>{run.completedChat ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.stoppedResponse)}><span>Stopped response receipt</span><strong>{run.stoppedResponse ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.approvedWrite)}><span>Approved workspace write</span><strong>{run.approvedWrite ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.approvedCommand)}><span>Approved command</span><strong>{run.approvedCommand ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.reviewContractObserved)}><span>Files &amp; review contract</span><strong>{run.reviewContractObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.artifactViewed)}><span>Artifact viewer revalidated</span><strong>{run.artifactViewed ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.contextTruthObserved)}><span>Context truth contract</span><strong>{run.contextTruthObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.modelSwitchObserved)}><span>Second model became ready</span><strong>{run.modelSwitchObserved ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.processExitConfirmed && run.unloaded)}><span>Unload and process exit</span><strong>{run.processExitConfirmed && run.unloaded ? "Passed" : "Waiting"}</strong></li>
            <li data-state={phaseState(run.gpuCleanup !== "waiting")}><span>GPU cleanup evidence</span><strong>{run.gpuCleanup === "measured" ? "Measured" : run.gpuCleanup === "not_required" ? "CPU · not required" : "Waiting"}</strong></li>
          </ol>
          <div aria-atomic="true" aria-live="polite" className="agent-acceptance__announcement" role="status">
            {complete
              ? "The packaged Agent core-loop evidence is complete for this page run. Separate installer, terminal-window census and physical offload checks remain release evidence."
              : run.cleanupProblem === "unknown"
                ? "Cleanup is unconfirmed. Do not load another model; clear this run only after inspecting local runtime cleanup."
                : run.cleanupProblem === "failed"
                  ? "Runtime cleanup failed and remains quarantined. Do not continue this acceptance run."
                  : run.sessionMismatch
                    ? "Return to the chat used for the clean baseline; evidence cannot be combined across sessions."
                    : run.baseline === null
                      ? "Select one idle live chat, stop the shared runtime, then check current evidence to capture a clean baseline."
                      : !run.recoveredSessionObserved
                        ? "This chat has not been recovered from local history. Clear this receipt, restart the app, resume the retained chat, and begin again."
                        : !run.workspaceContractObserved
                          ? "Open Files & review, then check current evidence so the admitted workspace root can be verified."
                      : !run.startupObserved
                        ? "Load the selected model with the normal Model & context control, then check current evidence."
                      : !run.completedChat || !run.stoppedResponse
                          ? "In this chat, complete one response and Stop one later response, then check current evidence."
                          : !run.approvedWrite || !run.approvedCommand
                            ? "Approve one reviewed write and one reviewed command in this chat, then check their terminal receipts."
                          : !run.reviewContractObserved
                            ? "Open Files & review for this chat, then check current evidence. No file content is retained by this card."
                            : !run.artifactViewed
                              ? "Open one recorded artifact through its viewer, close it, then check current evidence."
                              : !run.modelSwitchObserved
                                ? "Switch to a second admitted model and wait until it is ready, then check current evidence."
                            : !run.unloaded
                              ? "Stop the shared model with the normal runtime control, then check process and GPU cleanup evidence."
                              : "Acceptance evidence is still incomplete; review the waiting phase above."}
          </div>
          <div className="agent-acceptance__actions">
            <button className="button button--ghost" disabled={busy} onClick={() => void check()} type="button">
              {busy ? "Checking…" : "Check current evidence"}
            </button>
            <button className="button button--ghost" disabled={busy} onClick={() => { setRun(null); setError(""); }} type="button">
              Clear local receipt
            </button>
          </div>
        </>
      )}
      {!available && <p className="agent-acceptance__memory">Update the local app before running native acceptance.</p>}
      {error && <p className="agent-acceptance__error" role="alert">{error}</p>}

    </section>
  );
}
