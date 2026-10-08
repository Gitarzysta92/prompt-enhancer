import { describe, expect, it } from "vitest";
import { describeMetricSemantics } from "./metricSemantics";

const base = {
  state: "known" as const,
  numericValue: 0.4,
  unit: "ratio",
  observed: 4,
  eligible: 4,
  coverage: 1,
};

describe("describeMetricSemantics", () => {
  it.each([null, undefined])("separates complete coverage from unreported confidence (%j)", (confidence) => {
    const semantics = describeMetricSemantics({ ...base, confidence });

    expect(semantics.label).toBe("Confidence unknown");
    expect(semantics.detail).toMatch(/Coverage is complete/);
    expect(semantics.detail).toMatch(/Confidence was not reported/);
    expect(semantics.detail).not.toMatch(/calibrated/);
  });

  it("keeps genuinely incomplete coverage partial", () => {
    const semantics = describeMetricSemantics({ ...base, confidence: 1, observed: 3, coverage: 0.75 });

    expect(semantics.label).toBe("Partial");
    expect(semantics.detail).toMatch(/partial coverage/);
  });

  it("fails closed for inconsistent coverage while preserving a known state", () => {
    const semantics = describeMetricSemantics({ ...base, confidence: 1, observed: 5 });

    expect(semantics.label).toBe("Coverage unknown");
    expect(semantics.detail).toMatch(/could not be verified/);
  });

  it.each([
    { observed: 4, eligible: 4, coverage: 0.5 },
    { observed: 3, eligible: 4, coverage: 1 },
  ])("rejects coverage that does not equal observed / eligible (%j)", (counts) => {
    const semantics = describeMetricSemantics({ ...base, confidence: 1, ...counts });

    expect(semantics.label).toBe("Coverage unknown");
  });

  it("keeps unknown values unknown when their coverage is inconsistent", () => {
    const semantics = describeMetricSemantics({
      ...base,
      state: "unknown",
      numericValue: null,
      confidence: null,
      observed: 5,
    });

    expect(semantics.label).toBe("Unknown");
    expect(semantics.detail).toMatch(/coverage is unknown/);
  });
});
