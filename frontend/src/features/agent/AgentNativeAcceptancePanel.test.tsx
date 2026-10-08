import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AgentEvent,
  AgentSessionView,
  LocalRuntimeCoordinatorStatus,
} from "../../shared/api/contracts";
import { AgentNativeAcceptancePanel, type NativeAcceptanceRun } from "./AgentNativeAcceptancePanel";
import { AGENT_LEGACY_PARITY, AGENT_PARITY_SUMMARY } from "./agentReleaseParity";
import { exampleAgentTurn, exampleWriteReceipt } from "./agentTurnFixtures.test-support";

const SESSION = "a".repeat(32);

function session(overrides: Partial<AgentSessionView> = {}): AgentSessionView {
  return {
    contract_version: "local-agent.v9",
    cleanup_unconfirmed: false,
    closing: false,
    stopping: false,
    session_id: SESSION,
    settings: {
      workspace: "D:\\example\\acceptance",
      project_id: "b".repeat(32),
      model_alias: "synthetic-model",
      parameters: { temperature: 0.2, top_p: 0.95, max_tokens: 1400, enable_thinking: false },
      instructions: null,
      allow_writes: false,
      allow_commands: false,
      allow_web: false,
      max_steps: 10,
      command_timeout_seconds: 120,
      title: "Synthetic acceptance",
      retention_policy: "local_history",
    },
    created_at: "2040-01-01T10:00:00Z",
    running: false,
    last_seq: 0,
    pending_approval_id: null,
    model_alias: "synthetic-model",
    turns: 0,
    history_revision: 0,
    recovered: false,
    authority_revalidated: true,
    history_write_failed: false,
    recovery_state: "current",
    ...overrides,
  };
}

function context(served: boolean): LocalRuntimeCoordinatorStatus["context"] {
  return served
    ? {
        state: "unknown",
        used_tokens: null,
        limit_tokens: 8192,
        requested_output_tokens: null,
        available_output_tokens: null,
        source: "runtime_limit_only",
        scope: "runtime_limit",
        policy: "runtime_enforced",
        compacted_messages: 0,
        reason_code: "no_request_measured",
      }
    : {
        state: "unknown",
        used_tokens: null,
        limit_tokens: null,
        requested_output_tokens: null,
        available_output_tokens: null,
        source: "runtime_limit_only",
        scope: "runtime_limit",
        policy: "runtime_enforced",
        compacted_messages: 0,
        reason_code: "runtime_not_served",
      };
}

function runtime(
  state: LocalRuntimeCoordinatorStatus["state"],
  revision: number,
  gpuLayers = 0,
  cleanup: LocalRuntimeCoordinatorStatus["cleanup"] = {
    state: "not_required",
    process_exit_confirmed: true,
    gpu_memory_free_before_mb: null,
    gpu_memory_free_after_mb: null,
    gpu_memory_released_mb: null,
  },
  alias = "synthetic-model",
): LocalRuntimeCoordinatorStatus {
  const served = state === "ready";
  const selection = {
    alias,
    device: gpuLayers > 0 ? "gpu" as const : "cpu" as const,
    gpu_layers: gpuLayers,
    context_size: 8192,
  };
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision,
    state,
    requested: served ? selection : null,
    served: served ? { ...selection, started_at: "2040-01-01T10:00:00Z", pid: 4242 } : null,
    cleanup,
    capabilities: served
      ? {
          state: "verified",
          probe_version: "local-runtime-multimodal-probe.v2",
          text: true,
          tools: true,
          vision: false,
          audio: false,
          recording: false,
          structured_output: false,
          error_code: null,
        }
      : {
          state: "not_probed",
          probe_version: "local-runtime-multimodal-probe.v2",
          text: false,
          tools: false,
          vision: false,
          audio: false,
          recording: false,
          structured_output: false,
          error_code: null,
        },
    context: context(served),
    active_requests: 0,
    last_error_code: state === "cleanup_unknown" ? "runtime_cleanup_unconfirmed" : null,
  };
}

function doneEvents(): AgentEvent[] {
  const completedId = "c".repeat(32);
  const stoppedId = "d".repeat(32);
  return [
    {
      seq: 1,
      at: "2040-01-01T10:01:00Z",
      kind: "done",
      attachments: [],
      turn_id: completedId,
      turn_summary: exampleAgentTurn({ turn_id: completedId }),
    },
    {
      seq: 2,
      at: "2040-01-01T10:02:00Z",
      kind: "done",
      attachments: [],
      turn_id: stoppedId,
      turn_summary: exampleAgentTurn({
        turn_id: stoppedId,
        turn_number: 2,
        status: "stopped",
        reason: "stop_requested",
      }),
    },
  ];
}

function coreLoopEvents(): AgentEvent[] {
  return [
    ...doneEvents(),
    {
      seq: 3,
      at: "2040-01-01T10:03:00Z",
      kind: "tool_result",
      attachments: [],
      tool: "write_file",
      call_id: "1".repeat(32),
      ok: true,
      tool_state: "succeeded",
      write_receipt: exampleWriteReceipt(),
      execution_receipt: {
        contract_version: "agent-tool-execution.v1",
        elapsed_ms: 125,
        timing_source: "server_monotonic.v1",
        approval_state: "approved",
        evidence_state: "verified_workspace_effect",
      },
    },
    {
      seq: 4,
      at: "2040-01-01T10:04:00Z",
      kind: "tool_result",
      attachments: [],
      tool: "run_command",
      call_id: "2".repeat(32),
      ok: true,
      tool_state: "succeeded",
      execution_receipt: {
        contract_version: "agent-tool-execution.v1",
        elapsed_ms: 250,
        timing_source: "server_monotonic.v1",
        approval_state: "approved",
        evidence_state: "untracked_external_effect",
      },
    },
  ];
}

const START_RECEIPT = {
  contract_version: "agent-native-acceptance-start.v1",
  owner_presence_confirmed: true,
  model_execution_started: false,
  process_spawn_requested: false,
  workspace_access_requested: false,
  content_persisted: false,
  expires_on_reload: true,
} as const;

describe("AgentNativeAcceptancePanel", () => {
  it("is inert on render and fails closed outside native owner presence", () => {
    const begin = vi.fn();
    const getLocalRuntime = vi.fn();
    render(
      <AgentNativeAcceptancePanel
        current={session()}
        events={[]}
        onRuntimeStatus={vi.fn()}
        reviewOpen={false}
        transport={{ beginAgentNativeAcceptance: begin, getLocalRuntime }}
        userPresenceAvailable={false}
      />,
    );

    expect(screen.getByRole("button", { name: "Native confirmation required" })).toBeDisabled();
    expect(screen.getByText(/never starts or stops a model/i)).toBeInTheDocument();
    expect(begin).not.toHaveBeenCalled();
    expect(getLocalRuntime).not.toHaveBeenCalled();
  });

  it("does not mistake a partial CPU lifecycle for the complete packaged core loop", async () => {
    let currentRuntime = runtime("idle", 1);
    let currentSession = session();
    let events: AgentEvent[] = [];
    let reviewOpen = false;
    const begin = vi.fn(async () => START_RECEIPT);
    const getLocalRuntime = vi.fn(async () => currentRuntime);
    const getAgentChangeSet = vi.fn(async () => ({ contract_version: "synthetic" } as never));
    const onRuntimeStatus = vi.fn();
    const transport = { beginAgentNativeAcceptance: begin, getAgentChangeSet, getLocalRuntime };
    const rendered = render(
      <AgentNativeAcceptancePanel
        current={currentSession}
        events={events}
        onRuntimeStatus={onRuntimeStatus}
        reviewOpen={reviewOpen}
        transport={transport}
        userPresenceAvailable
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await waitFor(() => expect(begin).toHaveBeenCalledOnce());
    expect(within(screen.getByText("Clean stopped baseline").closest("li")!).getByText("Passed")).toBeInTheDocument();
    expect(getAgentChangeSet).not.toHaveBeenCalled();

    currentRuntime = runtime("ready", 2);
    currentSession = session({ turns: 2, last_seq: 2 });
    events = doneEvents();
    reviewOpen = true;
    rendered.rerender(
      <AgentNativeAcceptancePanel
        current={currentSession}
        events={events}
        onRuntimeStatus={onRuntimeStatus}
        reviewOpen={reviewOpen}
        transport={transport}
        userPresenceAvailable
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await waitFor(() => expect(getAgentChangeSet).toHaveBeenCalledWith(SESSION));
    for (const label of [
      "Verified model startup",
      "Completed streamed chat",
      "Stopped response receipt",
      "Files & review contract",
      "Context truth contract",
    ]) {
      expect(within(screen.getByText(label).closest("li")!).getByText("Passed")).toBeInTheDocument();
    }

    currentRuntime = runtime("idle", 3);
    rendered.rerender(
      <AgentNativeAcceptancePanel
        current={currentSession}
        events={events}
        onRuntimeStatus={onRuntimeStatus}
        reviewOpen={reviewOpen}
        transport={transport}
        userPresenceAvailable
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));

    await screen.findByText(/approved workspace write/i);
    expect(within(screen.getByText("Unload and process exit").closest("li")!).getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("CPU · not required")).toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  it("withholds GPU cleanup and completion when measurement is unknown", async () => {
    let currentRuntime = runtime("idle", 10);
    let currentSession = session();
    let events: AgentEvent[] = [];
    const transport = {
      beginAgentNativeAcceptance: vi.fn(async () => START_RECEIPT),
      getAgentChangeSet: vi.fn(async () => ({} as never)),
      getLocalRuntime: vi.fn(async () => currentRuntime),
    };
    const rendered = render(
      <AgentNativeAcceptancePanel current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByText("Clean stopped baseline");

    currentRuntime = runtime("ready", 11, 32);
    currentSession = session({ turns: 2, last_seq: 2 });
    events = doneEvents();
    rendered.rerender(
      <AgentNativeAcceptancePanel current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await waitFor(() => expect(screen.getByText("Verified model startup").closest("li")).toHaveAttribute("data-state", "passed"));

    currentRuntime = runtime("cleanup_unknown", 12, 0, {
      state: "unknown",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: null,
      gpu_memory_free_after_mb: null,
      gpu_memory_released_mb: null,
    });
    rendered.rerender(
      <AgentNativeAcceptancePanel current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));

    await screen.findByText(/cleanup is unconfirmed/i);
    expect(screen.getByText("GPU cleanup evidence").closest("li")).toHaveAttribute("data-state", "waiting");
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
  });

  it("completes only after restart, workspace, approved tools, artifact, switch, and final GPU unload evidence", async () => {
    let currentRuntime = runtime("idle", 20);
    let currentSession = session({ recovered: true, recovery_state: "recovered" });
    let events: AgentEvent[] = [];
    let artifactViewRevision = 0;
    const transport = {
      beginAgentNativeAcceptance: vi.fn(async () => START_RECEIPT),
      getAgentChangeSet: vi.fn(async () => ({} as never)),
      getAgentWorkspaceTree: vi.fn(async () => ({} as never)),
      getLocalRuntime: vi.fn(async () => currentRuntime),
    };
    const rendered = render(
      <AgentNativeAcceptancePanel artifactViewRevision={artifactViewRevision} current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByRole("button", { name: "Check current evidence" });

    currentRuntime = runtime("ready", 21, 24);
    currentSession = session({ recovered: true, recovery_state: "recovered", turns: 2, last_seq: 4 });
    events = coreLoopEvents();
    artifactViewRevision = 1;
    rendered.rerender(
      <AgentNativeAcceptancePanel artifactViewRevision={artifactViewRevision} current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await waitFor(() => expect(screen.getByText("Verified model startup").closest("li")).toHaveAttribute("data-state", "passed"));

    currentRuntime = runtime("ready", 22, 24, undefined, "synthetic-second-model");
    rendered.rerender(
      <AgentNativeAcceptancePanel artifactViewRevision={artifactViewRevision} current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await waitFor(() => expect(screen.getByText("Second model became ready").closest("li")).toHaveAttribute("data-state", "passed"));
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();

    currentRuntime = runtime("idle", 23, 0, {
      state: "measured",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: 1024,
      gpu_memory_free_after_mb: 1536,
      gpu_memory_released_mb: 512,
    });
    rendered.rerender(
      <AgentNativeAcceptancePanel artifactViewRevision={artifactViewRevision} current={currentSession} events={events} onRuntimeStatus={vi.fn()} reviewOpen transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));

    await screen.findByText(/packaged Agent core-loop evidence is complete/i);
    expect(screen.getByText("Measured")).toBeInTheDocument();
  });

  it("keeps prior evidence after an interrupted read and never retries by itself", async () => {
    const getLocalRuntime = vi.fn()
      .mockResolvedValueOnce(runtime("idle", 30))
      .mockRejectedValueOnce(new Error("synthetic local interruption"));
    render(
      <AgentNativeAcceptancePanel
        current={session()}
        events={[]}
        onRuntimeStatus={vi.fn()}
        reviewOpen={false}
        transport={{ beginAgentNativeAcceptance: vi.fn(async () => START_RECEIPT), getLocalRuntime }}
        userPresenceAvailable
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await waitFor(() => expect(screen.getByText("Clean stopped baseline").closest("li")).toHaveAttribute("data-state", "passed"));

    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await screen.findByText(/no action was retried or started/i);
    expect(getLocalRuntime).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Clean stopped baseline").closest("li")).toHaveAttribute("data-state", "passed");
  });

  it("does not merge evidence across chats and clears only its page-local receipt", async () => {
    const currentRuntime = runtime("idle", 1);
    const transport = {
      beginAgentNativeAcceptance: vi.fn(async () => START_RECEIPT),
      getLocalRuntime: vi.fn(async () => currentRuntime),
    };
    const rendered = render(
      <AgentNativeAcceptancePanel current={session()} events={[]} onRuntimeStatus={vi.fn()} reviewOpen={false} transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByRole("button", { name: "Check current evidence" });
    rendered.rerender(
      <AgentNativeAcceptancePanel current={session({ session_id: "f".repeat(32) })} events={[]} onRuntimeStatus={vi.fn()} reviewOpen={false} transport={transport} userPresenceAvailable />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Check current evidence" }));
    await screen.findByText(/evidence cannot be combined across sessions/i);

    fireEvent.click(screen.getByRole("button", { name: "Clear local receipt" }));
    expect(screen.getByRole("button", { name: "Begin guarded acceptance" })).toBeInTheDocument();
    expect(transport.beginAgentNativeAcceptance).toHaveBeenCalledOnce();
  });

  it("reports a declined native gate without reading runtime state", async () => {
    const getLocalRuntime = vi.fn();
    render(
      <AgentNativeAcceptancePanel
        current={session()}
        events={[]}
        onRuntimeStatus={vi.fn()}
        reviewOpen={false}
        transport={{
          beginAgentNativeAcceptance: vi.fn(async () => { throw new Error("synthetic decline"); }),
          getLocalRuntime,
        }}
        userPresenceAvailable
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByText(/no acceptance run, model, process, or workspace action was started/i);
    expect(getLocalRuntime).not.toHaveBeenCalled();
  });

  it("keeps the page-owned receipt when the Settings surface closes and reopens", async () => {
    const transport = {
      beginAgentNativeAcceptance: vi.fn(async () => START_RECEIPT),
      getLocalRuntime: vi.fn(async () => runtime("idle", 40)),
    };

    function Harness() {
      const [open, setOpen] = useState(true);
      const [run, setRun] = useState<NativeAcceptanceRun | null>(null);
      return (
        <>
          <button onClick={() => setOpen((value) => !value)} type="button">Toggle settings</button>
          {open && (
            <AgentNativeAcceptancePanel
              acceptanceRun={run}
              current={session()}
              events={[]}
              onAcceptanceRunChange={setRun}
              onRuntimeStatus={vi.fn()}
              reviewOpen={false}
              transport={transport}
              userPresenceAvailable
            />
          )}
        </>
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Begin guarded acceptance" }));
    await screen.findByRole("button", { name: "Check current evidence" });

    fireEvent.click(screen.getByRole("button", { name: "Toggle settings" }));
    expect(screen.queryByRole("region", { name: "Guarded native Agent acceptance" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle settings" }));

    expect(screen.getByRole("button", { name: "Check current evidence" })).toBeVisible();
    expect(transport.beginAgentNativeAcceptance).toHaveBeenCalledOnce();
  });

  it("freezes the complete retirement ledger and keeps known blockers explicit", () => {
    const keys = AGENT_LEGACY_PARITY.map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual([
      "project_catalog",
      "chat_catalog",
      "retained_history",
      "streaming_stop",
      "reasoning_tools",
      "workspace_review",
      "protected_approvals",
      "artifacts",
      "multimodal",
      "runtime",
      "context",
      "controller",
      "retention_export",
      "responsive_accessibility",
      "session_branching",
      "separate_native_window",
    ]);
    expect(AGENT_PARITY_SUMMARY).toEqual({
      total: 16,
      complete: 16,
      missing: 0,
      ownerPending: 10,
      platformBlocked: 0,
    });
    expect(AGENT_LEGACY_PARITY.find((item) => item.key === "session_branching")).toMatchObject({
      implementation: "complete",
      automatedEvidence: true,
    });
    expect(AGENT_LEGACY_PARITY.find((item) => item.key === "separate_native_window")).toMatchObject({
      implementation: "complete",
      automatedEvidence: true,
      ownerGate: "pending",
    });
  });
});
