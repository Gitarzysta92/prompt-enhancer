import { describe, expect, it } from "vitest";
import { METRIC_ROUTE_CATEGORIES } from "../../shared/platform/platform";
import {
  METRIC_TAXONOMY,
  metricCategoryDefinition,
  metricCategoryFor,
} from "./metricTaxonomy";

describe("metric taxonomy", () => {
  it("has one presentation entry for every allowlisted route category", () => {
    expect(METRIC_TAXONOMY.map(({ id }) => id)).toEqual(METRIC_ROUTE_CATEGORIES);
  });

  it.each([
    ["data_quality", "session.data_quality.turn_usage_coverage", "readiness"],
    ["workflow", "session.workflow.event_count", "execution"],
    ["reliability", "session.reliability.tool_success_rate", "tools"],
    ["usage", "session.usage.total_tokens", "model-usage"],
    ["verification", "session.verification.pass_rate", "outcome"],
    ["prompt_quality", "session.prompt_quality.goal_clarity", "prompt-quality"],
    ["reasoning", "session.reasoning.evidence_linkage", "reasoning"],
  ] as const)("maps %s metrics to %s", (dimension, key, expected) => {
    expect(metricCategoryFor({ dimension, key })).toBe(expected);
  });

  it("keeps an unregistered metric visible under other", () => {
    expect(
      metricCategoryFor({
        dimension: "future_dimension",
        key: "fictional.future_dimension.experimental_observation",
      }),
    ).toBe("other");
  });

  it.each([
    ["workflow", "session.workflow.tool_event_count"],
    ["efficiency", "session.efficiency.observed_tool_duration_ms"],
  ])("routes key-specific %s tool metrics to tools", (dimension, key) => {
    expect(metricCategoryFor({ dimension, key })).toBe("tools");
  });

  it("keeps tool evidence coverage in readiness", () => {
    expect(
      metricCategoryFor({
        dimension: "data_quality",
        key: "session.data_quality.tool_result_coverage",
      }),
    ).toBe("readiness");
  });

  it("marks prompt and logic as explicit local analysis rather than automatic stored metrics", () => {
    expect(metricCategoryDefinition("prompt-quality").availability).toBe("local-analysis");
    expect(metricCategoryDefinition("reasoning").availability).toBe("local-analysis");
  });
});
