import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CodexSession,
  ModelEnsembleCanonicalHead,
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPage,
  ModelEnsembleWatchSnapshot,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import {
  createTeamControlPlanePortForRuntime,
  teamControlPlanePortForOverlay,
} from "../../shared/api/teamControlPlaneRuntime";
import {
  CANCEL_ARMING_DELAY_MS,
  ModelEnsembleOverlay,
  stageCaseCountCopy,
} from "./ModelEnsembleOverlay";
import { CANONICAL_POLL_WRONG_RUN_MS } from "./canonicalPolling";

async function settlePoll() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  Reflect.deleteProperty(window, "pywebview");
});

describe("production team-context composition", () => {
  it("renders only registered drawers and keeps local-real team values closed", async () => {
    const syntheticPort = createTeamControlPlanePortForRuntime("synthetic_demo");
    const accepted = teamControlPlanePortForOverlay("synthetic_demo", syntheticPort);
    const view = render(
      <ModelEnsembleOverlay transport={createSyntheticTransport()} teamControlPlane={accepted} />,
    );
    expect(screen.getByText("Team context")).toBeVisible();
    expect(document.querySelector(".team-context-drawer")).not.toBeNull();
    expect(await screen.findByText(/Synthetic platform guild \(fixture cohort\)/)).toBeVisible();

    const localPort = createTeamControlPlanePortForRuntime("local_real");
    view.rerender(
      <ModelEnsembleOverlay
        transport={createSyntheticTransport()}
        teamControlPlane={teamControlPlanePortForOverlay("local_real", localPort)}
      />,
    );
    expect(screen.getByText("Team context")).toBeVisible();
    expect(screen.queryByText(/Synthetic platform guild/)).toBeNull();
    expect(document.querySelector(".team-context-drawer")).not.toBeNull();
    expect(await screen.findByText(/No team service in this runtime/)).toBeVisible();

    view.rerender(<ModelEnsembleOverlay transport={createSyntheticTransport()} teamControlPlane={null} />);
    expect(document.querySelector(".team-context-drawer")).toBeNull();
  });
});

const PROJECT_A = "a".repeat(64);
const PROJECT_B = "b".repeat(64);
const SESSION_A = "1".repeat(64);
const SESSION_B = "2".repeat(64);

function catalogSession(
  projectId: string,
  sessionId: string,
  projectLabel: string,
  sessionLabel: string,
  startedAt: string,
): CodexSession {
  return {
    adapter_version: "example-adapter-v1",
    ended_at: null,
    events_complete: false,
    installation_id: "f".repeat(64),
    project_display_name: projectLabel,
    project_display_name_origin: "provider",
    project_id: projectId,
    project_manual_label_revision: 0,
    provider: "codex",
    provider_version: "example-provider-v1",
    session_display_name: sessionLabel,
    session_display_name_origin: "provider",
    session_id: sessionId,
    session_manual_label_revision: 0,
    source_schema_version: "example-schema-v1",
    started_at: startedAt,
    terminal_state: "unknown",
  };
}

function watchSnapshot(
  maxMessages = 25,
  latestRun: ModelEnsembleRun | null = null,
): ModelEnsembleWatchSnapshot {
  return {
    watch: {
      watch_id: "d".repeat(64),
      provider: "codex",
      project_id: PROJECT_B,
      session_id: SESSION_B,
      max_messages: maxMessages,
      state: "queued",
      generation: 0,
      progress_completed: 0,
      progress_total: 10,
      has_result: latestRun !== null,
      last_error_code: null,
      next_check_at: "2040-01-02T10:01:00Z",
      updated_at: "2040-01-02T10:00:00Z",
      serial_model_execution: true,
      process_isolated_model_release: true,
      cuda_resource_retry_on_cpu: true,
      content_persisted: false,
      calibrated_as_truth: false,
    },
    latest_run: latestRun,
  };
}

function radarRun(runId: string, value: number, completedAt: string): ModelEnsembleRun {
  return {
    run_id: runId,
    completed_at: completedAt,
    metrics: [{
      metric_key: "prompt.task_definition_coverage",
      value_state: "known",
      numerator: value,
      denominator: 1,
      numeric_value: value,
      known_chunk_count: 1,
      abstained_chunk_count: 0,
      unsupported_chunk_count: 0,
      failed_chunk_count: 0,
      total_chunk_count: 1,
      explanation_code: "example_ratio",
      calibration_state: "not_assessed",
      product_metric_eligible: false,
    }],
    metric_projection_version: null,
    metric_projection_completed_at: null,
    metric_publication_v2: null,
    metric_profile_binding: null,
    typed_metrics: [],
    predictive_projection_version: null,
    predictive_projected_at: null,
    predictive_metrics: [],
    predictive_model_stages: [],
    chunk_metrics: [{
      chunk_ordinal: 0,
      metric_key: "prompt.task_definition_coverage",
      value_state: "known",
      numerator: value,
      denominator: 1,
      rubric_vote: value === 1 ? "present" : "absent",
      contributing_nli_votes: 2,
      diagnostic_nli_votes: 1,
      reason_code: "example_committee",
    }],
  } as unknown as ModelEnsembleRun;
}

function trajectoryPage(head: ModelEnsembleRun, older: ModelEnsembleRun): ModelEnsembleTrajectoryPage {
  const point = (run: ModelEnsembleRun, generation: number) => ({
    generation,
    run_id: run.run_id,
    published_at: new Date(new Date(run.completed_at).getTime() + 1000).toISOString(),
    completed_at: run.completed_at,
    max_messages: 25,
    source_coverage_state: "complete_window" as const,
    chunk_count: 1,
    comparable_to_head: true,
    metrics: run.metrics,
    metric_projection_version: run.metric_projection_version,
    metric_projection_completed_at: run.metric_projection_completed_at,
    typed_metrics: run.typed_metrics,
    metric_states_v2: [],
    predictive_projection_version: run.predictive_projection_version,
    predictive_metrics: run.predictive_metrics,
  });
  return {
    watch_id: "d".repeat(64),
    head_run_id: head.run_id,
    head_generation: 4,
    points: [point(head, 4), point(older, 2)],
    next_before_generation: null,
    content_persisted: false,
    calibrated_as_truth: false,
  };
}

function canonicalHead(run: ModelEnsembleRun, state: "running" | "cancelled" = "running"): ModelEnsembleCanonicalHead {
  const snapshot = watchSnapshot(25, run);
  snapshot.watch.state = state === "running" ? "running" : "idle";
  snapshot.watch.generation = 4;
  snapshot.watch.progress_completed = state === "running" ? 1 : 0;
  const completedAt = state === "cancelled" ? "2040-01-02T10:00:02Z" : null;
  return {
    schema_version: "analysis-snapshot-v2",
    watch: snapshot.watch,
    head_run_id: run.run_id,
    head_generation: 4,
    latest_attempt: {
      attempt_id: "c".repeat(64),
      watch_id: snapshot.watch.watch_id,
      generation: snapshot.watch.generation,
      state,
      prior_head_run_id: run.run_id,
      published_run_id: null,
      progress_completed: 1,
      progress_total: 6,
      stage_count: state === "cancelled" ? 1 : 0,
      warning_count: state === "cancelled" ? 1 : 0,
      error_code: state === "cancelled" ? "analysis_cancelled" : null,
      requested_at: "2040-01-02T10:00:00Z",
      started_at: "2040-01-02T10:00:00Z",
      completed_at: completedAt,
      content_persisted: false,
    },
    stages: state === "running" ? [] : [{
      stage_ordinal: 0,
      stage_key: "mdeberta_xnli",
      state: "cancelled",
      model_key: "mdeberta_xnli",
      repository_id: "example-org/example-model",
      revision: "f".repeat(40),
      error_code: "analysis_cancelled",
      device: "cuda",
      quantization: "none",
      inference_latency_ms: 120,
      peak_accelerator_memory_mb: 1024,
      process_rss_mb: 1536,
      evaluated_case_count: 20,
      contributed_case_count: 14,
      unloaded_after_stage: true,
      completed_at: "2040-01-02T10:00:01Z",
    }],
    content_persisted: false,
  };
}

function idleCanonicalHead(run: ModelEnsembleRun): ModelEnsembleCanonicalHead {
  const head = canonicalHead(run);
  head.watch.state = "idle";
  head.watch.progress_completed = 10;
  head.latest_attempt = {
    ...head.latest_attempt!,
    state: "completed",
    published_run_id: run.run_id,
    progress_completed: head.latest_attempt!.progress_total,
    completed_at: "2040-01-02T10:00:02Z",
  };
  return head;
}

describe("ModelEnsembleOverlay", () => {
  it.each(["cleanup", "streak", "legacy"])("does not invent automatic retries for %s job status", async (kind) => {
    const snapshot = watchSnapshot();
    snapshot.watch.state = "failed";
    snapshot.watch.last_error_code = kind === "cleanup" ? "model_ensemble_cleanup_unconfirmed" : "local_model_ensemble_execution_failed";
    if (kind !== "legacy") {
      snapshot.watch.quarantined = true;
      snapshot.watch.quarantine_reason_code = kind === "cleanup" ? "model_ensemble_cleanup_unconfirmed" : "watch_failure_streak_exhausted";
    }
    render(<ModelEnsembleOverlay transport={{ ...createSyntheticTransport(), getActiveModelEnsembleWatch: async () => snapshot }} />);
    if (kind === "legacy") {
      expect(await screen.findByText(/automatic retry status unavailable/)).toBeVisible();
    } else {
      expect(await screen.findByText(/Automatic retries are paused/)).toBeVisible();
    }
    expect(screen.queryByText(/automatic retry \d\d:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/retaining the last valid/i)).not.toBeInTheDocument();
    if (kind === "cleanup") expect(screen.getByText(/restart the app before retrying/)).toBeVisible();
  });

  it("renders absent stage case counts as unavailable rather than zero", () => {
    expect(stageCaseCountCopy({
      contributed_case_count: null,
      evaluated_case_count: null,
    })).toBe("case counts unavailable");
    expect(stageCaseCountCopy({
      contributed_case_count: 0,
      evaluated_case_count: 4,
    })).toBe("0/4 cases contributed");
  });

  it("renders custom native chrome and delegates only window controls to the desktop bridge", async () => {
    const minimizeWindow = vi.fn(async () => undefined);
    const toggleMaximizeWindow = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    const closeWindow = vi.fn(async () => undefined);
    Object.defineProperty(window, "pywebview", {
      configurable: true,
      value: {
        api: {
          minimize_window: minimizeWindow,
          toggle_maximize_window: toggleMaximizeWindow,
          close_window: closeWindow,
        },
      },
    });

    render(<ModelEnsembleOverlay transport={createSyntheticTransport()} />);

    expect(screen.getByText("Prompt Enhancer")).toBeVisible();
    expect(screen.getByText("Live intelligence")).toBeVisible();
    expect(document.querySelector(".model-ensemble-overlay")).toHaveAttribute("data-host", "native");
    const dashboardLink = await screen.findByRole("link", { name: /Open selected session in dashboard.*opens in your browser/i });
    expect(dashboardLink).toHaveAttribute("target", "_blank");
    expect(dashboardLink).toHaveAttribute("rel", expect.stringMatching(/noopener/));
    fireEvent.click(screen.getByRole("button", { name: "Minimize window" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize window" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Restore window" })).toBeVisible());
    fireEvent.click(screen.getByRole("button", { name: "Restore window" }));
    fireEvent.click(screen.getByRole("button", { name: "Close window" }));

    await waitFor(() => {
      expect(minimizeWindow).toHaveBeenCalledOnce();
      expect(toggleMaximizeWindow).toHaveBeenCalledTimes(2);
      expect(closeWindow).toHaveBeenCalledOnce();
    });
  });

  it("renders an absent active watch as an idle choice, not a disconnection", async () => {
    const getActiveModelEnsembleWatch = vi.fn().mockRejectedValue({ status: 404 });
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    await waitFor(() => expect(getActiveModelEnsembleWatch).toHaveBeenCalledOnce());
    await settlePoll();

    expect(screen.getByText("No active watch")).toBeVisible();
    expect(screen.getByText(/No live watch is active/i)).toBeVisible();
    expect(screen.queryByText(/Disconnected/)).not.toBeInTheDocument();
  });

  it("reserves disconnected for an actual service failure", async () => {
    vi.useFakeTimers();
    const getActiveModelEnsembleWatch = vi.fn().mockRejectedValue({ status: 503 });
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(screen.getByText(/Reconnecting · last receipt retained/i)).toBeVisible();
    vi.useRealTimers();
  });

  it("does not count intentionally superseded visibility polls as failures", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const getActiveModelEnsembleWatch = vi.fn((signal?: AbortSignal) => new Promise<ModelEnsembleWatchSnapshot>(
      (_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      },
    ));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch,
    };

    const view = render(<ModelEnsembleOverlay transport={transport} />);
    await waitFor(() => expect(getActiveModelEnsembleWatch).toHaveBeenCalledTimes(1));
    for (const expectedCalls of [2, 3, 4]) {
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await waitFor(() => expect(getActiveModelEnsembleWatch).toHaveBeenCalledTimes(expectedCalls));
    }
    await settlePoll();

    expect(screen.queryByText(/Reconnecting · last receipt retained/i)).not.toBeInTheDocument();
    view.unmount();
    visibility.mockRestore();
  });

  it("navigates indexed projects and sessions, filters catalog dates, and enables an exact message window", async () => {
    const recent = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const old = new Date(Date.now() - 120 * 24 * 60 * 60 * 1000).toISOString();
    const sessions = [
      catalogSession(PROJECT_A, SESSION_A, "Example Alpha", "Older planning", old),
      catalogSession(PROJECT_B, SESSION_B, "Example Beta", "Recent implementation", recent),
    ];
    const enableModelEnsembleWatch = vi.fn(async () => watchSnapshot(25));
    const listCodexSessions = vi.fn(async () => ({ sessions, limit: 100, offset: 0 }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      listCodexSessions,
      getActiveModelEnsembleWatch: vi.fn().mockRejectedValue({ status: 404 }),
      enableModelEnsembleWatch,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    await waitFor(() => expect(listCodexSessions).toHaveBeenCalledWith(100, 0, expect.any(AbortSignal)));
    expect(enableModelEnsembleWatch).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Session catalog date"), { target: { value: "7" } });
    await waitFor(() => expect(screen.getByLabelText("Watch project")).toHaveValue(PROJECT_B));
    expect(screen.queryByRole("option", { name: "Example Alpha" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Recent implementation/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Analysis message window"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Watch selected session" }));

    await waitFor(() => expect(enableModelEnsembleWatch).toHaveBeenCalledWith(
      SESSION_B,
      {
        project_id: PROJECT_B,
        max_messages: 25,
        confirmation: "continuously_analyze_selected_redacted_session",
      },
    ));
    expect(await screen.findByText(/Newest 25 messages · waiting for the serial local model lane/i)).toBeVisible();
    expect(screen.queryByText(/generation 0/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByText(/exact within-session date cutoffs/i)).toBeVisible();
  });

  it("navigates published radar history and overlays only a comparable prior receipt", async () => {
    const head = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const older = radarRun("7".repeat(64), 0, "2040-01-02T09:00:00Z");
    const snapshot = watchSnapshot(25, head);
    snapshot.watch.state = "idle";
    snapshot.watch.generation = 4;
    snapshot.watch.progress_completed = 10;
    const getModelEnsembleTrajectory = vi.fn(async () => trajectoryPage(head, older));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => snapshot),
      getModelEnsembleTrajectory,
    };

    render(<ModelEnsembleOverlay transport={transport} />);

    expect(await screen.findByText("Live published head")).toBeVisible();
    await waitFor(() => expect(getModelEnsembleTrajectory).toHaveBeenCalledWith(
      "d".repeat(64),
      24,
      undefined,
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/Dashed geometry marks previous comparable publication where numeric values exist/i)).toBeVisible();
    expect(document.querySelectorAll(".model-ensemble__radar-prior-segment")).toHaveLength(0);
    expect(document.querySelectorAll(".model-ensemble__radar-prior-point")).toHaveLength(1);
    expect(document.querySelectorAll(".model-ensemble__radar-state")).toHaveLength(5);

    fireEvent.click(screen.getByText("History"));
    fireEvent.click(screen.getByRole("button", { name: "Open earlier snapshot 2" }));
    expect(await screen.findByText("Earlier published snapshot")).toBeVisible();
    expect(screen.getByText(/Aggregate-only history point/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open live snapshot" }));
    expect(await screen.findByText("Live published head")).toBeVisible();
  });

  it("exposes an explicit analyze-now action with durable watch status", async () => {
    const head = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const idle = watchSnapshot(25, head);
    idle.watch.state = "idle";
    idle.watch.generation = 4;
    idle.watch.progress_completed = 10;
    const queued = structuredClone(idle);
    queued.watch.state = "queued";
    queued.watch.next_check_at = "2040-01-02T10:00:02Z";
    const refreshModelEnsembleWatch = vi.fn(async () => queued);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => idle),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(
        head,
        radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z"),
      )),
      refreshModelEnsembleWatch,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Analyze now" }));

    await waitFor(() => expect(refreshModelEnsembleWatch).toHaveBeenCalledWith("d".repeat(64)));
    expect(await screen.findByRole("button", { name: /Analysis queued/i })).toBeDisabled();
  });

  it("queues once on a repeated Analyze click and keeps the separate Cancel control disarmed briefly", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const run = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const initialHead = idleCanonicalHead(run);
    const nextHead = canonicalHead(run);
    let resolveEnqueue: ((value: ModelEnsembleCanonicalHead) => void) | undefined;
    const enqueueModelEnsembleAnalysis = vi.fn(() => new Promise<ModelEnsembleCanonicalHead>((resolve) => {
      resolveEnqueue = resolve;
    }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => initialHead),
      getModelEnsembleSnapshot: vi.fn(async () => run),
      enqueueModelEnsembleAnalysis,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    const analyze = await screen.findByRole("button", { name: "Analyze now" });
    fireEvent.click(analyze);
    fireEvent.click(analyze);
    expect(enqueueModelEnsembleAnalysis).toHaveBeenCalledTimes(1);
    await act(async () => resolveEnqueue?.(nextHead));

    const cancel = await screen.findByRole("button", { name: "Cancel analysis" });
    expect(cancel).toBeDisabled();
    expect(cancel).toHaveAttribute("title", expect.stringMatching(/available a moment/i));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CANCEL_ARMING_DELAY_MS);
    });
    expect(screen.getByRole("button", { name: "Cancel analysis" })).toBeEnabled();
    vi.useRealTimers();
  });

  it("uses the canonical head for dynamic stage status, heavy snapshot changes, and real cancellation", async () => {
    const headRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const cancellationHeadRun = radarRun("9".repeat(64), 0, "2040-01-02T10:00:01Z");
    const runningHead = canonicalHead(headRun);
    const cancelledHead = canonicalHead(cancellationHeadRun, "cancelled");
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) =>
      runId === headRun.run_id ? headRun : cancellationHeadRun);
    const cancelModelEnsembleAnalysis = vi.fn(async () => cancelledHead);
    const getActiveModelEnsembleWatch = vi.fn();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => runningHead),
      getModelEnsembleSnapshot,
      cancelModelEnsembleAnalysis,
      getActiveModelEnsembleWatch,
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(
        headRun,
        radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z"),
      )),
    };

    render(<ModelEnsembleOverlay transport={transport} />);

    expect((await screen.findAllByText("Updating · 1/6 pipeline steps")).length).toBeGreaterThanOrEqual(1);
    expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(headRun.run_id, expect.any(AbortSignal));
    expect(getActiveModelEnsembleWatch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel analysis" }));
    await waitFor(() => expect(cancelModelEnsembleAnalysis).toHaveBeenCalledWith("d".repeat(64)));
    expect(await screen.findByText("0% signal")).toBeVisible();
    expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(cancellationHeadRun.run_id);
    fireEvent.click(screen.getByText("Models"));
    expect(screen.getByText("Experimental cases evaluated").parentElement).toHaveTextContent("20");
    expect(screen.getByText("Experimental cases contributed").parentElement).toHaveTextContent("14");
    expect((await screen.findAllByText(/Analysis cancelled · last valid snapshot retained/i)).length).toBeGreaterThanOrEqual(1);
  });

  it("atomically replaces the sealed run when enqueue returns a newer exact head", async () => {
    const oldRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const newRun = radarRun("9".repeat(64), 0, "2040-01-02T10:00:01Z");
    const initialHead = idleCanonicalHead(oldRun);
    const enqueueHead = canonicalHead(newRun);
    enqueueHead.watch.state = "queued";
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) => runId === oldRun.run_id ? oldRun : newRun);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => initialHead),
      getModelEnsembleSnapshot,
      enqueueModelEnsembleAnalysis: vi.fn(async () => enqueueHead),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(
        oldRun,
        radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z"),
      )),
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    expect(await screen.findByText("100% signal")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Analyze now" }));

    expect(await screen.findByText("0% signal")).toBeVisible();
    expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(newRun.run_id);
  });

  it("does not let a superseded poll overwrite the exact head returned by an analysis command", async () => {
    const oldRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const newRun = radarRun("9".repeat(64), 0, "2040-01-02T10:00:01Z");
    const oldHead = idleCanonicalHead(oldRun);
    const commandHead = canonicalHead(newRun);
    let resolveStalePoll: ((value: ModelEnsembleCanonicalHead) => void) | undefined;
    const getActiveModelEnsembleCanonicalHead = vi.fn()
      .mockResolvedValueOnce(oldHead)
      .mockImplementationOnce(() => new Promise<ModelEnsembleCanonicalHead>((resolve) => {
        resolveStalePoll = resolve;
      }))
      .mockResolvedValue(commandHead);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead,
      getModelEnsembleSnapshot: vi.fn(async (runId: string) => runId === oldRun.run_id ? oldRun : newRun),
      enqueueModelEnsembleAnalysis: vi.fn(async () => commandHead),
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    expect(await screen.findByText("100% signal")).toBeVisible();
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(getActiveModelEnsembleCanonicalHead).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Analyze now" }));
    expect(await screen.findByText("0% signal")).toBeVisible();

    await act(async () => resolveStalePoll?.(oldHead));
    expect(screen.getByText("0% signal")).toBeVisible();
    expect(screen.queryByText("100% signal")).not.toBeInTheDocument();
  });

  it("retries when an immutable snapshot does not match the canonical head run id", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const wrongRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const exactRun = radarRun("9".repeat(64), 0, "2040-01-02T10:00:01Z");
    const head = idleCanonicalHead(exactRun);
    const getModelEnsembleSnapshot = vi.fn()
      .mockResolvedValueOnce(wrongRun)
      .mockResolvedValue(exactRun);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => head),
      getModelEnsembleSnapshot,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("100% signal")).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CANONICAL_POLL_WRONG_RUN_MS);
    });
    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("0% signal")).toBeVisible();
    vi.useRealTimers();
  });

  it("clears the old sealed run when enqueue returns an intentional null head", async () => {
    const oldRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const initialHead = idleCanonicalHead(oldRun);
    const emptyHead = canonicalHead(oldRun);
    emptyHead.watch.state = "queued";
    emptyHead.watch.has_result = false;
    emptyHead.head_run_id = null;
    emptyHead.head_generation = null;
    const getModelEnsembleSnapshot = vi.fn(async () => oldRun);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => initialHead),
      getModelEnsembleSnapshot,
      enqueueModelEnsembleAnalysis: vi.fn(async () => emptyHead),
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    expect(await screen.findByText("100% signal")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Analyze now" }));

    expect(await screen.findByText(/first typed measurement and experimental model range have not completed/i)).toBeVisible();
    expect(screen.queryByText("100% signal")).not.toBeInTheDocument();
  });

  it("keeps Analyze disabled while a canonical watch is queued", async () => {
    const headRun = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const queuedHead = canonicalHead(headRun);
    queuedHead.watch.state = "queued";
    queuedHead.latest_attempt = {
      ...queuedHead.latest_attempt!,
      state: "completed",
      published_run_id: headRun.run_id,
      completed_at: "2040-01-02T10:00:02Z",
    };
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead: vi.fn(async () => queuedHead),
      getModelEnsembleSnapshot: vi.fn(async () => headRun),
    };
    render(<ModelEnsembleOverlay transport={transport} />);

    const queuedButton = await screen.findByRole("button", { name: "Analysis queued…" });
    expect(queuedButton).toBeDisabled();
    expect((await screen.findAllByText("Queued · waiting for the local model lane")).length).toBeGreaterThanOrEqual(1);
  });

  it("does not let a refresh revoke an active serial model lease", async () => {
    const head = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const running = watchSnapshot(25, head);
    running.watch.state = "running";
    running.watch.progress_completed = 3;
    const refreshModelEnsembleWatch = vi.fn(async () => running);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => running),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(
        head,
        radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z"),
      )),
      refreshModelEnsembleWatch,
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    const runningButton = await screen.findByRole("button", {
      name: /Analysis running · 3\/10/i,
    });

    expect(runningButton).toBeDisabled();
    fireEvent.click(runningButton);
    expect(refreshModelEnsembleWatch).not.toHaveBeenCalled();
    expect(await screen.findByText("Live published head")).toBeVisible();
  });

  it("explains a fixed local failure and offers an explicit retry", async () => {
    const head = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const failed = watchSnapshot(25, head);
    failed.watch.state = "failed";
    failed.watch.last_error_code = "local_model_ensemble_execution_failed";
    failed.watch.next_check_at = "2040-01-02T10:01:00Z";
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => failed),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(
        head,
        radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z"),
      )),
      refreshModelEnsembleWatch: vi.fn(async () => failed),
    };

    render(<ModelEnsembleOverlay transport={transport} />);

    expect(await screen.findByText(/a local model stage did not complete/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry analysis" })).toBeEnabled();
    expect(await screen.findByText("Live published head")).toBeVisible();
  });

  it("advances a live-following radar when a new watch head is published", async () => {
    const firstHead = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const older = radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z");
    const secondHead = radarRun("9".repeat(64), 0, "2040-01-02T11:00:00Z");
    let currentSnapshot = watchSnapshot(25, firstHead);
    currentSnapshot.watch.state = "idle";
    let currentTrajectory = trajectoryPage(firstHead, older);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => currentSnapshot),
      getModelEnsembleTrajectory: vi.fn(async () => currentTrajectory),
    };

    render(<ModelEnsembleOverlay transport={transport} />);
    expect(await screen.findByText("100% signal")).toBeVisible();

    currentSnapshot = watchSnapshot(25, secondHead);
    currentSnapshot.watch.state = "idle";
    currentSnapshot.watch.generation = 5;
    currentSnapshot.watch.progress_completed = 10;
    currentTrajectory = trajectoryPage(secondHead, firstHead);
    document.dispatchEvent(new Event("visibilitychange"));

    expect(await screen.findByText("0% signal")).toBeVisible();
    expect(await screen.findByText("Live published head")).toBeVisible();
  });

  it("never lets stale trajectory history override a newer exact watch head", async () => {
    const liveHead = radarRun("9".repeat(64), 0, "2040-01-02T11:00:00Z");
    const staleHead = radarRun("8".repeat(64), 1, "2040-01-02T10:00:00Z");
    const older = radarRun("7".repeat(64), 1, "2040-01-02T09:00:00Z");
    const snapshot = watchSnapshot(25, liveHead);
    snapshot.watch.state = "idle";
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: vi.fn(async () => snapshot),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryPage(staleHead, older)),
    };

    render(<ModelEnsembleOverlay transport={transport} />);

    expect(await screen.findByText("0% signal")).toBeVisible();
    expect(await screen.findByText(/Trajectory history is temporarily unavailable/i)).toBeVisible();
    expect(screen.queryByText("Live published head")).not.toBeInTheDocument();
  });
});
