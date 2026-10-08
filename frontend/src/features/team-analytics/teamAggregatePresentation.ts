import { QUALITY_ANALYSIS_DEFINITIONS } from "../quality-profile/qualityProfile";
import { MODEL_ENSEMBLE_LENSES, type ModelEnsembleLensId } from "../model-ensemble/metricAxisModel";
import type { MetricExplainerProvenance } from "../model-ensemble/metricHelpV2";
import { SCOPE_CONTEXT_LABELS, type MetricContextFacts } from "../model-ensemble/metricContextFacts";
import type {
  MetricDirection,
  TeamAggregateSnapshot,
  TeamMemberMetricCell,
  TeamMetricAggregate,
  TeamMetricSuppressionReason,
  TeamMetricValueState,
} from "../../shared/api/teamControlPlane";
import {
  TEAM_REVIEWED_METRIC_CONTRACTS,
  type TeamReviewedMetricContract,
} from "../../shared/api/teamControlPlane";
import { shortUtcDate } from "./teamAnalyticsCopy";

/**
 * Presentation-only projection of a team aggregate snapshot onto the shipped
 * metric lenses. It never computes new statistics: values, intervals, cohort
 * sizes, and states are read from the port and only oriented for display
 * (lower-is-better metrics plot 100% minus the raw rate, exactly like the
 * personal radar). Non-numeric states never become zero.
 */
export type TeamMetricRowStatus =
  | "known"
  | "suppressed"
  | "withheld"
  | "unknown"
  | "not_applicable"
  | "abstained"
  | "unavailable"
  | "missing";

export interface OrientedRange {
  low: number;
  high: number;
}

export interface TeamMetricRow {
  key: string;
  label: string;
  shortLabel: string;
  direction: MetricDirection;
  definitionVersion: number;
  measured: TeamMetricAggregate | null;
  experimental: TeamMetricAggregate | null;
  status: TeamMetricRowStatus;
  statusLabel: string;
  /** Header value text: exact fraction and percentage, or the state. */
  valueLabel: string;
  /** Shorter value text for the compact list; same facts, fewer words. */
  valueLabelCompact: string;
  /** Radar-quality orientation (0..1); null for every non-numeric state. */
  radarQuality: number | null;
  /** True when the measured raw fraction is exactly zero: a real value, never missing data. */
  explicitZero: boolean;
  interval: OrientedRange | null;
  experimentalMedian: number | null;
  experimentalRange: OrientedRange | null;
  explainerProvenance: MetricExplainerProvenance;
  /** Raw fraction (metric direction) handed to the explainer, when measured. */
  explainerValue: number | null;
  cohortLabel: string;
  missingnessLabel: string;
  comparabilityLabel: string;
  freshnessLabel: string;
  uncertaintyLabel: string;
}

export interface TeamLensColumn {
  key: string;
  label: string;
  shortLabel: string;
  direction: MetricDirection;
  definitionVersion: number;
}

const DEFINITIONS = new Map(QUALITY_ANALYSIS_DEFINITIONS.map((definition) => [definition.key, definition]));

/**
 * Team publication is accepted only while its independently reviewed contract
 * list exactly matches every production lens key, version, and direction.
 * This is deliberately not derived from the lenses: drift must fail closed
 * until a reviewer updates both sides.
 */
export function teamReviewedMetricContractsMatchLenses(
  reviewed: readonly TeamReviewedMetricContract[] = TEAM_REVIEWED_METRIC_CONTRACTS,
): boolean {
  const lensMetrics = MODEL_ENSEMBLE_LENSES.flatMap((lens) => lens.metrics);
  if (reviewed.length !== lensMetrics.length) return false;
  const reviewedKeys = reviewed.map((contract) => contract.metric_key);
  const lensKeys = lensMetrics.map((metric) => metric.key);
  if (new Set(reviewedKeys).size !== reviewed.length || new Set(lensKeys).size !== lensMetrics.length) return false;
  const reviewedByKey = new Map(reviewed.map((contract) => [contract.metric_key, contract]));
  return lensMetrics.every(({ key, version }) => {
    const contract = reviewedByKey.get(key);
    const definition = DEFINITIONS.get(key);
    return contract !== undefined
      && definition !== undefined
      && contract.definition_version === version
      && contract.definition_version === definition.version
      && contract.direction === definition.direction;
  });
}

/** Shared, fail-closed lens columns for aggregate and member presentations. */
export function teamLensColumns(
  lensId: ModelEnsembleLensId,
  reviewed: readonly TeamReviewedMetricContract[] = TEAM_REVIEWED_METRIC_CONTRACTS,
): TeamLensColumn[] {
  if (!teamReviewedMetricContractsMatchLenses(reviewed)) return [];
  const lens = MODEL_ENSEMBLE_LENSES.find((candidate) => candidate.id === lensId);
  if (lens === undefined) return [];
  return lens.metrics.map(({ key, version }) => {
    const definition = DEFINITIONS.get(key);
    return {
      key,
      label: definition?.label ?? key,
      shortLabel: definition?.shortLabel ?? key,
      direction: definition?.direction ?? "higher_is_better",
      definitionVersion: version,
    };
  });
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function orient(value: number, direction: MetricDirection): number {
  return direction === "lower_is_better" ? 1 - value : value;
}

function orientRange(low: number, high: number, direction: MetricDirection): OrientedRange {
  return direction === "lower_is_better"
    ? { low: 1 - high, high: 1 - low }
    : { low, high };
}

export function teamMetricRowStatus(state: TeamMetricValueState | null): TeamMetricRowStatus {
  switch (state) {
    case null: return "missing";
    case "known": return "known";
    case "suppressed_small_cohort": return "suppressed";
    case "suppressed_privacy_policy": return "suppressed";
    case "withheld_not_comparable": return "withheld";
    case "not_applicable": return "not_applicable";
    case "abstained": return "abstained";
    case "unavailable": return "unavailable";
    case "unknown":
    default: return "unknown";
  }
}

export function teamMetricStatusLabel(
  status: TeamMetricRowStatus,
  suppressionReason: TeamMetricSuppressionReason | null = null,
): string {
  switch (status) {
    case "known": return "measured";
    case "suppressed": return suppressionReason === "overlap_or_differencing"
      ? "suppressed · overlap/differencing protection"
      : suppressionReason === "query_identity_mismatch"
        ? "suppressed · query identity mismatch"
        : suppressionReason === "small_cohort"
          ? "suppressed · small contributing cohort"
          : "suppressed · privacy protection";
    case "withheld": return "withheld · not comparable";
    case "not_applicable": return "not applicable";
    case "abstained": return "needs evidence";
    case "unavailable": return "unavailable";
    case "missing": return "no record";
    case "unknown":
    default: return "unknown";
  }
}

function pluralMembers(count: number): string {
  return `${count} member${count === 1 ? "" : "s"}`;
}

export function cohortLabelFor(metric: TeamMetricAggregate | null): string {
  if (metric === null) return "Cohort not exposed";
  const members = metric.cohort.member_count;
  const sessions = metric.cohort.session_count;
  const parts = [
    members === null ? "member count unavailable" : pluralMembers(members),
    sessions === null ? null : `${sessions} session${sessions === 1 ? "" : "s"}`,
  ].filter((part): part is string => part !== null);
  const suppression = teamMetricRowStatus(metric.value_state) !== "suppressed"
    ? ""
    : metric.suppression_reason === "overlap_or_differencing"
      ? ` · contributor minimum of ${metric.cohort.minimum_contributor_count} was met; release withheld to prevent overlap/differencing disclosure`
      : metric.suppression_reason === "query_identity_mismatch"
        ? " · release withheld because an immutable query identity was reused with different inputs"
        : metric.suppression_reason === "small_cohort"
          ? ` · contributing subset below minimum of ${metric.cohort.minimum_contributor_count}`
          : " · release withheld by privacy policy; suppression reason unavailable";
  return `${parts.join(" · ")}${suppression}`;
}

export function missingnessLabelFor(metric: TeamMetricAggregate | null): string {
  if (metric === null) return "Missingness not exposed";
  if (teamMetricRowStatus(metric.value_state) === "suppressed") {
    return "Contributor and missing-receipt counts suppressed";
  }
  const { members_with_value: withValue, members_in_cohort: inCohort, sessions_without_receipt: sessionsMissing } = metric.missingness;
  const memberPart = withValue === null || inCohort === null
    ? "member coverage unavailable"
    : `${withValue} of ${inCohort} members have a value`;
  const sessionPart = sessionsMissing === null
    ? ""
    : ` · ${sessionsMissing} session${sessionsMissing === 1 ? "" : "s"} without a receipt`;
  return `${memberPart}${sessionPart}`;
}

export function comparabilityLabelFor(metric: TeamMetricAggregate | null): string {
  if (metric === null) return "Comparability not exposed";
  const versions = metric.comparability.definition_versions.map((version) => `v${version}`).join(", ");
  switch (metric.comparability.state) {
    case "comparable": return `Comparable · definition ${versions}`;
    case "mixed_definition_versions": return `Not comparable · definitions ${versions} mixed`;
    case "mixed_windows": return "Not comparable · analysis windows differ";
    case "not_comparable":
    default: return "Not comparable";
  }
}

export function freshnessLabelFor(metric: TeamMetricAggregate | null): string {
  if (metric === null) return "Freshness not exposed";
  const { newest_receipt_at: newest, stale_member_count: stale, stale_after_days: staleAfter } = metric.freshness;
  if (newest === null) return "No receipt dates";
  const stalePart = stale === null
    ? "stale count unavailable"
    : stale === 0
      ? `no member older than ${staleAfter} days`
      : `${pluralMembers(stale)} older than ${staleAfter} days`;
  return `Newest ${shortUtcDate(newest)} · ${stalePart}`;
}

export function uncertaintyLabelFor(metric: TeamMetricAggregate | null): string {
  if (metric === null || metric.uncertainty.kind !== "interval" || metric.uncertainty.low === null || metric.uncertainty.high === null) {
    return "Not estimated";
  }
  const range = orientRange(metric.uncertainty.low, metric.uncertainty.high, metric.direction);
  return metric.uncertainty.method === "model_range_90"
    ? `Model range ${percent(range.low)}–${percent(range.high)} (central 90%, uncalibrated)`
    : `95% interval ${percent(range.low)}–${percent(range.high)} (Wilson, sampling only)`;
}

export function valueLabelFor(
  measured: TeamMetricAggregate | null,
  status: TeamMetricRowStatus,
  compact = false,
): string {
  if (measured === null || status !== "known" || measured.numeric_value === null) {
    switch (status) {
      case "suppressed": return "Suppressed";
      case "withheld": return "Withheld";
      case "not_applicable": return "N/A";
      case "abstained": return "Needs evidence";
      case "unavailable": return "Unavailable";
      case "missing": return "No record";
      case "unknown":
      default: return "Unknown";
    }
  }
  const fraction = measured.numerator === null || measured.denominator === null
    ? ""
    : ` · ${measured.numerator}/${measured.denominator}`;
  if (measured.direction === "lower_is_better") {
    return compact
      ? `${percent(1 - measured.numeric_value)} rq · raw ${percent(measured.numeric_value)}`
      : `${percent(1 - measured.numeric_value)} radar quality · raw ${percent(measured.numeric_value)}${fraction}`;
  }
  return `${percent(measured.numeric_value)}${fraction}`;
}

/** Rows for one shipped lens, in the lens's fixed axis order. */
export function teamMetricRowsForLens(
  snapshot: TeamAggregateSnapshot | null,
  lensId: ModelEnsembleLensId,
  reviewed: readonly TeamReviewedMetricContract[] = TEAM_REVIEWED_METRIC_CONTRACTS,
): TeamMetricRow[] {
  const columns = teamLensColumns(lensId, reviewed);
  if (columns.length === 0) return [];
  const measuredByKey = new Map<string, TeamMetricAggregate>();
  const experimentalByKey = new Map<string, TeamMetricAggregate>();
  for (const metric of snapshot?.metrics ?? []) {
    if (metric.provenance === "experimental_model") experimentalByKey.set(metric.metric_key, metric);
    else measuredByKey.set(metric.metric_key, metric);
  }
  return columns.map(({ key, label, shortLabel, direction, definitionVersion: version }) => {
    const measured = measuredByKey.get(key) ?? null;
    const experimental = experimentalByKey.get(key) ?? null;
    const status = teamMetricRowStatus(measured?.value_state ?? null);
    const measuredValue = status === "known" && measured !== null ? measured.numeric_value : null;
    const interval = measuredValue !== null
      && measured !== null
      && measured.uncertainty.kind === "interval"
      && measured.uncertainty.low !== null
      && measured.uncertainty.high !== null
      ? orientRange(measured.uncertainty.low, measured.uncertainty.high, direction)
      : null;
    const experimentalValue = experimental !== null && experimental.value_state === "known"
      ? experimental.numeric_value
      : null;
    const experimentalRange = experimentalValue !== null
      && experimental !== null
      && experimental.uncertainty.kind === "interval"
      && experimental.uncertainty.low !== null
      && experimental.uncertainty.high !== null
      ? orientRange(experimental.uncertainty.low, experimental.uncertainty.high, direction)
      : null;
    return {
      key,
      label,
      shortLabel,
      direction,
      definitionVersion: measured?.definition_version ?? version,
      measured,
      experimental,
      status,
      statusLabel: teamMetricStatusLabel(status, measured?.suppression_reason ?? null),
      valueLabel: valueLabelFor(measured, status),
      valueLabelCompact: valueLabelFor(measured, status, true),
      radarQuality: measuredValue === null ? null : orient(measuredValue, direction),
      explicitZero: measuredValue === 0,
      interval,
      experimentalMedian: experimentalValue === null ? null : orient(experimentalValue, direction),
      experimentalRange,
      explainerProvenance: measuredValue !== null ? "measured" : experimentalValue !== null ? "experimental" : "not_measured",
      explainerValue: measuredValue,
      cohortLabel: cohortLabelFor(measured),
      missingnessLabel: missingnessLabelFor(measured),
      comparabilityLabel: comparabilityLabelFor(measured),
      freshnessLabel: freshnessLabelFor(measured),
      uncertaintyLabel: uncertaintyLabelFor(measured),
    };
  });
}

/** Snapshot-level counts shown in headers; state-only rows are counted, never plotted. */
export function teamSnapshotSummary(snapshot: TeamAggregateSnapshot | null): {
  measured: number;
  stateOnly: number;
  experimental: number;
  suppressed: number;
} {
  const metrics = snapshot?.metrics ?? [];
  const measuredRows = metrics.filter((metric) => metric.provenance === "measured_typed");
  return {
    measured: measuredRows.filter((metric) => metric.value_state === "known").length,
    stateOnly: measuredRows.filter((metric) => metric.value_state !== "known").length,
    experimental: metrics.filter((metric) => metric.provenance === "experimental_model" && metric.value_state === "known").length,
    suppressed: measuredRows.filter((metric) => teamMetricRowStatus(metric.value_state) === "suppressed").length,
  };
}

/** Per-member cell text; the same orientation rules as aggregates, never a total. */
export function memberCellLabel(cell: TeamMemberMetricCell | null, direction: MetricDirection): string {
  if (cell === null) return "No record";
  switch (cell.value_state) {
    case "known": {
      if (cell.numeric_value === null) return "Unknown";
      const fraction = cell.numerator === null || cell.denominator === null ? "" : ` · ${cell.numerator}/${cell.denominator}`;
      return direction === "lower_is_better"
        ? `${percent(1 - cell.numeric_value)} rq · raw ${percent(cell.numeric_value)}${fraction}`
        : `${percent(cell.numeric_value)}${fraction}`;
    }
    case "not_applicable": return "N/A";
    case "abstained": return "Needs evidence";
    case "unknown":
    default: return "Unknown";
  }
}

/**
 * Scope · contributors · model · evidence context for one aggregate row. Every
 * sentence is read from the port's typed cohort, missingness, provenance, and
 * uncertainty facts; suppression and withholding stay visible as states and
 * cohort counts are never invented when the port publishes null.
 */
export function teamMetricRowContext(snapshot: TeamAggregateSnapshot, row: TeamMetricRow): MetricContextFacts {
  const measured = row.measured;
  const scopeLabel = `${SCOPE_CONTEXT_LABELS[snapshot.scope]} · ${snapshot.cohort_label}`;
  const description = snapshot.scope === "organization"
    ? "Aggregate over several teams; aggregates only, no team or member ranking."
    : "Aggregate over a consented cohort; aggregates only, no member ranking.";
  const contributors = measured === null
    ? null
    : (() => {
      const cohort = measured.cohort;
      const missing = measured.missingness;
      const size = cohort.member_count === null ? "cohort size not published" : `${cohort.member_count} members in cohort`;
      const withValue = missing.members_with_value === null || missing.members_in_cohort === null
        ? "member coverage not published"
        : `${missing.members_with_value}/${missing.members_in_cohort} contributed a value`;
      const sessions = cohort.session_count === null ? "" : ` · ${cohort.session_count} sessions`;
      return `${size} · ${withValue}${sessions} · minimum ${cohort.minimum_contributor_count} distinct contributors required before any value is published.`;
    })();
  const model = row.experimental === null
    ? null
    : row.experimentalMedian === null
      ? "Experimental model row exists but publishes no informative range · nothing is drawn for it."
      : `Experimental model range (median ${Math.round(row.experimentalMedian * 100)}% radar quality) · a model judgment shown separately as hatched band/diamond, never merged with the measured value.`;
  const evidence = measured === null
    ? "No measured aggregate record for this metric · not observed, not zero, not plotted."
    : measured.value_state === "known"
      ? `${measured.numerator ?? "?"}/${measured.denominator ?? "?"} ratio-of-sums across the cohort · ${measured.uncertainty.method === "wilson_95" ? "95% Wilson sampling interval" : "no interval estimated"} · comparability ${measured.comparability.state.replaceAll("_", " ")}.`
      : `State “${row.statusLabel}”${measured.suppression_reason === null ? "" : ` (${measured.suppression_reason.replaceAll("_", " ")})`} · kept in the state lane, off the numeric axis, and never drawn as zero.`;
  return { scope: snapshot.scope, label: scopeLabel, description, contributors, model, evidence };
}
