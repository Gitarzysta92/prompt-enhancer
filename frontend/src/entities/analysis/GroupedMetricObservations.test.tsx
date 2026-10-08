import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SYNTHETIC_RESULTS } from "../../shared/api/syntheticFixtures";
import { GroupedMetricObservations } from "./GroupedMetricObservations";

const GENERIC_RESULT = {
  ...SYNTHETIC_RESULTS[0],
  dimension: null,
  display_name: null,
  description: null,
};

describe("GroupedMetricObservations", () => {
  it("groups registered and fallback metrics by interpretation question", () => {
    const base = GENERIC_RESULT;
    const results = [
      {
        ...base,
        key: "task.data_quality.turn_usage_coverage",
        numeric_value: 0.5,
        unit: "ratio",
      },
      {
        ...base,
        key: "task.workflow.finalized_turn_count",
        numeric_value: 2,
      },
      {
        ...base,
        key: "task.verification.observed_count",
        numeric_value: 1,
      },
      {
        ...base,
        key: "task.experimental.fictional_signal",
        numeric_value: 7,
      },
    ];

    render(<GroupedMetricObservations results={results} />);

    const readiness = screen.getByRole("region", { name: "Data readiness" });
    expect(within(readiness).getByText("Usable turn usage coverage")).toBeVisible();
    expect(within(readiness).getByText(/For how many finalized turns/i)).toBeVisible();

    const effort = screen.getByRole("region", { name: "Operational effort" });
    expect(within(effort).getByText("Observed agent iterations")).toBeVisible();

    const evidence = screen.getByRole("region", {
      name: "Verification and outcome evidence",
    });
    expect(within(evidence).getByText("Verification Observed Count")).toBeVisible();

    const fallback = screen.getByRole("region", { name: "Other observations" });
    expect(within(fallback).getByText("Experimental Fictional Signal")).toBeVisible();
    expect(screen.getByText("Task stream completeness not reported")).toBeVisible();
  });

  it("keeps tool reliability with operational evidence, not task correctness", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.reliability.tool_success_rate",
      numeric_value: 0.8,
      unit: "ratio",
    };
    render(<GroupedMetricObservations results={[result]} />);

    const effort = screen.getByRole("region", { name: "Operational effort" });
    expect(within(effort).getByText(/do not prove task success/i)).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Verification and outcome evidence" }),
    ).not.toBeInTheDocument();
  });

  it("groups by the persisted definition dimension before using key inference", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.experimental.fictional_signal",
      dimension: "data_quality",
      display_name: "Persisted readiness signal",
      description: "Synthetic persisted definition metadata.",
    };
    render(<GroupedMetricObservations results={[result]} />);

    const readiness = screen.getByRole("region", { name: "Data readiness" });
    expect(within(readiness).getByText("Persisted readiness signal")).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Other observations" }),
    ).not.toBeInTheDocument();
  });

  it("keeps task-stream completeness separate from metric confidence", () => {
    const eventStream = {
      ...GENERIC_RESULT,
      key: "task.workflow.observed_event_count",
      observed_count: 1,
      eligible_count: 2,
      coverage: 0.5,
      confidence: null,
    };
    const rate = {
      ...GENERIC_RESULT,
      key: "task.data_quality.unknown_event_kind_rate",
      numeric_value: 1 / 6,
      observed_count: 6,
      eligible_count: 6,
      coverage: 1,
      confidence: null,
      unit: "ratio",
    };
    render(<GroupedMetricObservations results={[eventStream, rate]} />);

    expect(screen.getByText("Partial task evidence - current snapshot only")).toBeVisible();
    const rateCard = screen.getByRole("heading", {
      name: "Unknown event kind rate",
    }).closest("article")!;
    expect(within(rateCard).getByText("1/6")).toBeVisible();
    expect(within(rateCard).getByText(/Coverage is complete/i)).toBeVisible();
    expect(within(rateCard).getByText("Confidence unknown")).toBeVisible();
    expect(within(rateCard).queryByText(/partial coverage/i)).not.toBeInTheDocument();
  });
});
