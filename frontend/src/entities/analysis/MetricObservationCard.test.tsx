import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SYNTHETIC_RESULTS } from "../../shared/api/syntheticFixtures";
import { MetricObservationCard } from "./MetricObservationCard";

const GENERIC_RESULT = {
  ...SYNTHETIC_RESULTS[0],
  dimension: null,
  display_name: null,
  description: null,
};

describe("MetricObservationCard", () => {
  it("shows unknown as a state rather than a numeric zero", () => {
    const result = SYNTHETIC_RESULTS.find((item) => item.value_state === "unknown")!;
    render(<MetricObservationCard result={result} />);

    expect(screen.getByRole("heading", { name: result.display_name! })).toBeVisible();
    expect(screen.getByText("Unknown", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.queryByText("0 tokens")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Eligible evidence exists, but no usable observations/i),
    ).toBeVisible();
    expect(screen.getByRole("meter")).toHaveAccessibleName(
      `0 of ${result.eligible_count} observations (0%)`,
    );
  });

  it("renders an arbitrary known metric through the generic presenter", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "fictional_delivery_signal",
      numeric_value: 0.42,
      unit: "ratio",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByRole("heading", { name: "Fictional Delivery Signal" })).toBeVisible();
    expect(screen.getByText("42%")).toBeVisible();
    expect(screen.queryByText("Rate basis")).not.toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeVisible();
  });

  it("prefers persisted presentation metadata while retaining the metric question", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.workflow.finalized_turn_count",
      dimension: "verification",
      display_name: "Persisted iteration evidence",
      description: "Synthetic persisted definition metadata.",
    };
    render(<MetricObservationCard result={result} />);

    expect(
      screen.getByRole("heading", { name: "Persisted iteration evidence" }),
    ).toBeVisible();
    expect(screen.getByText("Verification", { selector: ".metric-card__eyebrow" })).toBeVisible();
    expect(screen.getByText(/How many finalized agent turns/i)).toBeVisible();
  });

  it("labels an incomplete numeric count as an observed subtotal", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.workflow.finalized_turn_count",
      numeric_value: 3,
      observed_count: 3,
      eligible_count: 5,
      coverage: 0.6,
      confidence: 1,
      unit: "count",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("3", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.getByText("Partial")).toBeVisible();
    expect(screen.getByText(/Observed subtotal - partial/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Observed agent iterations" })).toBeVisible();
    expect(screen.getByText(/How many finalized agent turns/i)).toBeVisible();
  });

  it("does not let a partial zero imply confirmed absence", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.workflow.compaction_count",
      numeric_value: 0,
      observed_count: 1,
      eligible_count: 2,
      coverage: 0.5,
      confidence: 1,
      unit: "count",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("0", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.getByText(/does not confirm absence/i)).toBeVisible();
  });

  it("distinguishes complete coverage from unknown confidence", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.data_quality.unknown_event_kind_rate",
      numeric_value: 0,
      observed_count: 8,
      eligible_count: 8,
      coverage: 1,
      confidence: null,
      unit: "ratio",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("Confidence unknown")).toBeVisible();
    expect(screen.getByText(/Coverage is complete/i)).toBeVisible();
    expect(screen.queryByText(/partial coverage/i)).not.toBeInTheDocument();
    expect(screen.getByText("100%")).toBeVisible();
  });

  it("keeps a known value but labels invalid coverage inputs explicitly", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.data_quality.unknown_event_kind_rate",
      numeric_value: 0.25,
      observed_count: 3,
      eligible_count: 2,
      coverage: 0.5,
      confidence: 1,
      unit: "ratio",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("25%", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.getByText("Coverage unknown")).toBeVisible();
    expect(screen.getByText(/could not be verified/i)).toBeVisible();
    expect(screen.getByText("Coverage unavailable")).toBeVisible();
  });

  it("keeps an unknown state when coverage inputs are inconsistent", () => {
    const result = {
      ...SYNTHETIC_RESULTS.find((item) => item.value_state === "unknown")!,
      observed_count: 3,
      eligible_count: 2,
      coverage: 0.5,
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("Unknown", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.getByText(/coverage is unknown because/i)).toBeVisible();
    expect(screen.getByText("Coverage unavailable")).toBeVisible();
  });

  it("keeps a small nonzero event rate visibly nonzero", () => {
    const result = {
      ...GENERIC_RESULT,
      key: "task.data_quality.unknown_event_kind_rate",
      numeric_value: 1 / 1000,
      observed_count: 1000,
      eligible_count: 1000,
      coverage: 1,
      confidence: 1,
      unit: "ratio",
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText("0.1%", { selector: ".metric-card__value" })).toBeVisible();
    expect(screen.getByText("1/1,000")).toBeVisible();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "100");
  });

  it("explains when an unknown metric has no eligible evidence", () => {
    const result = {
      ...SYNTHETIC_RESULTS.find((item) => item.value_state === "unknown")!,
      observed_count: 0,
      eligible_count: 0,
      coverage: 0,
    };
    render(<MetricObservationCard result={result} />);

    expect(screen.getByText(/No eligible evidence was available/i)).toBeVisible();
  });

  it("shows the required provenance fields on every card", () => {
    render(<MetricObservationCard result={SYNTHETIC_RESULTS[0]} />);
    const card = screen.getByRole("article");

    for (const label of [
      "Source",
      "Definition",
      "Usable evidence",
      "Eligible evidence",
      "Confidence",
    ]) {
      expect(within(card).getByText(label)).toBeVisible();
    }
    expect(within(card).getByText("Deterministic")).toBeVisible();
  });
});
