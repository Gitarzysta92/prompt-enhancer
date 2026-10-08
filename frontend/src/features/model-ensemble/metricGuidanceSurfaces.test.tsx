import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ModelEnsembleCanonicalHead,
  ModelEnsembleRun,
  ModelPredictiveMetricDetail,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import { MetricDefinitionsOutOfDateError, METRIC_V2_KEYS } from "../../shared/api/metricPublicationV2Contract";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import {
  syntheticMetricEvidenceReadinessV2,
  syntheticMetricPublicationV2,
  type MetricScenarioV2,
} from "../../test/metricPublicationV2Fixture";
import { CANONICAL_POLL_IDLE_MS } from "./canonicalPolling";
import { MetricWorkspace } from "./MetricWorkspace";
import { ModelEnsembleOverlay } from "./ModelEnsembleOverlay";
import { ModelEnsemblePanel } from "./ModelEnsemblePanel";
import {
  modelEnsembleAxisGuidanceSentences,
  modelEnsembleKnowledgeEntries,
  modelEnsembleRadarAxes,
  type ModelEnsembleRadarData,
} from "./metricAxisModel";

const SCENARIOS: Partial<Record<typeof METRIC_V2_KEYS[number], MetricScenarioV2>> = {
  "prompt.task_definition_coverage": { value_state: "known", numerator: 3, denominator: 4, state_class: "known_retain" },
  "prompt.problem_evidence_quality": { value_state: "known", numerator: 1, denominator: 4, state_class: "known_improve" },
  "prompt.context_sufficiency": {
    value_state: "known", numerator: 1, denominator: 3, state_class: "known_improve",
    factor_evidence: "per_factor_measured", focus_factor_keys: ["current_state", "boundary"],
  },
  "prompt.constraint_precision": { value_state: "pending", eligible: 4, pending: 2, numerator: 1 },
  "prompt.acceptance_testability": { value_state: "not_applicable" },
  "prompt.deliverable_contract": { value_state: "abstained" },
  "collaboration.ambiguity_resolution": { value_state: "execution_error" },
  "outcome.first_pass_verification": { value_state: "known", numerator: 1, denominator: 1, state_class: "known_retain" },
  "outcome.verified_requirement_coverage": { value_state: "known", numerator: 2, denominator: 3, state_class: "known_improve" },
  "logic.hypothesis_test_linkage": { value_state: "unknown", eligible: 2, unknown: 1, capability_available: true },
  "logic.requirement_action_traceability": { value_state: "unknown", eligible: 0, capability_available: true },
};

function v2Run(runId = "e".repeat(64)): ModelEnsembleRun {
  return {
    run_id: runId,
    completed_at: "2040-01-02T10:00:00Z",
    source_coverage_state: "complete_window",
    metrics: [],
    chunk_metrics: [],
    typed_metrics: [],
    metric_projection_version: null,
    metric_projection_completed_at: null,
    metric_publication_v2: syntheticMetricPublicationV2(SCENARIOS),
    metric_profile_binding: null,
    predictive_projection_version: null,
    predictive_projected_at: null,
    predictive_metrics: [],
    predictive_model_stages: [],
  } as unknown as ModelEnsembleRun;
}

const transport = { getModelPredictiveMetricDetail: vi.fn(() => new Promise<never>(() => undefined)) };

function workspace(
  mode: "full" | "compact",
  run: ModelEnsembleRadarData = v2Run(),
  workspaceTransport: Pick<PromptEnhancerTransport, "getModelPredictiveMetricDetail"> = transport,
  lensId: "task-framing" | "collaboration-flow" | "reasoning-trace" | "outcome-evidence" = "task-framing",
) {
  return render(
    <MetricWorkspace lensId={lensId} mode={mode} onLensChange={vi.fn()} run={run} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={workspaceTransport} />,
  );
}

function inspectorSentences(): { meaning: string; action: string } {
  const inspector = document.querySelector(".metric-inspector-sentences")!;
  const [meaning, action] = [...inspector.querySelectorAll("p")].map((node) => node.textContent?.replace(/^(Meaning|Next)/u, "") ?? "");
  return { meaning, action };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("canonical V2 guidance across the workspace surfaces", () => {
  it("renders the board action, the inspector action, and the ARIA description from the same sealed guidance receipt", () => {
    const run = v2Run();
    workspace("full", run);
    const axes = modelEnsembleRadarAxes(run, "task-framing");
    const board = within(screen.getByRole("region", { name: /exact metric values/i })).getAllByRole("button");
    const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button");
    axes.forEach((axis, index) => {
      const sentences = modelEnsembleAxisGuidanceSentences(axis);
      expect(board[index].querySelector(".metric-workspace__board-action")?.textContent, axis.key).toBe(sentences.action);
      // Selecting the axis shows the identical action in the radar inspector.
      fireEvent.click(strip[index]);
      expect(inspectorSentences(), axis.key).toEqual({ meaning: sentences.meaning, action: sentences.action });
      // The always-present hidden description carries the same two sentences.
      const description = document.getElementById(strip[index].getAttribute("aria-describedby")!)!;
      expect(description.textContent, axis.key).toContain(sentences.meaning);
      expect(description.textContent, axis.key).toContain(sentences.action);
    });
    // The retain receipt at 3/4 retains even though one cue was not met.
    const retain = axes.findIndex((axis) => axis.key === "prompt.task_definition_coverage");
    expect(board[retain].querySelector(".metric-workspace__board-action")?.textContent).toMatch(/^Retain: keep the practice/u);
    expect(board[retain]).toHaveAttribute("data-guidance-kind", "measured");
    // The per-factor improve receipt names at most two measured factors.
    const focus = axes.findIndex((axis) => axis.key === "prompt.context_sufficiency");
    expect(board[focus].querySelector(".metric-workspace__board-action")?.textContent).toMatch(/^Focus on current state and boundary/u);
  });

  it("shows exact pending censoring bounds on the strip, the board, the inspector, and the description", () => {
    const run = v2Run();
    workspace("full", run);
    const axes = modelEnsembleRadarAxes(run, "task-framing");
    const pending = axes.findIndex((axis) => axis.key === "prompt.constraint_precision");
    const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button");
    const board = within(screen.getByRole("region", { name: /exact metric values/i })).getAllByRole("button");
    expect(strip[pending].querySelector("b")?.textContent).toBe("Pending");
    expect([...strip[pending].querySelectorAll("small")].map((node) => node.textContent)).toContain("bounds 25%–75%");
    expect(board[pending].querySelector("small")?.textContent).toBe("pending · horizon open · bounds 25%–75%");
    fireEvent.click(strip[pending]);
    expect(inspectorSentences().meaning).toMatch(/lower bound of 25% and an upper bound of 75%/u);
    expect(document.querySelector(".model-ensemble__focused-metric")?.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByText("Censoring bounds").nextElementSibling?.textContent).toBe("25%–75%");
    const description = document.getElementById(strip[pending].getAttribute("aria-describedby")!)!;
    expect(description.textContent).toMatch(/lower bound of 25% and an upper bound of 75%/u);
    // Pending stays unplotted: a state marker, never a numeric point.
    expect(axes[pending].plotted).toBeNull();
  });

  it("keeps board, inspector, and ARIA guidance identical when an experimental detail is visible", async () => {
    const prediction = {
      metric_key: "prompt.task_definition_coverage",
      target: "metric_value",
      state: "experimental",
      mean: 0.5,
      median: 0.5,
      q05: 0.2,
      q25: 0.4,
      q75: 0.6,
      q95: 0.8,
      applicability_probability: 0.9,
      pending_probability: 0.05,
      model_disagreement: 0.2,
      effective_observation_count: 2,
      model_set_version: "example-model-set-v1",
      calibration_version: "not-calibrated-v1",
      contract_version: "example-contract-v1",
      contract_fingerprint: "a".repeat(64),
      product_metric_eligible: false,
    } as const;
    const run = {
      ...v2Run(),
      predictive_metrics: [prediction],
      predictive_model_stages: [
        { model_key: "mdeberta_xnli", repository_id: "example.invalid/mdeberta", status: "completed" },
        { model_key: "minilm_challenger", repository_id: "example.invalid/minilm", status: "completed" },
      ],
    } as unknown as ModelEnsembleRun;
    const detailTransport: Pick<PromptEnhancerTransport, "getModelPredictiveMetricDetail"> = {
      getModelPredictiveMetricDetail: vi.fn(async (): Promise<ModelPredictiveMetricDetail> => ({
        run_id: run.run_id,
        projection_version: "local-probabilistic-radar-v1",
        projected_at: "2040-01-02T10:00:02Z",
        metric: prediction,
        density_bins: Array.from({ length: 20 }, () => 0.05),
        factors: [
          { factor_key: "goal_cue", scale: "binary", weight: 1, applicability_probability: 0.9, present_probability: 0.1, neutral_probability: 0.2, absent_probability: 0.7, expert_count: 2, critical: true },
          { factor_key: "target_cue", scale: "binary", weight: 1, applicability_probability: 0.9, present_probability: 0.2, neutral_probability: 0.2, absent_probability: 0.6, expert_count: 2, critical: true },
        ],
        experimental_label: "Experimental model range",
        local_only: true,
        content_persisted: false,
        universal_trust_percentage_available: false,
      })),
    };
    const fullView = workspace("full", run, detailTransport);
    const axes = modelEnsembleRadarAxes(run, "task-framing");
    const expected = modelEnsembleAxisGuidanceSentences(axes[0]);
    const board = within(screen.getByRole("region", { name: /exact metric values/i })).getAllByRole("button")[0];
    const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button")[0];
    fireEvent.click(strip);
    await waitFor(() => expect(detailTransport.getModelPredictiveMetricDetail).toHaveBeenCalled());
    expect(inspectorSentences()).toEqual({ meaning: expected.meaning, action: expected.action });
    expect(board.querySelector(".metric-workspace__board-action")?.textContent).toBe(expected.action);
    const description = document.getElementById(strip.getAttribute("aria-describedby")!)!;
    expect(description.textContent).toContain(expected.meaning);
    expect(description.textContent).toContain(expected.action);
    expect(`${expected.meaning} ${expected.action}`).not.toMatch(/goal cue|target cue|lowest for/u);
    expect(document.querySelector(".model-ensemble__focused-metric")?.querySelectorAll("p")).toHaveLength(2);
    expect(screen.getByText("Experimental estimate")).toBeVisible();
    expect(strip).toHaveTextContent("◇ 50% radar-quality estimate");

    fullView.unmount();
    workspace("compact", run, detailTransport);
    const compactStrip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button")[0];
    fireEvent.click(compactStrip);
    expect(screen.getByText("Experimental estimate")).toBeVisible();
    expect(compactStrip).toHaveTextContent("◇ 50% radar-quality estimate");
    expect(inspectorSentences()).toEqual({ meaning: expected.meaning, action: expected.action });
  });

  it("publishes the objective measured count of five in the workspace header", () => {
    workspace("full");
    const header = document.querySelector(".metric-workspace__snapshot dl")!;
    expect(within(header as HTMLElement).getByText("Objective measured").nextElementSibling?.textContent).toBe("2/5");
    expect(within(header as HTMLElement).getByText("Measured").nextElementSibling?.textContent).toBe("5/20");
  });

  it("shows exact proof-contributor readiness only when it is bound to the sealed publication", () => {
    const publication = syntheticMetricPublicationV2({
      "prompt.task_definition_coverage": { value_state: "unknown", capability_available: false },
    });
    const readiness = syntheticMetricEvidenceReadinessV2(publication);
    const run = {
      ...v2Run(),
      metric_publication_v2: publication,
      metric_evidence_readiness_v2: readiness,
    } as ModelEnsembleRun & ModelEnsembleRadarData;
    const view = workspace("full", run);
    expect(screen.getByText("Capability gaps").nextElementSibling?.textContent).toBe(`${readiness.capability_missing_count}/20`);
    expect(screen.getByText("Objective measurable").nextElementSibling?.textContent).toBe("0/5");
    const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button")[0];
    fireEvent.pointerEnter(strip);
    const card = screen.getByRole("region", { name: "Task definition coverage knowledge card" });
    expect(card).toHaveTextContent("0/2 proof contributors observed (evidence families, not people)");
    expect(card).toHaveTextContent("missing: focus owned request revision, rubric factor calculator");
    expect(card).toHaveTextContent("readiness capability missing");
    expect(card).toHaveTextContent("calibration not assessed · not product-metric eligible");
    fireEvent.click(strip);
    const inspector = document.querySelector(".model-ensemble__focused-metric")!;
    expect(inspector.textContent).toContain("Evidence readinesscapability missing");
    expect(inspector.textContent).toContain("Proof contributors0/2 observed");
    expect(inspector.textContent).toContain("Missing prooffocus owned request revision, rubric factor calculator");

    view.unmount();
    workspace("full", run, transport, "outcome-evidence");
    const objectiveAxes = modelEnsembleRadarAxes(run, "outcome-evidence");
    const objectiveIndex = objectiveAxes.findIndex((axis) => axis.key === "logic.hypothesis_test_linkage");
    const objectiveStrip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button")[objectiveIndex];
    fireEvent.click(objectiveStrip);
    expect(document.querySelector(".model-ensemble__focused-metric")?.textContent)
      .toContain("Adapter-required proof familieshypothesis opportunities, hypothesis evidence links, tool events, decision events, verification events · supplied by the adapter, not by user wording");
  });

  it("keeps full and compact modes on the same meaning and action for every axis", () => {
    const run = v2Run();
    const axes = modelEnsembleRadarAxes(run, "task-framing");
    const collect = (mode: "full" | "compact") => {
      const view = workspace(mode, run);
      const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button");
      const result = axes.map((_, index) => {
        fireEvent.click(strip[index]);
        return inspectorSentences();
      });
      view.unmount();
      return result;
    };
    expect(collect("compact")).toEqual(collect("full"));
    // Knowledge entries (cards + descriptions) are the same function again.
    expect(modelEnsembleKnowledgeEntries(axes).map((entry) => entry.guidance.action))
      .toEqual(axes.map((axis) => modelEnsembleAxisGuidanceSentences(axis).action));
  });

  it("distinguishes objective evidence, adapter capability, and unresolved receipts in full and compact modes", () => {
    const run = v2Run();
    const collect = (mode: "full" | "compact") => {
      const view = workspace(mode, run, transport, "outcome-evidence");
      const axes = modelEnsembleRadarAxes(run, "outcome-evidence");
      const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button");
      const sentenceFor = (metricKey: string) => {
        fireEvent.click(strip[axes.findIndex((axis) => axis.key === metricKey)]);
        return inspectorSentences();
      };
      const result = {
        unresolved: sentenceFor("logic.hypothesis_test_linkage"),
        evidenceMissing: sentenceFor("logic.requirement_action_traceability"),
        capabilityMissing: sentenceFor("outcome.agent_claim_grounding"),
      };
      view.unmount();
      return result;
    };
    const compact = collect("compact");
    const full = collect("full");
    expect(compact).toEqual(full);
    expect(full.unresolved.meaning).toMatch(/^Objective evidence unresolved:/u);
    expect(full.evidenceMissing.meaning).toMatch(/^Objective evidence missing:/u);
    expect(full.capabilityMissing.meaning).toMatch(/^Adapter capability missing:/u);
    for (const sentences of Object.values(full)) expect(sentences.action).toMatch(/ — verify: /u);
  });

  it("keeps unknown, not-applicable, abstained, and error unplotted while the objective-missing wording names adapter readiness", () => {
    const run = v2Run();
    workspace("full", run);
    const outcomeAxes = modelEnsembleRadarAxes(run, "outcome-evidence");
    for (const axis of outcomeAxes) {
      if (axis.metric?.value_state !== "known") expect(axis.plotted, axis.key).toBeNull();
    }
    const missing = outcomeAxes.find((axis) => axis.key === "outcome.agent_claim_grounding")!;
    const sentences = modelEnsembleAxisGuidanceSentences(missing);
    expect(sentences.meaning).toMatch(/current adapter cannot measure/u);
    expect(sentences.action).toMatch(/verify: adapter readiness/u);
  });

  it("does not describe rich knowledge cards as tooltips", () => {
    workspace("full");
    const strip = within(screen.getByRole("navigation", { name: /metric axes/ })).getAllByRole("button");
    fireEvent.pointerEnter(strip[0]);
    expect(document.querySelectorAll('[role="tooltip"]')).toHaveLength(0);
    const card = document.querySelector(".metric-knowledge-card")!;
    expect(card.getAttribute("role")).toBe("region");
    expect(card.textContent).toContain("Guidance basis");
  });

  it("does not invent a retain-or-improve decision for a compact history point that carries no guidance receipt", () => {
    const publication = syntheticMetricPublicationV2(SCENARIOS);
    const historyPoint = {
      metrics: [],
      chunk_metrics: [],
      typed_metrics: [],
      metric_states_v2: publication.metrics.map((item) => item.state),
    } as unknown as ModelEnsembleRadarData;
    const axis = modelEnsembleRadarAxes(historyPoint, "task-framing")[0];
    const sentences = modelEnsembleAxisGuidanceSentences(axis);
    expect(sentences.meaning).toMatch(/^Measured: 3\/4/u);
    expect(sentences.action).toMatch(/^No sealed guidance receipt travels with this compact history point/u);
    expect(sentences.basis).toBe("method-only");
  });
});

function idleHead(run: ModelEnsembleRun): ModelEnsembleCanonicalHead {
  return {
    schema_version: "analysis-snapshot-v2",
    watch: {
      watch_id: "d".repeat(64),
      provider: "codex",
      project_id: "a".repeat(64),
      session_id: "1".repeat(64),
      max_messages: 25,
      state: "idle",
      generation: 4,
      progress_completed: 10,
      progress_total: 10,
      has_result: true,
      last_error_code: null,
      next_check_at: "2040-01-02T10:01:00Z",
      updated_at: "2040-01-02T10:00:00Z",
      serial_model_execution: true,
      process_isolated_model_release: true,
      cuda_resource_retry_on_cpu: true,
      content_persisted: false,
      calibrated_as_truth: false,
    },
    head_run_id: run.run_id,
    head_generation: 4,
    latest_attempt: null,
    stages: [],
    content_persisted: false,
  } as unknown as ModelEnsembleCanonicalHead;
}

describe("definitions-out-of-date compatibility gate on the live surfaces", () => {
  it("replaces every value and guidance with the distinct update-client alert in the overlay, without reconnect wording", async () => {
    const goodRun = v2Run("8".repeat(64));
    const staleHead = idleHead(goodRun);
    const nextHead = idleHead(v2Run("9".repeat(64)));
    const getActiveModelEnsembleCanonicalHead = vi.fn()
      .mockResolvedValueOnce(staleHead)
      .mockResolvedValueOnce(nextHead)
      .mockResolvedValue(staleHead);
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) => {
      if (runId === goodRun.run_id) return goodRun;
      throw new MetricDefinitionsOutOfDateError("registry_version");
    });
    const overlayTransport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getActiveModelEnsembleCanonicalHead,
      getModelEnsembleSnapshot,
      getModelEnsembleTrajectory: vi.fn().mockRejectedValue({ status: 404 }),
    };
    render(<ModelEnsembleOverlay transport={overlayTransport} />);
    expect(await screen.findByText("Objective measured")).toBeVisible();

    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(getActiveModelEnsembleCanonicalHead).toHaveBeenCalledTimes(2));
    const alert = await screen.findByRole("alert", { name: "Metric definitions out of date" });
    expect(alert).toHaveAttribute("data-state", "definitions_out_of_date");
    expect(alert).toHaveAttribute("data-mismatch", "registry_version");
    expect(alert.textContent).toMatch(/update this client/u);
    expect(alert.textContent).toMatch(/0\/20 values shown · 0\/20 guidance receipts shown/u);
    // All twenty old values and their guidance are cleared, not shown beside the alert.
    expect(screen.queryByText("Objective measured")).toBeNull();
    expect(screen.queryByRole("navigation", { name: /metric axes/ })).toBeNull();
    expect(document.querySelector(".metric-inspector-sentences")).toBeNull();
    // Status line and alert both carry the update-client title; neither says "reconnecting".
    const titles = screen.getAllByText("Metric definitions are out of date · update this client");
    expect(titles).toHaveLength(2);
    expect(document.querySelector(".model-ensemble-overlay__connection")?.textContent).toBe("Metric definitions are out of date · update this client");
    expect(document.querySelector(".model-ensemble-overlay__connection")).not.toHaveClass("is-stale");
    expect(document.body.textContent).not.toMatch(/Reconnecting/u);

    // A compatible publication clears the alert again.
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(getActiveModelEnsembleCanonicalHead).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("Objective measured")).toBeVisible();
    expect(screen.queryByRole("alert", { name: "Metric definitions out of date" })).toBeNull();
  });

  it("clears the stored run and shows the alert in the dashboard panel", async () => {
    const goodRun = v2Run("8".repeat(64));
    const head = idleHead(goodRun);
    const staleHead = { ...head, head_run_id: "9".repeat(64) } as ModelEnsembleCanonicalHead;
    const getSessionModelEnsembleCanonicalHead = vi.fn()
      .mockResolvedValueOnce(head)
      .mockResolvedValue(staleHead);
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) => {
      if (runId === goodRun.run_id) return goodRun;
      throw new MetricDefinitionsOutOfDateError("contract_set_fingerprint");
    });
    const panelTransport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getSessionModelEnsembleCanonicalHead,
      getModelEnsembleSnapshot,
      getModelEnsembleTrajectory: vi.fn().mockRejectedValue({ status: 404 }),
    };
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <ModelEnsemblePanel
        analysisCapability={{ available: true, reason_code: null } as never}
        category="prompt-quality"
        compatibilityLoading={false}
        projectId={"a".repeat(64)}
        providerCompatibility={null}
        sessionId={"1".repeat(64)}
        transport={panelTransport}
      />,
    );
    expect(await screen.findByText("Objective measured")).toBeVisible();
    // The panel coordinator polls on its idle cadence; advance to the next poll.
    await act(async () => { await vi.advanceTimersByTimeAsync(CANONICAL_POLL_IDLE_MS + 100); });
    await waitFor(() => expect(getSessionModelEnsembleCanonicalHead.mock.calls.length).toBeGreaterThanOrEqual(2));
    const alert = await screen.findByRole("alert", { name: "Metric definitions out of date" });
    expect(alert).toHaveAttribute("data-mismatch", "contract_set_fingerprint");
    expect(screen.queryByText("Objective measured")).toBeNull();
    expect(screen.queryByRole("navigation", { name: /metric axes/ })).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/update this client/u);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "off");
    expect(screen.getAllByText("Metric definitions are out of date · update this client")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).not.toMatch(/reconnect|could not be validated/iu);
  });
});
