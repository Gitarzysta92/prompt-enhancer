import { describe, expect, it } from "vitest";
import { sessionMetricGuidance } from "./metricGuidance";

describe("sessionMetricGuidance", () => {
  it("requests objective local evidence instead of prompt rewriting", () => {
    const guidance = sessionMetricGuidance("outcome.verified_requirement_coverage", {
      state: "abstained",
      numericValue: null,
      direction: "higher_is_better",
      explanationCode: "objective_verification_stream_required",
    });

    expect(guidance.audience).toBe("tooling");
    expect(guidance.basis).toBe("readiness");
    expect(guidance.action).toMatch(/tool, test, artifact, action, or acceptance receipt/i);
    expect(guidance.action).not.toMatch(/rewrite|improve the prompt/i);
  });

  it("names at most two weak factors without generating source-derived prose", () => {
    const guidance = sessionMetricGuidance("prompt.task_definition_coverage", {
      state: "known",
      numericValue: 0.25,
      direction: "higher_is_better",
      factorKeys: ["action", "intended_outcome", "target"],
    });

    expect(guidance.factorKeys).toEqual(["action", "intended_outcome"]);
    expect(guidance.action).toMatch(/focus on action and intended outcome/i);
    expect(guidance.basis).toBe("measured");
  });

  it("does not prescribe changes for a not-applicable metric", () => {
    const guidance = sessionMetricGuidance("logic.decomposition_coverage", {
      state: "not_applicable",
      numericValue: null,
      direction: "higher_is_better",
    });

    expect(guidance.action).toMatch(/no change is required/i);
    expect(guidance.basis).toBe("readiness");
  });

  it("waits for an open episode horizon instead of treating pending as a user defect", () => {
    const legacyGuidance = sessionMetricGuidance("collaboration.open_loop_closure", {
      state: "unknown",
      numericValue: null,
      direction: "higher_is_better",
      explanationCode: "episode_horizon_open",
    });
    const guidance = sessionMetricGuidance("collaboration.open_loop_closure", {
      state: "pending",
      numericValue: null,
      direction: "higher_is_better",
    });

    expect(guidance.action).toMatch(/nothing to change yet.*pending/i);
    expect(guidance.verification).toMatch(/episode closes/i);
    expect(guidance.basis).toBe("readiness");
    expect(legacyGuidance).toEqual(guidance);
  });

  it("keeps an unknown metric with a visible model range explicitly experimental", () => {
    const guidance = sessionMetricGuidance("prompt.task_definition_coverage", {
      state: "unknown",
      numericValue: null,
      direction: "higher_is_better",
      experimentalOnly: true,
    });

    expect(guidance.action).toMatch(/^if the experimental signal persists/i);
    expect(guidance.basis).toBe("experimental");
  });

  it("does not call a partial measured fraction a practice to keep", () => {
    const guidance = sessionMetricGuidance("prompt.constraint_precision", {
      state: "known",
      numericValue: 0.8,
      direction: "higher_is_better",
    });

    expect(guidance.action).not.toMatch(/keep the observed practice/i);
    expect(guidance.action).toMatch(/convert .*vague constraint/i);
    expect(guidance.basis).toBe("measured");
  });
});
