import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricOpportunityMap } from "./MetricOpportunityMap";
import {
  METRIC_OPPORTUNITY_CATALOG_VERSION,
  METRIC_OPPORTUNITY_FAMILIES,
} from "./metricOpportunityCatalog";

describe("MetricOpportunityMap", () => {
  it("uses unique labelled-by identities when two maps are embedded", () => {
    render(<><MetricOpportunityMap /><MetricOpportunityMap /></>);
    const sections = screen.getAllByRole("region", {
      name: "Next evidence for real user benefit",
    });
    const ids = sections.map((section) => section.getAttribute("aria-labelledby"));
    expect(ids.every(Boolean)).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("keeps future metric specifications separate from measured values", () => {
    const { container } = render(<MetricOpportunityMap />);

    const summary = screen.getByText("Broader value map");
    expect(summary).toBeVisible();
    expect(screen.getByText(`9 families`)).toBeVisible();
    fireEvent.click(summary);

    expect(
      screen.getByText(/versioned metric specifications, not inferred values/i),
    ).toBeVisible();
    expect(screen.getByText(/catalog v1/i)).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(9);
    expect(screen.getAllByText("Not measured yet").length).toBeGreaterThan(0);
    expect(screen.getByText("Private opt-in only")).toBeVisible();
    expect(container).not.toHaveTextContent("0%");
    expect(container).not.toHaveTextContent(/overall quality score/i);
  });

  it("shows actionable evidence, release gates, and guardrails", () => {
    render(<MetricOpportunityMap />);
    fireEvent.click(screen.getByText("Broader value map"));

    const recommendationCard = screen
      .getByRole("heading", { name: "Recommendation effectiveness" })
      .closest("article");
    expect(recommendationCard).not.toBeNull();
    expect(
      within(recommendationCard!).getByText("Recommendation adoption rate"),
    ).toBeVisible();
    expect(within(recommendationCard!).getByText("Evidence to add")).toBeVisible();
    expect(within(recommendationCard!).getByText("How to use it")).toBeVisible();
    expect(within(recommendationCard!).getByText("Release gate")).toBeVisible();
    expect(within(recommendationCard!).getByText("Guardrail")).toBeVisible();
  });

  it("has one versioned, unique post-processing key per candidate metric", () => {
    expect(METRIC_OPPORTUNITY_CATALOG_VERSION).toBe(1);
    const familyIds = METRIC_OPPORTUNITY_FAMILIES.map((family) => family.id);
    const metricKeys = METRIC_OPPORTUNITY_FAMILIES.flatMap((family) =>
      family.candidateMetrics.map((metric) => metric.key),
    );
    expect(new Set(familyIds).size).toBe(familyIds.length);
    expect(new Set(metricKeys).size).toBe(metricKeys.length);
    expect(
      METRIC_OPPORTUNITY_FAMILIES.every(
        (family) =>
          family.evidenceToAdd.length > 0 &&
          family.validationGate.length > 0 &&
          family.guardrail.length > 0,
      ),
    ).toBe(true);
  });
});
