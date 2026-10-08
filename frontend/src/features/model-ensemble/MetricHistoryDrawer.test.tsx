import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelEnsembleTrajectoryPoint } from "../../shared/api/contracts";
import { MetricHistoryDrawer } from "./MetricHistoryDrawer";
import { MetricWorkspace, type MetricWorkspaceHistory } from "./MetricWorkspace";

const METRIC = "prompt.task_definition_coverage";
const REWORK = "collaboration.rework_avoidance";
type ReceiptState = "known" | "unknown" | "not_applicable" | "abstained" | "execution_error" | "pending";

function point(
  runId: string,
  generation: number,
  value: number | null,
  comparable = true,
  state: ReceiptState = value === null ? "unknown" : "known",
  metricKey = METRIC,
): ModelEnsembleTrajectoryPoint {
  return {
    generation,
    run_id: runId,
    published_at: `2040-01-${String(generation).padStart(2, "0")}T10:00:01Z`,
    completed_at: `2040-01-${String(generation).padStart(2, "0")}T10:00:00Z`,
    max_messages: 100,
    source_coverage_state: "complete_window",
    chunk_count: 1,
    comparable_to_head: comparable,
    metrics: [],
    typed_metrics: [{
      metric_key: metricKey,
      value_state: state,
      numeric_value: value,
      explanation_code: state === "pending" ? "episode_horizon_open" : "example_receipt_state",
    }],
    predictive_metrics: [],
  } as unknown as ModelEnsembleTrajectoryPoint;
}

function missingPoint(runId: string, generation: number): ModelEnsembleTrajectoryPoint {
  return { ...point(runId, generation, null), typed_metrics: [] } as unknown as ModelEnsembleTrajectoryPoint;
}

function history(points: readonly ModelEnsembleTrajectoryPoint[], selectedRunId: string | null = points[0]?.run_id ?? null): MetricWorkspaceHistory {
  return {
    points,
    headRunId: points[0]?.run_id ?? null,
    selectedRunId,
    onSelectRun: vi.fn(),
  };
}

describe("MetricHistoryDrawer", () => {
  it("states that history is not exposed instead of drawing an empty chart", () => {
    render(<MetricHistoryDrawer direction="higher_is_better" metricKey={METRIC} />);
    expect(screen.getByText("History").parentElement).toHaveTextContent("Not exposed for this receipt");
    expect(screen.getByText(/content-free trajectory/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /sealed snapshot history/i })).not.toBeInTheDocument();
  });

  it("renders every sealed snapshot with current, selected, identity, comparability, and numeric/state truth", () => {
    const onSelectRun = vi.fn();
    const points = [
      point("9".repeat(64), 4, 1),
      point("8".repeat(64), 3, null),
      point("7".repeat(64), 2, 0.5, false),
    ];
    const value: MetricWorkspaceHistory = {
      points,
      headRunId: points[0].run_id,
      selectedRunId: points[2].run_id,
      onSelectRun,
      error: true,
    };
    render(<MetricHistoryDrawer direction="higher_is_better" history={value} metricKey={METRIC} />);

    expect(screen.getByText("History").parentElement).toHaveTextContent("3 sealed snapshots");
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByText("History").closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("status")).toHaveTextContent(/showing 3 previously loaded sealed snapshots/i);
    expect(screen.getByText(/state-only and missing receipts stay outside the chart/i)).toBeInTheDocument();
    const chart = screen.getByRole("img", { name: "Selected metric history" });
    expect(chart).toHaveAttribute("data-numeric-count", "2");
    // The unknown middle point and the scope break prevent numeric connections.
    expect(chart.querySelectorAll("line.metric-history__segment")).toHaveLength(0);
    expect(chart.querySelectorAll("circle")).toHaveLength(2);
    expect(chart.querySelectorAll("circle.is-selected")).toHaveLength(1);

    const snapshots = screen.getByRole("list", { name: /sealed snapshot history/i });
    expect(within(snapshots).getAllByRole("listitem")).toHaveLength(3);
    const current = screen.getByRole("button", { name: "Open live snapshot" });
    const stateOnly = screen.getByRole("button", { name: "Open earlier snapshot 2" });
    const selected = screen.getByRole("button", { name: "Open earlier snapshot 3" });
    expect(current).toHaveAttribute("aria-pressed", "false");
    expect(current).toHaveTextContent("Current · generation 4");
    expect(current).toHaveTextContent("run 99999999…9999");
    expect(current).toHaveTextContent("Numeric · 100%");
    expect(current).toHaveTextContent("Current comparison baseline");
    expect(stateOnly).toHaveTextContent("State only · Unknown");
    expect(stateOnly).toHaveTextContent("Comparable to current");
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(selected).toHaveTextContent("Selected");
    expect(selected).toHaveTextContent("Scope break · not comparable");
    fireEvent.click(stateOnly);
    expect(onSelectRun).toHaveBeenCalledWith(points[1].run_id);
  });

  it("does not draw an all-state trajectory and labels each nonnumeric state without substituting zero", () => {
    const points = [
      point("9".repeat(64), 7, null, true, "unknown"),
      point("8".repeat(64), 6, null, true, "not_applicable"),
      point("7".repeat(64), 5, null, true, "abstained"),
      point("6".repeat(64), 4, null, true, "execution_error"),
      point("5".repeat(64), 3, null, true, "pending"),
      point("4".repeat(64), 2, null, true, "known"),
      missingPoint("3".repeat(64), 1),
    ];
    render(<MetricHistoryDrawer direction="higher_is_better" history={history(points)} metricKey={METRIC} />);
    fireEvent.click(screen.getByText("History"));

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("note", { name: "" })).toHaveTextContent(/no numeric receipts/i);
    for (const label of ["Unknown", "N/A", "Needs evidence", "Error", "Pending", "No numeric value", "No record"]) {
      expect(screen.getByText(`State only · ${label}`)).toBeInTheDocument();
    }
    expect(screen.queryByText(/Numeric · 0%/)).not.toBeInTheDocument();
  });

  it("lists every loaded snapshot instead of silently truncating after eight", () => {
    const points = Array.from({ length: 10 }, (_, index) => point(
      String(9 - index).repeat(64),
      10 - index,
      (10 - index) / 10,
    ));
    render(<MetricHistoryDrawer direction="higher_is_better" history={history(points)} metricKey={METRIC} />);
    expect(screen.getByText("History").parentElement).toHaveTextContent("10 sealed snapshots");
    fireEvent.click(screen.getByText("History"));
    expect(within(screen.getByRole("list", { name: /sealed snapshot history/i })).getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Open earlier snapshot 10" })).toHaveTextContent("generation 1");
  });

  it("shows lower-is-better raw values separately from their once-inverted chart orientation and preserves numeric zero", () => {
    const points = [
      point("9".repeat(64), 2, 0, true, "known", REWORK),
      point("8".repeat(64), 1, 0.2, true, "known", REWORK),
    ];
    render(<MetricHistoryDrawer direction="lower_is_better" history={history(points)} metricKey={REWORK} />);
    fireEvent.click(screen.getByText("History"));

    expect(screen.getByText(/numeric raw rates are inverted once/i)).toBeInTheDocument();
    expect(screen.getByText("Numeric · raw 0% · chart 100%")).toBeInTheDocument();
    expect(screen.getByText("Numeric · raw 20% · chart 80%")).toBeInTheDocument();
    const chart = screen.getByRole("img", { name: "Selected metric history" });
    expect(chart).toHaveAttribute("data-numeric-count", "2");
    expect(chart.querySelectorAll("circle")).toHaveLength(2);
  });

  it("renders empty and delayed-empty trajectories explicitly", () => {
    const empty = history([]);
    const view = render(<MetricHistoryDrawer direction="higher_is_better" history={empty} metricKey={METRIC} />);
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByText(/no sealed snapshots are available/i)).toHaveTextContent(/not a zero metric value/i);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
   view.rerender(<MetricHistoryDrawer direction="higher_is_better" history={{ ...empty, error: true }} metricKey={METRIC} />);
   expect(screen.getByRole("status")).toHaveTextContent(/no previously loaded trajectory is available/i);
 });

  it("offers a manual read-only retry for delayed history, including with nothing loaded", () => {
    const onRetry = vi.fn();
    const delayedEmpty: MetricWorkspaceHistory = {
      points: [],
      headRunId: null,
      selectedRunId: null,
      onSelectRun: vi.fn(),
      error: true,
      onRetry,
    };
    render(<MetricHistoryDrawer direction="higher_is_better" history={delayedEmpty} metricKey={METRIC} />);
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByText(/no previously loaded trajectory is available/i)).toBeVisible();
    expect(screen.getByText("History unavailable")).toBeVisible();
    expect(screen.queryByText("0 sealed snapshots")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("falls back to the loaded current identity when a stale A selection is absent from context B", () => {
    const a = [point("a".repeat(64), 2, 0.6), point("b".repeat(64), 1, 0.4)];
    const valueA = history(a, a[1].run_id);
    const view = render(<MetricHistoryDrawer direction="higher_is_better" history={valueA} metricKey={METRIC} />);
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByRole("button", { name: "Open earlier snapshot 2" })).toHaveAttribute("aria-pressed", "true");

    const b = [point("c".repeat(64), 3, 0.8), point("d".repeat(64), 2, 0.7)];
    view.rerender(<MetricHistoryDrawer direction="higher_is_better" history={{ ...history(b), selectedRunId: a[1].run_id }} metricKey={METRIC} />);
    expect(screen.getByRole("status")).toHaveTextContent(/requested snapshot is no longer/i);
    expect(screen.getByRole("button", { name: "Open live snapshot" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("run bbbbbbbb…bbbb")).not.toBeInTheDocument();
    expect(document.querySelectorAll("circle.is-selected")).toHaveLength(1);
  });

  it("uses Arrow, Home, and End to focus and select the exact snapshot", () => {
    const points = [point("9".repeat(64), 3, 0.9), point("8".repeat(64), 2, 0.8), point("7".repeat(64), 1, 0.7)];
    const value = history(points);
    render(<MetricHistoryDrawer direction="higher_is_better" history={value} metricKey={METRIC} />);
    fireEvent.click(screen.getByText("History"));
    const list = screen.getByRole("list", { name: /sealed snapshot history/i });
    const buttons = within(list).getAllByRole("button");
    buttons[0].focus();
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(buttons[1]).toHaveFocus();
    expect(value.onSelectRun).toHaveBeenLastCalledWith(points[1].run_id);
    fireEvent.keyDown(list, { key: "End" });
    expect(buttons[2]).toHaveFocus();
    expect(value.onSelectRun).toHaveBeenLastCalledWith(points[2].run_id);
    fireEvent.keyDown(list, { key: "Home" });
    expect(buttons[0]).toHaveFocus();
    expect(value.onSelectRun).toHaveBeenLastCalledWith(points[0].run_id);
  });

  it("keeps the same truthful drawer contract in full and compact workspaces", () => {
    const points = [point("9".repeat(64), 2, 0.75), point("8".repeat(64), 1, 0.25)];
    const value = history(points);
    const run = { metrics: [], chunk_metrics: [], typed_metrics: [], predictive_metrics: [] };
    const transport = { getModelPredictiveMetricDetail: vi.fn(() => new Promise<never>(() => undefined)) };
    const view = render(
      <MetricWorkspace history={value} lensId="task-framing" mode="full" onLensChange={vi.fn()} run={run} runId={points[0].run_id} snapshotLabel="Synthetic" transport={transport} />,
    );
    const fullSummary = screen.getByText("History").parentElement?.textContent;
    const fullButtons = [...document.querySelectorAll(".metric-history__snapshots button")].map((button) => button.getAttribute("aria-label"));
    view.unmount();
    render(
      <MetricWorkspace history={value} lensId="task-framing" mode="compact" onLensChange={vi.fn()} run={run} runId={points[0].run_id} snapshotLabel="Synthetic" transport={transport} />,
    );
    expect(screen.getByText("History").parentElement?.textContent).toBe(fullSummary);
    expect([...document.querySelectorAll(".metric-history__snapshots button")].map((button) => button.getAttribute("aria-label"))).toEqual(fullButtons);
    expect(fullButtons).toEqual([
      "Open live snapshot",
      "Open earlier snapshot 2",
    ]);
  });
});
