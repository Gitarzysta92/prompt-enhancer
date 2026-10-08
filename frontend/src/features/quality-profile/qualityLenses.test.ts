import { describe, expect, it } from "vitest";
import type { QualityMetricObservation } from "./qualityProfile";
import { QUALITY_LENSES, qualityLensesFor } from "./qualityLenses";

function metric(
  key: string,
  dimension: QualityMetricObservation["definition"]["dimension"],
  version: QualityMetricObservation["definition"]["version"] = 2,
): QualityMetricObservation {
  return {
    definition: {
      key,
      version,
      kind: dimension === "logic" || dimension === "outcome" ? "logic" : "prompt",
      dimension,
      unit: "ratio",
      direction: "higher_is_better",
      shortLabel: key,
      label: key,
      question: "Synthetic question.",
      method: "Synthetic method.",
      limitation: "Synthetic limitation.",
      polarity: "capability",
    },
    state: "observed",
    ratio: 0.5,
    fractionNumerator: 1,
    fractionDenominator: 2,
    observed: 1,
    eligible: 1,
    notSelectedRuns: 0,
    unknownScopeRuns: 0,
    coverage: 1,
    confidence: null,
    signals: [],
    metricSchemaVersion: 2,
    explanationCode: null,
    algorithmId: "synthetic",
    algorithmVersion: "1",
    modelId: null,
    errorCode: null,
    definitionVersion: 2,
    computedAt: "2040-01-01T00:00:00Z",
  };
}

describe("quality lenses", () => {
  it("defines four current and two explicitly versioned legacy lens vocabularies", () => {
    expect(
      QUALITY_LENSES.map(({ id, version, expectedMetricCount }) => ({
        id,
        version,
        expectedMetricCount,
      })),
    ).toEqual([
      { id: "task-framing", version: 1, expectedMetricCount: 6 },
      { id: "collaboration-flow", version: 1, expectedMetricCount: 5 },
      { id: "reasoning-trace", version: 1, expectedMetricCount: 4 },
      { id: "outcome-evidence", version: 1, expectedMetricCount: 5 },
      { id: "legacy-task-contract", version: 1, expectedMetricCount: 5 },
      { id: "legacy-reasoning-trace", version: 1, expectedMetricCount: 5 },
    ]);
    expect(QUALITY_LENSES.every((lens) => lens.metrics.length <= 8)).toBe(true);
    expect(
      QUALITY_LENSES.every(
        (lens) => lens.metrics.length === lens.expectedMetricCount,
      ),
    ).toBe(true);
  });

  it("keeps an exact legacy snapshot visible without accepting unknown versions", () => {
    const lenses = qualityLensesFor([
      metric("prompt.completion_evaluability", "prompt", 1),
      metric("prompt.goal_definition", "prompt", 1),
    ]);

    expect(lenses).toHaveLength(1);
    expect(lenses[0].definition.id).toBe("legacy-task-contract");
    expect(lenses[0].metrics.map((item) => item.definition.key)).toEqual([
      "prompt.goal_definition",
      "prompt.completion_evaluability",
    ]);
    expect(
      qualityLensesFor([metric("prompt.goal_definition", "prompt", 2)]),
    ).toEqual([]);
  });

  it("returns only represented dimensions in canonical lens and axis order", () => {
    const lenses = qualityLensesFor([
      metric("collaboration.clarification_yield", "collaboration"),
      metric("prompt.deliverable_contract", "prompt", 3),
      metric("prompt.task_definition_coverage", "prompt"),
      metric("collaboration.ambiguity_resolution", "collaboration"),
    ]);

    expect(lenses.map((lens) => lens.definition.id)).toEqual([
      "task-framing",
      "collaboration-flow",
    ]);
    expect(lenses[0].metrics.map((item) => item.definition.key)).toEqual([
      "prompt.task_definition_coverage",
      "prompt.deliverable_contract",
    ]);
    expect(lenses[1].metrics.map((item) => item.definition.key)).toEqual([
      "collaboration.ambiguity_resolution",
      "collaboration.clarification_yield",
    ]);
  });

  it("keeps all five evidence-lane keys even when objective evidence spans logic and outcome dimensions", () => {
    const evidence = qualityLensesFor([
      metric("outcome.verified_requirement_coverage", "outcome"),
      metric("logic.requirement_action_traceability", "logic", 3),
      metric("outcome.agent_claim_grounding", "outcome"),
      metric("logic.hypothesis_test_linkage", "logic"),
      metric("outcome.first_pass_verification", "outcome"),
    ]).find((lens) => lens.definition.id === "outcome-evidence");

    expect(evidence?.metrics.map((item) => item.definition.key)).toEqual([
      "logic.hypothesis_test_linkage",
      "logic.requirement_action_traceability",
      "outcome.agent_claim_grounding",
      "outcome.first_pass_verification",
      "outcome.verified_requirement_coverage",
    ]);
  });

  it("fails closed for unknown-only, version-mismatched, or duplicate lens identities", () => {
    expect(qualityLensesFor([metric("prompt.future_metric", "prompt")])).toEqual([]);
    expect(
      qualityLensesFor([
        metric("prompt.task_definition_coverage", "prompt", 1),
      ]),
    ).toEqual([]);
    expect(
      qualityLensesFor([
        metric("prompt.task_definition_coverage", "prompt"),
        metric("prompt.task_definition_coverage", "prompt"),
      ]),
    ).toEqual([]);
  });

  it("ignores additive unknown keys without changing the registered axis order", () => {
    const lenses = qualityLensesFor([
      metric("prompt.future_metric", "prompt"),
      metric("prompt.context_sufficiency", "prompt"),
      metric("prompt.task_definition_coverage", "prompt"),
    ]);

    expect(lenses).toHaveLength(1);
    expect(lenses[0].metrics.map((item) => item.definition.key)).toEqual([
      "prompt.task_definition_coverage",
      "prompt.context_sufficiency",
    ]);
  });
});
