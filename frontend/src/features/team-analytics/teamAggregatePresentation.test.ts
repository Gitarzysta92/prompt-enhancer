import { describe, expect, it } from "vitest";
import {
  TEAM_REVIEWED_METRIC_CONTRACTS,
  teamAggregateRequestForAccess,
  type AnalyticsScope,
} from "../../shared/api/teamControlPlane";
import { createSyntheticTeamControlPlanePort } from "../../shared/api/teamControlPlaneSynthetic";
import {
  memberCellLabel,
  teamLensColumns,
  teamMetricRowContext,
  teamMetricRowsForLens,
  teamReviewedMetricContractsMatchLenses,
  teamSnapshotSummary,
} from "./teamAggregatePresentation";

async function fixtureSnapshot(scope: AnalyticsScope) {
  const port = createSyntheticTeamControlPlanePort();
  const report = await port.getCapabilities();
  const access = report.scopes.find((candidate) => candidate.scope === scope)!;
  const request = teamAggregateRequestForAccess(access)!;
  return port.getAggregate(request);
}

describe("teamMetricRowsForLens", () => {
  it("fails closed with no rows when a reviewed lens contract drifts", async () => {
    const snapshot = await fixtureSnapshot("team");
    expect(teamReviewedMetricContractsMatchLenses()).toBe(true);
    const replaceFirst = (patch: Partial<(typeof TEAM_REVIEWED_METRIC_CONTRACTS)[number]>) =>
      TEAM_REVIEWED_METRIC_CONTRACTS.map((contract, index) => index === 0 ? { ...contract, ...patch } : contract);
    for (const drifted of [
      replaceFirst({ metric_key: "prompt.unreviewed_drift" }),
      replaceFirst({ definition_version: 999 }),
      replaceFirst({ direction: "lower_is_better" }),
    ]) {
      expect(teamReviewedMetricContractsMatchLenses(drifted)).toBe(false);
      expect(teamLensColumns("task-framing", drifted)).toEqual([]);
      expect(teamMetricRowsForLens(snapshot, "task-framing", drifted)).toEqual([]);
    }
  });

  it("shares one reviewed lens-column projection across aggregate and member surfaces", () => {
    expect(teamLensColumns("task-framing")).toEqual([
      { key: "prompt.task_definition_coverage", label: "Task definition coverage", shortLabel: "Task", direction: "higher_is_better", definitionVersion: 2 },
      { key: "prompt.problem_evidence_quality", label: "Problem evidence quality", shortLabel: "Evidence", direction: "higher_is_better", definitionVersion: 2 },
      { key: "prompt.context_sufficiency", label: "Context cue checks", shortLabel: "Context", direction: "higher_is_better", definitionVersion: 2 },
      { key: "prompt.constraint_precision", label: "Constraint precision candidates", shortLabel: "Constraints", direction: "higher_is_better", definitionVersion: 2 },
      { key: "prompt.acceptance_testability", label: "Acceptance testability cues", shortLabel: "Checkability", direction: "higher_is_better", definitionVersion: 2 },
      { key: "prompt.deliverable_contract", label: "Deliverable contract cues", shortLabel: "Deliverable", direction: "higher_is_better", definitionVersion: 3 },
    ]);
  });

  it("keeps every non-numeric state off the value axis and never at zero", async () => {
    const snapshot = await fixtureSnapshot("team");
    const framing = teamMetricRowsForLens(snapshot, "task-framing");
    expect(framing.map((row) => row.key)).toEqual([
      "prompt.task_definition_coverage",
      "prompt.problem_evidence_quality",
      "prompt.context_sufficiency",
      "prompt.constraint_precision",
      "prompt.acceptance_testability",
      "prompt.deliverable_contract",
    ]);
    const suppressed = framing.find((row) => row.key === "prompt.constraint_precision")!;
    expect(suppressed.status).toBe("suppressed");
    expect(suppressed.radarQuality).toBeNull();
    expect(suppressed.interval).toBeNull();
    expect(suppressed.valueLabel).toBe("Suppressed");
    expect(suppressed.cohortLabel).toContain("5 members");
    expect(suppressed.cohortLabel).toContain("contributing subset below minimum of 3");
    expect(suppressed.missingnessLabel).toBe("Contributor and missing-receipt counts suppressed");
    expect(suppressed.explainerProvenance).toBe("not_measured");

    const differencing = framing.find((row) => row.key === "prompt.problem_evidence_quality")!;
    expect(differencing.measured?.suppression_reason).toBe("overlap_or_differencing");
    expect(differencing.statusLabel).toBe("suppressed · overlap/differencing protection");
    expect(differencing.cohortLabel).toContain("contributor minimum of 3 was met");
    expect(differencing.cohortLabel).not.toContain("below minimum");

    const withheld = framing.find((row) => row.key === "prompt.deliverable_contract")!;
    expect(withheld.status).toBe("withheld");
    expect(withheld.radarQuality).toBeNull();
    expect(withheld.comparabilityLabel).toBe("Not comparable · definitions v1, v3 mixed");

    const known = framing.find((row) => row.key === "prompt.task_definition_coverage")!;
    expect(known.status).toBe("known");
    expect(known.radarQuality).toBeCloseTo(41 / 57);
    expect(known.interval!.low).toBeLessThan(known.radarQuality!);
    expect(known.interval!.high).toBeGreaterThan(known.radarQuality!);
    expect(known.valueLabel).toBe("72% · 41/57");
    expect(known.uncertaintyLabel).toMatch(/^95% interval \d+%–\d+% \(Wilson, sampling only\)$/u);
    expect(known.experimentalMedian).toBeCloseTo(0.69);
    expect(known.experimentalRange).toEqual({ low: 0.55, high: 0.81 });
    expect(known.explainerProvenance).toBe("measured");
    expect(known.missingnessLabel).toContain("5 of 5 members have a value");
    expect(known.freshnessLabel).toContain("Newest 30 Jan 2040");
  });

  it("orients lower-is-better metrics as radar quality with a flipped interval", async () => {
    const snapshot = await fixtureSnapshot("team");
    const rows = teamMetricRowsForLens(snapshot, "collaboration-flow");
    const rework = rows.find((row) => row.key === "collaboration.rework_candidate_rate")!;
    expect(rework.direction).toBe("lower_is_better");
    expect(rework.radarQuality).toBeCloseTo(1 - 7 / 64);
    expect(rework.valueLabel).toBe("89% radar quality · raw 11% · 7/64");
    expect(rework.valueLabelCompact).toBe("89% rq · raw 11%");
    const raw = rework.measured!.uncertainty;
    expect(rework.interval!.low).toBeCloseTo(1 - raw.high!);
    expect(rework.interval!.high).toBeCloseTo(1 - raw.low!);
    expect(rows.find((row) => row.key === "collaboration.exploration_conversion")!.status).toBe("not_applicable");
    expect(rows.find((row) => row.key === "collaboration.scope_change_discipline")!.status).toBe("abstained");
  });

  it("marks an exact measured zero as a real value at the centre", async () => {
    const snapshot = await fixtureSnapshot("me");
    const rows = teamMetricRowsForLens(snapshot, "outcome-evidence");
    const zero = rows.find((row) => row.key === "outcome.first_pass_verification")!;
    expect(zero.status).toBe("known");
    expect(zero.explicitZero).toBe(true);
    expect(zero.radarQuality).toBe(0);
    expect(zero.valueLabel).toBe("0% · 0/3");
    const unknown = rows.find((row) => row.key === "logic.hypothesis_test_linkage")!;
    expect(unknown.status).toBe("unknown");
    expect(unknown.radarQuality).toBeNull();
    expect(unknown.explicitZero).toBe(false);
  });

  it("uses experimental provenance only when no measured value exists", async () => {
    const snapshot = await fixtureSnapshot("team");
    const rows = teamMetricRowsForLens(snapshot, "reasoning-trace");
    const rationale = rows.find((row) => row.key === "logic.decision_rationale_coverage")!;
    expect(rationale.status).toBe("unknown");
    expect(rationale.radarQuality).toBeNull();
    expect(rationale.experimentalMedian).toBeCloseTo(0.44);
    expect(rationale.explainerProvenance).toBe("experimental");
    expect(rationale.explainerValue).toBeNull();
  });

  it("returns state-only rows for a null snapshot and counts states without plotting them", () => {
    expect(teamMetricRowsForLens(null, "task-framing").every((row) => row.status === "missing" && row.radarQuality === null)).toBe(true);
    expect(teamSnapshotSummary(null)).toEqual({ measured: 0, stateOnly: 0, experimental: 0, suppressed: 0 });
  });

  it("labels member cells without totals or ranks", () => {
    expect(memberCellLabel(null, "higher_is_better")).toBe("No record");
    expect(memberCellLabel({ metric_key: "x", definition_version: 2, value_state: "known", numerator: 2, denominator: 4, numeric_value: 0.5, provenance: "measured_typed", newest_receipt_at: null }, "higher_is_better")).toBe("50% · 2/4");
    expect(memberCellLabel({ metric_key: "x", definition_version: 2, value_state: "known", numerator: 1, denominator: 4, numeric_value: 0.25, provenance: "measured_typed", newest_receipt_at: null }, "lower_is_better")).toBe("75% rq · raw 25% · 1/4");
    expect(memberCellLabel({ metric_key: "x", definition_version: 2, value_state: "abstained", numerator: null, denominator: null, numeric_value: null, provenance: "measured_typed", newest_receipt_at: null }, "higher_is_better")).toBe("Needs evidence");
    expect(memberCellLabel({ metric_key: "x", definition_version: 2, value_state: "unknown", numerator: null, denominator: null, numeric_value: null, provenance: "measured_typed", newest_receipt_at: null }, "higher_is_better")).toBe("Unknown");
    expect(memberCellLabel({ metric_key: "x", definition_version: 2, value_state: "not_applicable", numerator: null, denominator: null, numeric_value: null, provenance: "measured_typed", newest_receipt_at: null }, "higher_is_better")).toBe("N/A");
  });
});

describe("teamMetricRowContext", () => {
  it("states scope, cohort contributors, model separation, and evidence authority per row without inventing counts", async () => {
    const snapshot = await fixtureSnapshot("team");
    const framing = teamMetricRowsForLens(snapshot, "task-framing");
    const measured = framing.find((row) => row.status === "known")!;
    const measuredContext = teamMetricRowContext(snapshot, measured);
    expect(measuredContext.scope).toBe("team");
    expect(measuredContext.label).toBe(`Team · ${snapshot.cohort_label}`);
    expect(measuredContext.description).toMatch(/no member ranking/);
    expect(measuredContext.contributors).toMatch(/members in cohort/);
    expect(measuredContext.contributors).toMatch(/minimum \d+ distinct contributors required/);
    expect(measuredContext.evidence).toMatch(/ratio-of-sums across the cohort/);
    const suppressed = framing.find((row) => row.status === "suppressed")!;
    const suppressedContext = teamMetricRowContext(snapshot, suppressed);
    expect(suppressedContext.evidence).toMatch(/State “suppressed/);
    expect(suppressedContext.evidence).toMatch(/never drawn as zero/);
    expect(suppressedContext.evidence).not.toMatch(/\b0%|\b0\/0\b/);
    const experimental = teamMetricRowsForLens(snapshot, "reasoning-trace").find((row) => row.experimental !== null);
    if (experimental !== undefined) {
      expect(teamMetricRowContext(snapshot, experimental).model).toMatch(/never merged with the measured value|nothing is drawn for it/);
    }
    const noRecord = { ...measured, measured: null, experimental: null };
    const noRecordContext = teamMetricRowContext(snapshot, noRecord);
    expect(noRecordContext.contributors).toBeNull();
    expect(noRecordContext.model).toBeNull();
    expect(noRecordContext.evidence).toMatch(/not observed, not zero, not plotted/);
  });
});
