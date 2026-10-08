import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MetricCoverageReport } from "../../shared/api/contracts";
import {
  SYNTHETIC_METRIC_COVERAGE,
  SYNTHETIC_QUALITY_PROJECT_ID,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { MetricCoveragePanel } from "./MetricCoveragePanel";

function detailedReport(): MetricCoverageReport {
  const report = structuredClone(SYNTHETIC_METRIC_COVERAGE);
  report.indexed_session_count = 2;
  report.latest_profile_runs = {
    completed: 1,
    running: 0,
    failed: 1,
    never_run: 0,
  };
  report.latest_completed_snapshot_count = 2;
  report.effective_automation_grant_count = 1;
  report.effective_automation_project_count = 1;
  const stateNames = [
    "known", "unknown", "not_applicable", "abstained", "execution_error",
  ] as const;
  report.metrics.forEach((metric, index) => {
    metric.latest_completed_run_count = 2;
    metric.selected_run_count = 2;
    metric.completed_selected_run_count = 2;
    metric.contract_compatible_result_states = {
      known: 0,
      unknown: 0,
      not_applicable: 0,
      abstained: 0,
      execution_error: 0,
    };
    metric.contract_compatible_result_states[stateNames[index] ?? "known"] =
      index === 0 ? 1 : 2;
    metric.contract_incompatible_result_count = index === 0 ? 1 : 0;
    metric.compatible_provenance_cohort_count = 1;
    metric.effective_automation_selected_project_count = index === 0 ? 1 : 0;
  });
  return report;
}

describe("MetricCoveragePanel", () => {
  it("keeps structural, contract, state, provenance, attempt and automation axes distinct", async () => {
    const report = detailedReport();
    const transport = createSyntheticTransport();
    transport.getMetricCoverage = vi.fn(async () => report);

    render(<MetricCoveragePanel provider="synthetic" transport={transport} />);

    expect(await screen.findByRole("heading", { name: "Coaching metric coverage" }))
      .toBeVisible();
    expect(screen.getByText("20 of 20 metric definitions are structurally attemptable."))
      .toBeVisible();
    expect(screen.getByText(/does not mean 20 metrics were measured/i)).toBeVisible();
    const snapshot = screen.getByRole("group", { name: "Coverage snapshot counts" });
    expect(snapshot).toHaveTextContent("Contract-compatible stored results39");
    expect(snapshot).toHaveTextContent("Contract-incompatible selected snapshots1");
    expect(snapshot).toHaveTextContent("Per-metric provenance cohorts20");
    expect(snapshot).toHaveTextContent("Unrecognized stored result records0");
    expect(screen.getByRole("group", { name: "Latest analysis attempts" }))
      .toHaveTextContent("Latest attempt completed1Latest attempt running0Latest attempt failed1Never run0");
    expect(screen.getByRole("group", { name: "Automation scope" }))
      .toHaveTextContent("Effective automation grants1Effective automation projects1");

    fireEvent.click(screen.getByText("Metric-by-metric counts"));
    const table = screen.getByRole("table");
    for (const heading of [
      "Known", "Unknown", "Not applicable", "Abstained", "Execution error",
      "Incompatible selections", "Absent", "Cohorts", "Not selected",
      "Scope unknown", "Automation-selected projects",
    ]) {
      expect(within(table).getByRole("columnheader", { name: heading })).toBeVisible();
    }
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(21);
    expect(within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent))
      .toEqual(["attemptable", "2", "0", "0", "1", "0", "0", "0", "0", "1", "0", "1", "1"]);
    expect(document.body.textContent).not.toContain(SYNTHETIC_QUALITY_PROJECT_ID);
    expect(document.body.textContent).not.toContain("%");
    expect(screen.getByText(/not for all provider history/i)).toBeVisible();
    expect(screen.getByText(/not captured atomically/i)).toBeVisible();
    expect(screen.getByText(/Full catalog automation coverage is not guaranteed/i))
      .toBeVisible();
  });

  it("isolates a failed coverage read and retries without exposing the error", async () => {
    const transport = createSyntheticTransport();
    const getMetricCoverage = vi.fn()
      .mockRejectedValueOnce(new Error("PRIVATE-COVERAGE-CANARY"))
      .mockResolvedValueOnce(SYNTHETIC_METRIC_COVERAGE);
    transport.getMetricCoverage = getMetricCoverage;

    render(<MetricCoveragePanel provider="synthetic" transport={transport} />);
    expect(await screen.findByRole("heading", { name: "Metric coverage: Unknown" }))
      .toBeVisible();
    expect(document.body.textContent).not.toContain("PRIVATE-COVERAGE-CANARY");
    fireEvent.click(screen.getByRole("button", { name: "Retry coverage" }));

    expect(await screen.findByRole("heading", { name: "Coaching metric coverage" }))
      .toBeVisible();
    expect(getMetricCoverage).toHaveBeenCalledTimes(2);
  });

  it("uses the project-scoped request and aborts it when removed", async () => {
    const transport = createSyntheticTransport();
    let signal: AbortSignal | undefined;
    transport.getProjectMetricCoverage = vi.fn((_projectId, _provider, requestSignal) => {
      signal = requestSignal;
      return new Promise<never>(() => undefined);
    });
    const { unmount } = render(
      <MetricCoveragePanel
        projectId={SYNTHETIC_QUALITY_PROJECT_ID}
        provider="synthetic"
        transport={transport}
      />,
    );
    await waitFor(() => expect(signal).toBeInstanceOf(AbortSignal));
    expect(transport.getProjectMetricCoverage).toHaveBeenCalledWith(
      SYNTHETIC_QUALITY_PROJECT_ID,
      "synthetic",
      expect.any(AbortSignal),
    );
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});
