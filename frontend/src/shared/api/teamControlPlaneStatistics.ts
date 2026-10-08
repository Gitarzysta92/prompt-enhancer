import type { TeamMetricValueState } from "./teamControlPlaneSchema";

/** Value states that carry a plottable numeric fraction. */
export function teamMetricHasValue(state: TeamMetricValueState): boolean {
  return state === "known";
}

/**
 * Wilson score interval for a binomial fraction. It describes sampling
 * uncertainty of an exact cohort fraction; it is not calibration and it never
 * turns a missing value into a number.
 */
export function wilsonInterval(
  numerator: number,
  denominator: number,
  z = 1.96,
): { low: number; high: number } | null {
  if (
    !Number.isFinite(numerator)
    || !Number.isFinite(denominator)
    || denominator <= 0
    || numerator < 0
    || numerator > denominator
  ) return null;
  const p = numerator / denominator;
  const z2 = z * z;
  const centre = (p + z2 / (2 * denominator)) / (1 + z2 / denominator);
  const spread = (z * Math.sqrt((p * (1 - p)) / denominator + z2 / (4 * denominator * denominator)))
    / (1 + z2 / denominator);
  return {
    low: Math.max(0, Math.min(1, centre - spread)),
    high: Math.max(0, Math.min(1, centre + spread)),
  };
}
