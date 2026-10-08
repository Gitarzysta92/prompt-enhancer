import type { PillTone } from "../../shared/ui/StatusPill";

export type MetricValueState =
  | "known"
  | "unknown"
  | "not_applicable"
  | "abstained"
  | "execution_error";

export interface MetricSemantics {
  label: string;
  detail: string;
  tone: PillTone;
  partial: boolean;
}

function hasValidCoverage(
  observed: number,
  eligible: number,
  coverage: number,
): boolean {
  return Number.isSafeInteger(observed) &&
    Number.isSafeInteger(eligible) &&
    observed >= 0 &&
    eligible > 0 &&
    observed <= eligible &&
    Number.isFinite(coverage) &&
    coverage >= 0 &&
    coverage <= 1 &&
    Math.abs(coverage - observed / eligible) <= 1e-9;
}

export function describeMetricSemantics(input: {
  state: MetricValueState;
  numericValue: number | null;
  unit?: string | null;
  confidence?: number | null;
  observed: number;
  eligible: number;
  coverage: number;
}): MetricSemantics {
  if (input.state === "known") {
    const coverageValid = hasValidCoverage(input.observed, input.eligible, input.coverage);
    if (!coverageValid) {
      return {
        label: "Coverage unknown",
        detail:
          "Observed value retained, but evidence coverage could not be verified from the stored counts.",
        tone: "warning",
        partial: true,
      };
    }
    const coverageIncomplete = input.observed < input.eligible || input.coverage < 1;
    if (input.confidence == null && !coverageIncomplete) {
      return {
        label: "Confidence unknown",
        detail:
          "Observed value. Coverage is complete for this metric's eligible evidence in the current snapshot. Confidence was not reported; no confidence level is inferred.",
        tone: "warning",
        partial: true,
      };
    }
    const partial = coverageIncomplete;
    const isRate = input.unit === "ratio";
    if (partial && input.numericValue === 0) {
      if (isRate) {
        return {
          label: "Partial",
          detail:
            "Observed rate - partial coverage. Zero applies only to usable evidence in this current snapshot; it does not confirm absence.",
          tone: "warning",
          partial: true,
        };
      }
      return {
        label: "Partial",
        detail:
          "Observed subtotal - partial. Zero means no matching evidence was observed in this current snapshot; it does not confirm absence.",
        tone: "warning",
        partial: true,
      };
    }
    if (partial) {
      if (isRate) {
        return {
          label: "Partial",
          detail:
            "Observed rate - partial coverage. Missing evidence or uncertain stream completeness may change this rate.",
          tone: "warning",
          partial: true,
        };
      }
      return {
        label: "Partial",
        detail:
          "Observed subtotal - partial. Missing evidence or uncertain stream completeness may change this value.",
        tone: "warning",
        partial: true,
      };
    }
    return {
      label: "Observed",
      detail: "Current snapshot - complete for this metric's eligible evidence.",
      tone: "info",
      partial: false,
    };
  }

  if (input.state === "unknown") {
    if (input.eligible <= 0) {
      return {
        label: "Unknown",
        detail:
          "No eligible evidence was available in this current snapshot, so no value was inferred.",
        tone: "unknown",
        partial: true,
      };
    }
    if (!hasValidCoverage(input.observed, input.eligible, input.coverage)) {
      return {
        label: "Unknown",
        detail:
          "Evidence coverage is unknown because the stored observation counts are inconsistent or unavailable; no value was inferred.",
        tone: "unknown",
        partial: true,
      };
    }
    if (input.observed <= 0) {
      return {
        label: "Unknown",
        detail:
          "Eligible evidence exists, but no usable observations were available in this current snapshot.",
        tone: "unknown",
        partial: true,
      };
    }
    return {
      label: "Unknown",
      detail:
        "Available observations were insufficient to infer a value in this current snapshot.",
      tone: "unknown",
      partial: true,
    };
  }

  if (input.state === "not_applicable") {
    return {
      label: "Not applicable",
      detail: "This metric has no eligible evidence for the current snapshot.",
      tone: "info",
      partial: false,
    };
  }

  if (input.state === "abstained") {
    return {
      label: "Abstained",
      detail: "The calculator intentionally made no claim from the current snapshot.",
      tone: "warning",
      partial: true,
    };
  }

  return {
    label: "Execution error",
    detail: "The calculation did not complete; no metric value is available.",
    tone: "danger",
    partial: true,
  };
}
