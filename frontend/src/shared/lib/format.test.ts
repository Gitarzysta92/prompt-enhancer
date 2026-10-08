import { describe, expect, it } from "vitest";
import { formatPercent } from "./format";

describe("formatPercent", () => {
  it("does not round positive sub-threshold ratios to zero", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(1 / 1000)).toBe("0.1%");
    expect(formatPercent(1 / 1_000_000)).toBe("<0.01%");
    expect(formatPercent(99_999 / 100_000)).toBe(">99.99%");
    expect(formatPercent(1)).toBe("100%");
  });
});
