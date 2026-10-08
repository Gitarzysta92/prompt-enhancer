import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelEnsembleRun } from "../../shared/api/contracts";
import { MetricWorkspace } from "./MetricWorkspace";
import {
  modelEnsembleAxisPlottedLabel,
  modelEnsembleAxisRawRateLabel,
  modelEnsembleMetricStateLabel,
  modelEnsembleRadarAxes,
  type ModelEnsembleRadarData,
} from "./metricAxisModel";

type TypedMetric = ModelEnsembleRun["typed_metrics"][number];
type CommitteeMetric = ModelEnsembleRun["metrics"][number];

function typedMetric(metricKey: string, patch: Partial<TypedMetric>): TypedMetric {
  return {
    metric_key: metricKey,
    value_state: "known",
    numeric_value: 0.5,
    numerator: 1,
    denominator: 2,
    coverage: 1,
    observed_message_count: 2,
    eligible_message_count: 2,
    projection_source: "deterministic_typed_contract",
    explanation_code: "typed_requirement_ratio",
    ...patch,
  } as unknown as TypedMetric;
}

function committeeMetric(metricKey: string, patch: Partial<CommitteeMetric> = {}): CommitteeMetric {
  return {
    metric_key: metricKey,
    value_state: "known",
    numerator: 1,
    denominator: 2,
    numeric_value: 0.5,
    known_chunk_count: 2,
    abstained_chunk_count: 0,
    unsupported_chunk_count: 0,
    failed_chunk_count: 0,
    total_chunk_count: 4,
    explanation_code: "example_ratio_of_chunks",
    calibration_state: "not_assessed",
    product_metric_eligible: false,
    ...patch,
  };
}

const run: ModelEnsembleRadarData = {
  metrics: [],
  chunk_metrics: [],
  typed_metrics: [
    typedMetric("collaboration.ambiguity_resolution", { numeric_value: 0.25, numerator: 1, denominator: 4 }),
    typedMetric("collaboration.clarification_yield", { value_state: "unknown", numeric_value: null, numerator: null, denominator: null, explanation_code: "episode_horizon_open" }),
    typedMetric("collaboration.exploration_conversion", { value_state: "not_applicable", numeric_value: null, numerator: null, denominator: null }),
    typedMetric("collaboration.rework_candidate_rate", { numeric_value: 0.02, numerator: 2, denominator: 100 }),
  ],
  predictive_metrics: [],
};

const transport = { getModelPredictiveMetricDetail: vi.fn(() => new Promise<never>(() => undefined)) };

describe("metric workspace surfaces share one axis presentation", () => {
  it("partitions the canonical 20-contract receipt ledger without promoting state-only or missing entries", () => {
    render(
      <MetricWorkspace lensId="collaboration-flow" mode="full" onLensChange={vi.fn()} run={run} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    const summary = within(screen.getByLabelText("20-contract receipt summary"));
    expect(summary.getByText("Measured").nextElementSibling).toHaveTextContent("2/20");
    expect(summary.getByText("Legacy signals").nextElementSibling).toHaveTextContent("0");
    expect(summary.getByText("Pending").nextElementSibling).toHaveTextContent("1");
    expect(summary.getByText("N/A").nextElementSibling).toHaveTextContent("1");
    expect(summary.getByText("Unresolved").nextElementSibling).toHaveTextContent("0");
    expect(summary.getByText("No receipt").nextElementSibling).toHaveTextContent("16");
  });

  it("labels a legacy committee value as a signal instead of a typed measurement", () => {
    const legacyRun: ModelEnsembleRadarData = {
      ...run,
      metrics: [committeeMetric("collaboration.ambiguity_resolution")],
      typed_metrics: [],
    };
    render(
      <MetricWorkspace lensId="collaboration-flow" mode="full" onLensChange={vi.fn()} run={legacyRun} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    const summary = within(screen.getByLabelText("20-contract receipt summary"));
    expect(summary.getByText("Measured").nextElementSibling).toHaveTextContent("0/20");
    expect(summary.getByText("Legacy signals").nextElementSibling).toHaveTextContent("1");
    expect(summary.getByText("No receipt").nextElementSibling).toHaveTextContent("19");
    expect(within(screen.getByRole("region", { name: /exact metric values/i }))
      .getByRole("button", { name: /Ambiguity-resolution candidates/i })).toHaveTextContent("50% signal");
  });

  it("renders every nonnumeric state explicitly while preserving an authoritative numeric zero", () => {
    const stateRun: ModelEnsembleRadarData = {
      metrics: [],
      chunk_metrics: [],
      typed_metrics: [
        typedMetric("prompt.task_definition_coverage", { numeric_value: 0, numerator: 0, denominator: 2 }),
        typedMetric("prompt.problem_evidence_quality", { value_state: "unknown", numeric_value: null, numerator: null, denominator: null }),
        typedMetric("prompt.context_sufficiency", { value_state: "not_applicable", numeric_value: null, numerator: null, denominator: null }),
        typedMetric("prompt.constraint_precision", { value_state: "abstained", numeric_value: null, numerator: null, denominator: null }),
        typedMetric("prompt.acceptance_testability", { value_state: "execution_error", numeric_value: null, numerator: null, denominator: null }),
      ],
      predictive_metrics: [],
    };
    render(
      <MetricWorkspace lensId="task-framing" mode="full" onLensChange={vi.fn()} run={stateRun} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    const board = within(screen.getByRole("region", { name: /exact metric values/i }));
    expect(board.getByRole("button", { name: /Task definition coverage/i }).querySelector("b")).toHaveTextContent("0% measured");
    expect(board.getByRole("button", { name: /Problem evidence quality/i }).querySelector("b")).toHaveTextContent("Unknown");
    expect(board.getByRole("button", { name: /Context cue checks/i }).querySelector("b")).toHaveTextContent("N/A");
    expect(board.getByRole("button", { name: /Constraint precision candidates/i }).querySelector("b")).toHaveTextContent("Needs evidence");
    expect(board.getByRole("button", { name: /Acceptance testability cues/i }).querySelector("b")).toHaveTextContent("Error");
    expect(board.getByRole("button", { name: /Deliverable contract cues/i }).querySelector("b")).toHaveTextContent("No record");
  });

  it("defaults to authoritative evidence, preserves an explicit selection, and closes pinned context on snapshot change", () => {
    const mixedRun: ModelEnsembleRadarData = {
      metrics: [committeeMetric("prompt.task_definition_coverage")],
      chunk_metrics: [],
      typed_metrics: [typedMetric("prompt.problem_evidence_quality", {})],
      predictive_metrics: [],
    };
    const props = {
      lensId: "task-framing" as const,
      mode: "full" as const,
      onLensChange: vi.fn(),
      run: mixedRun,
      runId: "e".repeat(64),
      snapshotLabel: "Synthetic",
      transport,
    };
    const view = render(<MetricWorkspace {...props} />);
    const board = within(screen.getByRole("region", { name: /exact metric values/i }));
    expect(board.getByRole("button", { name: /Problem evidence quality/i })).toHaveAttribute("aria-pressed", "true");

    const chosen = board.getByRole("button", { name: /Context cue checks/i });
    fireEvent.click(chosen);
    expect(chosen).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Context cue checks knowledge card" })).toBeVisible();

    view.rerender(<MetricWorkspace {...props} runId={"f".repeat(64)} />);
    expect(screen.queryByRole("region", { name: "Context cue checks knowledge card" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /exact metric values/i }))
      .getByRole("button", { name: /Context cue checks/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("uses labeled regions and a grouped, keyboard-operable lens selector", () => {
    const onLensChange = vi.fn();
    render(
      <MetricWorkspace lensId="collaboration-flow" mode="full" onLensChange={onLensChange} run={run} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    expect(screen.getByRole("region", { name: /Metric workspace · Snapshot/i })).toBeVisible();
    expect(screen.getByRole("heading", { level: 3, name: /Metric workspace · Snapshot/i })).toBeVisible();
    expect(screen.getByRole("heading", { level: 4, name: /exact metric values/i })).toBeVisible();
    const lenses = screen.getByRole("group", { name: "Metric workspace view" });
    const buttons = within(lenses).getAllByRole("button");
    buttons[0].focus();
    expect(buttons[0]).toHaveFocus();
    fireEvent.keyDown(buttons[0], { key: "ArrowRight" });
    expect(onLensChange).toHaveBeenLastCalledWith("collaboration-flow");
    fireEvent.keyDown(buttons[0], { key: "End" });
    expect(onLensChange).toHaveBeenLastCalledWith("outcome-evidence");
    fireEvent.keyDown(buttons[3], { key: "Home" });
    expect(onLensChange).toHaveBeenLastCalledWith("task-framing");
  });

  it("describes comparison geometry only when the selected lens has comparable numeric values", () => {
    const stateOnlyComparison: ModelEnsembleRadarData = {
      metrics: [],
      chunk_metrics: [],
      typed_metrics: [typedMetric("collaboration.ambiguity_resolution", {
        value_state: "unknown", numeric_value: null, numerator: null, denominator: null,
      })],
      predictive_metrics: [],
    };
    const props = {
      comparisonLabel: "Reviewed baseline",
      comparisonRun: stateOnlyComparison,
      lensId: "collaboration-flow" as const,
      mode: "full" as const,
      onLensChange: vi.fn(),
      run,
      runId: "e".repeat(64),
      snapshotLabel: "Synthetic",
      transport,
    };
    const view = render(<MetricWorkspace {...props} />);
    expect(screen.getByText("No numeric comparison is available for Reviewed baseline in this lens.")).toBeVisible();
    expect(screen.queryByText(/Dashed geometry marks/i)).not.toBeInTheDocument();

    view.rerender(<MetricWorkspace {...props} comparisonRun={run} />);
    expect(screen.getByText("Dashed geometry marks Reviewed baseline where numeric values exist.")).toBeVisible();
  });

  it("lets the compact axis strip select every metric, including state-only axes", () => {
    render(
      <MetricWorkspace lensId="collaboration-flow" mode="compact" onLensChange={vi.fn()} run={run} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    const strip = within(screen.getByRole("navigation", { name: "Collaboration flow metric axes" })).getAllByRole("button");

    for (const button of strip) {
      fireEvent.click(button);
      expect(button).toHaveAttribute("aria-pressed", "true");
    }
  });

  it("keeps radar orientation in the plot and promotes the raw measured value in the exact-value board", () => {
    render(
      <MetricWorkspace lensId="collaboration-flow" mode="full" onLensChange={vi.fn()} run={run} runId={"e".repeat(64)} snapshotLabel="Synthetic" transport={transport} />,
    );
    const axes = modelEnsembleRadarAxes(run, "collaboration-flow");
    const strip = within(screen.getByRole("navigation", { name: "Collaboration flow metric axes" })).getAllByRole("button");
    const board = within(screen.getByRole("region", { name: /exact metric values/i })).getAllByRole("button");
    expect(strip).toHaveLength(axes.length);
    expect(board).toHaveLength(axes.length);

    axes.forEach((axis, index) => {
      const rawRate = modelEnsembleAxisRawRateLabel(axis);
      const stripValue = strip[index].querySelector("b")?.textContent;
      const stripSmalls = [...strip[index].querySelectorAll("small")].map((node) => node.textContent);
      const boardStatus = board[index].querySelector("small")?.textContent;
      expect(stripValue).toBe(modelEnsembleAxisPlottedLabel(axis));
      expect(strip[index]).toHaveClass(`is-${axis.metric === null ? "missing" : axis.metric.value_state === "unknown" && axis.metric.explanation_code === "episode_horizon_open" ? "pending" : axis.metric.value_state}`);
      const expectedStatus = modelEnsembleMetricStateLabel(axis.metric);
      const numericValue = axis.metric?.numeric_value;
      const boardCaption = rawRate === null || typeof numericValue !== "number"
        ? expectedStatus
        : `${expectedStatus} · radar orientation ${100 - Math.round(numericValue * 100)}%`;
      expect(boardStatus).toBe(boardCaption);
      if (rawRate === null) {
        expect(stripSmalls.some((text) => text?.startsWith("raw rate"))).toBe(false);
      } else {
        expect(stripSmalls).toContain(rawRate);
      }
      expect(strip[index].getAttribute("aria-describedby")).toBe(board[index].getAttribute("aria-describedby"));
    });

    const rework = axes.findIndex((axis) => axis.key === "collaboration.rework_candidate_rate");
    expect(strip[rework].querySelector("b")?.textContent).toBe("98% radar quality");
    expect(board[rework].querySelector("small")?.textContent).toBe("known · radar orientation 98%");
    expect(board[rework].querySelector("b")?.textContent).toBe("2% measured raw rate");
    const pending = axes.findIndex((axis) => axis.key === "collaboration.clarification_yield");
    expect(strip[pending].querySelector("b")?.textContent).toBe("Pending");
    expect(board[pending].querySelector("small")?.textContent).toBe("pending · horizon open");
    expect(board[pending].querySelector("b")?.textContent).toBe("Pending");
    const missing = axes.findIndex((axis) => axis.key === "collaboration.scope_change_discipline");
    expect(strip[missing].querySelector("b")?.textContent).toBe("No record");
    expect(board[missing].querySelector("b")?.textContent).toBe("No record");
    expect(board[missing].querySelector("small")?.textContent).toBe("not observed");
  });
});
