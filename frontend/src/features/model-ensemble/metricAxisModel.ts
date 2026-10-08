import type { ModelEnsembleRun } from "../../shared/api/contracts";
import { QUALITY_ANALYSIS_DEFINITIONS } from "../quality-profile/qualityProfile";
import { QUALITY_LENSES } from "../quality-profile/qualityLenses";
import { isDeepModelStage } from "./modelStages";
import {
  metricHelpV2,
  metricInspectorSentences,
  type MetricHelpProjectionVersion,
  type MetricInspectorSentences,
} from "./metricHelpV2";
import { exactPercent, metricGuidanceReceiptSentences } from "./metricGuidanceReceipt";
import { ME_SCOPE_CONTEXT, type MetricContextFacts, type MetricScopeContext } from "./metricContextFacts";
import {
  metricEvidenceReadinessForPublication,
  readableAdapterCapability,
  readableEvidenceAvailability,
  readableEvidenceContributor,
  type MetricEvidenceReadinessRowV2,
} from "./metricEvidenceReadiness";

/**
 * Pure presentation model for the metric workspace: typed lens axes, sealed
 * metric states, lower-is-better radar orientation, predictive visibility, and
 * radar geometry helpers. No React and no transport, so the same truth can back
 * the radar, the exact-value board, the history drawer, tests, and future team
 * views or model catalogs.
 *
 * Invariants kept here:
 * - a non-numeric state (N/A, pending, unknown, error, abstained, missing) is
 *   never converted to zero and never plotted on the numeric scale;
 * - lower-is-better values are oriented as radar quality (1 - raw rate) while
 *   the raw rate stays available for captions;
 * - predictive estimates are separate from measured evidence and are withheld
 *   unless the receipt proves enough small experts and an informative span.
 */
export type ModelEnsembleCommitteeMetric = ModelEnsembleRun["metrics"][number];
export type ModelEnsembleTypedMetric = ModelEnsembleRun["typed_metrics"][number];
export type ModelEnsemblePredictiveMetric = ModelEnsembleRun["predictive_metrics"][number];
type PublishedMetricV2 = NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
type MetricStateV2 = PublishedMetricV2["state"];
export interface ModelEnsembleV2Metric {
  metric_key: string;
  metric_version: number;
  /** Immutable projection identity carried by this exact state receipt. */
  projection_version: MetricStateV2["projection_version"];
  value_state: PublishedMetricV2["state"]["value_state"];
  numerator: number | null;
  denominator: number | null;
  numeric_value: number | null;
  explanation_code: string;
  observed_message_count: number;
  eligible_message_count: number;
  coverage: number;
  projection_source: "metric_contract_v2_live";
  source_kind: "metric_v2";
  implementation_state: PublishedMetricV2["implementation_state"];
  evidence_authority: PublishedMetricV2["state"]["evidence_authority"];
  statistics: PublishedMetricV2["state"]["statistics"];
  /** Exact censoring bounds published by the state receipt (a pending value lies between them); null when unpublished. */
  censoring_lower_bound: number | null;
  censoring_upper_bound: number | null;
  guidance: PublishedMetricV2["guidance"] | null;
  /** Additive evidence-readiness row, only after exact cross-binding to this publication. */
  readiness: MetricEvidenceReadinessRowV2 | null;
}
export type ModelEnsembleMeasuredMetric = ModelEnsembleTypedMetric | ModelEnsembleV2Metric;
export type ModelEnsembleMetric = ModelEnsembleCommitteeMetric | ModelEnsembleMeasuredMetric;
export type ModelEnsembleRadarData = Pick<ModelEnsembleRun, "metrics" | "chunk_metrics"> & {
  typed_metrics: readonly ModelEnsembleTypedMetric[];
  metric_publication_v2?: ModelEnsembleRun["metric_publication_v2"];
  metric_states_v2?: readonly MetricStateV2[];
  metric_evidence_readiness_v2?: unknown;
  predictive_metrics?: readonly ModelEnsemblePredictiveMetric[];
  predictive_model_stages?: ModelEnsembleRun["predictive_model_stages"];
};
export type ModelEnsembleMetricDirection = "higher_is_better" | "lower_is_better";

type TypedMetric = ModelEnsembleMeasuredMetric;
type PredictiveMetric = ModelEnsemblePredictiveMetric;
type EnsembleMetric = ModelEnsembleMetric;
type MetricDirection = ModelEnsembleMetricDirection;

export type ModelEnsembleLensId =
  | "task-framing"
  | "collaboration-flow"
  | "reasoning-trace"
  | "outcome-evidence";

const LENS_IDS = new Set<ModelEnsembleLensId>([
  "task-framing",
  "collaboration-flow",
  "reasoning-trace",
  "outcome-evidence",
]);

export const MODEL_ENSEMBLE_LENSES = QUALITY_LENSES.filter(
  (lens): lens is (typeof QUALITY_LENSES)[number] & { id: ModelEnsembleLensId } =>
    LENS_IDS.has(lens.id as ModelEnsembleLensId),
);

const DEFINITIONS = new Map(
  QUALITY_ANALYSIS_DEFINITIONS.map((definition) => [definition.key, definition]),
);

export function isModelEnsembleTypedMetric(metric: EnsembleMetric): metric is TypedMetric {
  return "projection_source" in metric;
}

export function isModelEnsembleV2Metric(metric: EnsembleMetric): metric is ModelEnsembleV2Metric {
  return "source_kind" in metric && metric.source_kind === "metric_v2";
}

const isTypedMetric = isModelEnsembleTypedMetric;

/**
 * Presentation status for one sealed metric. `pending` is a typed unknown whose
 * episode horizon is still open: candidates were observed, but their follow-up
 * cannot be judged yet. It stays unplotted and is never converted to zero.
 */
export type ModelEnsembleMetricStatus =
  | EnsembleMetric["value_state"]
  | "pending"
  | "missing";

export function modelEnsembleMetricStatus(metric: EnsembleMetric | null): ModelEnsembleMetricStatus {
  if (metric === null) return "missing";
  if (metric.value_state === "pending") return "pending";
  if (
    isTypedMetric(metric)
    && metric.value_state !== "known"
    && metric.explanation_code === "episode_horizon_open"
  ) return "pending";
  return metric.value_state;
}

export function modelEnsembleMetricStatusLabel(status: ModelEnsembleMetricStatus): string {
  switch (status) {
    case "pending": return "pending · horizon open";
    case "missing": return "not observed";
    default: return status.replaceAll("_", " ");
  }
}

/** Status label of a metric (or of a missing one) in one step. */
export function modelEnsembleMetricStateLabel(metric: EnsembleMetric | null): string {
  return modelEnsembleMetricStatusLabel(modelEnsembleMetricStatus(metric));
}

function stateExplanation(metric: EnsembleMetric): string {
  if (isModelEnsembleV2Metric(metric)) {
    if (metric.value_state === "pending") {
      const bounds = modelEnsembleV2CensoringBounds(metric);
      return `Pending: ${metric.statistics.pending_count} of ${metric.statistics.eligible_count} eligible opportunities are still open at the right edge${bounds === null ? "; this receipt published no censoring bounds" : `, so the value is censored between a lower bound of ${exactPercent(bounds.lower)} and an upper bound of ${exactPercent(bounds.upper)}`}. It stays outside the numeric scale until its reviewed horizon closes.`;
    }
    const bounds = modelEnsembleV2CensoringBounds(metric);
    if (
      metric.projection_version === "metric-contract-v2-projection-8"
      && metric.metric_key === "outcome.verified_requirement_coverage"
      && metric.value_state === "unknown"
      && bounds !== null
    ) {
      const interval = `The exact right-censored interval is ${exactPercent(bounds.lower)}–${exactPercent(bounds.upper)}`;
      if (metric.explanation_code === "app_issued_requirement_verification_pending") {
        return `Verification authority is partial: ${metric.statistics.unknown_count} of ${metric.statistics.eligible_count} reviewed requirements remain unresolved. ${interval}; app-issued passing results or separately typed native human acceptances can establish met requirements, while assistant completion claims never count.`;
      }
      if (metric.explanation_code === "requirement_verification_authority_invalid") {
        return `Verification authority is invalid for this exact reviewed requirement set, so every eligible requirement remains unknown. ${interval}; repair the local typed authority and issue a fresh sealed receipt rather than treating missing proof as failure.`;
      }
      return `Verification evidence is unavailable for this exact reviewed requirement set, so every eligible requirement remains unknown. ${interval}; collect app-issued verification results or separately typed native human acceptances, never assistant completion claims.`;
    }
    if (metric.implementation_state === "objective_capability_missing") {
      return metric.statistics.capability_available
        ? "Objective evidence missing: the adapter exposes this objective contract's evidence family, but the compact receipt has no authoritative opportunity set or typed outcome to classify. Keep it unknown until a fresh sealed receipt proves complete denominator and evidence links."
        : "Adapter capability missing: the current adapter cannot measure this objective contract, and no user wording or agent action can fix that. When a supported structured-evidence adapter is available, use its confirmation workflow to emit a fresh typed receipt; until then keep this metric unknown and do not substitute prose.";
    }
    if (metric.evidence_authority === "objective_receipt" && metric.value_state !== "known") {
      return "A typed local action, test, artifact, or acceptance receipt is required. Transcript prose and model estimates cannot create a measured outcome.";
    }
    if (metric.value_state === "unknown") {
      return "The V2 contract cannot establish its opportunity family or resolve its sufficient statistics in this exact window. Unknown is not zero.";
    }
  }
  if (isTypedMetric(metric)) {
    switch (metric.explanation_code) {
      case "episode_horizon_open":
        return "Pending: the newest exchange is still open, so its follow-up cannot be judged yet. The value stays unknown until the episode closes. This is pending evidence, not a zero.";
      case "message_kind_unavailable":
        return "This adapter version does not expose the typed event family required by this metric. This is unavailable evidence, not a zero.";
      case "message_kind_unobserved":
        return "The adapter supports the required event family, but none was observed in this selected window. This is not a zero.";
      case "scope_changes_unobserved":
        return "No explicit scope-change opportunity was detected in this selected window. This is not a zero.";
      case "objective_evidence_stream_required":
      case "objective_verification_episode_required":
      case "objective_verification_stream_required":
        return "A typed local tool, test, artifact, or verification receipt is required. Transcript prose is deliberately not accepted as proof.";
      default:
        break;
    }
  }
  switch (metric.value_state) {
    case "not_applicable":
      return "No eligible denominator was observed in this window.";
    case "unknown":
      return metric.metric_key.startsWith("outcome.")
        ? "Objective test, tool, artifact, or requirement-verification evidence is unavailable. Assistant prose is not accepted as proof."
        : "The required evidence capability or denominator is unavailable.";
    case "abstained":
      return isTypedMetric(metric)
        ? "The typed contract could not establish a defensible denominator for this window."
        : "The opportunity may exist, but the committee did not support a numeric decision.";
    case "execution_error":
      return "Required local inference failed; this is not a low score.";
    default:
      return "No numeric value is available.";
  }
}

/** Exact bounds of a nonnumeric censored V2 receipt, including legal r8 unknown intervals. */
export function modelEnsembleV2CensoringBounds(
  metric: EnsembleMetric | null,
): { lower: number; upper: number } | null {
  if (
    metric === null
    || !isModelEnsembleV2Metric(metric)
    || !["pending", "unknown"].includes(metric.value_state)
  ) return null;
  if (metric.censoring_lower_bound === null || metric.censoring_upper_bound === null) return null;
  return { lower: metric.censoring_lower_bound, upper: metric.censoring_upper_bound };
}

/** Exact bounds of a pending canonical V2 receipt; retained for existing callers. */
export function modelEnsembleV2PendingBounds(
  metric: EnsembleMetric | null,
): { lower: number; upper: number } | null {
  if (metric === null || !isModelEnsembleV2Metric(metric) || metric.value_state !== "pending") return null;
  return modelEnsembleV2CensoringBounds(metric);
}

/** Compact caption for a pending or unknown-censored V2 axis. */
export function modelEnsembleAxisPendingBoundsLabel(axis: Pick<ModelEnsembleRadarAxis, "metric">): string | null {
  const bounds = modelEnsembleV2CensoringBounds(axis.metric);
  return bounds === null ? null : `bounds ${exactPercent(bounds.lower)}–${exactPercent(bounds.upper)}`;
}

/** Short value shown for a non-numeric state (`—` for a known metric without a value). */
export function modelEnsembleMetricStateValue(metric: EnsembleMetric | null): string {
  if (modelEnsembleMetricStatus(metric) === "pending") return "Pending";
  switch (metric?.value_state) {
    case "not_applicable":
      return "N/A";
    case "unknown":
      return "Unknown";
    case "abstained":
      return "Needs evidence";
    case "execution_error":
      return "Error";
    default:
      return metric === null ? "No record" : "—";
  }
}

const stateValue = modelEnsembleMetricStateValue;

export function modelEnsembleMetricPresentation(
  metric: EnsembleMetric,
  direction: MetricDirection,
) {
  const sealedGuidance = isModelEnsembleV2Metric(metric) && metric.guidance !== null;
  if (
    metric.value_state !== "known"
    || metric.numeric_value == null
    || metric.numerator == null
    || metric.denominator == null
  ) {
    return { value: stateValue(metric), detail: sealedGuidance ? null : stateExplanation(metric) };
  }
  const rawPercent = Math.round(metric.numeric_value * 100);
  const radarPercent = direction === "lower_is_better" ? 100 - rawPercent : rawPercent;
  if (direction === "lower_is_better") {
    const source = isModelEnsembleV2Metric(metric)
      ? `${metric.numerator}/${metric.denominator} V2 opportunities`
      : isTypedMetric(metric)
      ? `${metric.numerator}/${metric.denominator} typed opportunities`
      : `${metric.numerator}/${metric.denominator} known eligible observations`;
    return {
      value: `${radarPercent}% radar quality`,
      detail: sealedGuidance
        ? null
        : `Raw lower-is-better rate ${rawPercent}% (${source}). The radar quality is ${radarPercent}%, so a lower observed rate appears farther from the center.`,
    };
  }
  const signalKind = "positive signal";
  if (isModelEnsembleV2Metric(metric)) {
    return {
      value: `${rawPercent}% measured`,
      detail: sealedGuidance
        ? null
        : `${metric.numerator}/${metric.denominator} eligible V2 opportunities met the exact versioned contract. The measured layer is independent of model estimates. Radar ${radarPercent}%.`,
    };
  }
  if (isTypedMetric(metric)) {
    return {
      value: `${rawPercent}% measured`,
      detail: `${metric.numerator}/${metric.denominator} typed opportunities met the versioned local contract. ${metric.observed_message_count}/${metric.eligible_message_count} eligible messages were observed. Radar ${radarPercent}%.`,
    };
  }
  const explicitZero = metric.numerator === 0
    ? " This sealed shadow receipt stored a committee negative, not missing data or a failure score. Typed opportunity eligibility is still required before product use."
    : "";
  return {
    value: `${rawPercent}% signal`,
    detail: `${metric.numerator}/${metric.denominator} known eligible observations contained the ${signalKind}.${explicitZero} Radar ${radarPercent}%.`,
  };
}

export interface ModelEnsembleRadarAxis {
  key: string;
  label: string;
  shortLabel: string;
  direction: MetricDirection;
  question: string;
  metric: EnsembleMetric | null;
  plotted: number | null;
  prediction: PredictiveMetric | null;
  predictiveMedian: number | null;
  predictiveQ05: number | null;
  predictiveQ25: number | null;
  predictiveQ75: number | null;
  predictiveQ95: number | null;
  predictiveWithheldReason: string | null;
}

export const PREDICTIVE_WITHHELD_CONTRIBUTOR_PROOF_MISSING =
  "Withheld because this history point does not expose contributor proof; open the sealed snapshot to check its model stages.";
export const PREDICTIVE_WITHHELD_TOO_FEW_EXPERTS =
  "Withheld because fewer than two small experts are proven by this receipt.";

/**
 * Counts completed small (non-deep) expert stages, or `null` when the receipt
 * does not expose stage receipts at all. A trajectory-only history point has no
 * contributor proof; that is not the same as a sealed receipt proving fewer
 * than two experts.
 */
export function modelEnsembleCompletedSmallExperts(run: ModelEnsembleRadarData): number | null {
  if (run.predictive_model_stages === undefined) return null;
  return run.predictive_model_stages.filter(
    (stage) => stage.status === "completed" && !isDeepModelStage(stage.model_key, stage.repository_id),
  ).length;
}

export function modelEnsemblePredictiveVisibility(
  prediction: PredictiveMetric | null,
  completedSmallExperts: number | null,
): { visible: boolean; reason: string | null } {
  if (prediction === null || prediction.state === "unavailable" || prediction.state === "execution_error") {
    return { visible: false, reason: "No experimental estimate is available." };
  }
  if (prediction.state === "out_of_distribution") {
    return { visible: false, reason: "Withheld because this receipt is outside its calibration cohort." };
  }
  if (completedSmallExperts === null) {
    return { visible: false, reason: PREDICTIVE_WITHHELD_CONTRIBUTOR_PROOF_MISSING };
  }
  if (completedSmallExperts < 2) {
    return { visible: false, reason: PREDICTIVE_WITHHELD_TOO_FEW_EXPERTS };
  }
  if (
    prediction.median == null || prediction.q05 == null || prediction.q25 == null
    || prediction.q75 == null || prediction.q95 == null
  ) return { visible: false, reason: "The estimate does not contain a complete interval summary." };
  if (prediction.q95 - prediction.q05 >= 0.65) {
    return { visible: false, reason: "Uninformative experimental range withheld (90% span is at least 65 points)." };
  }
  return { visible: true, reason: null };
}

export function modelEnsembleDensityBinsForDirection(
  bins: readonly number[],
  direction: MetricDirection,
): number[] {
  return direction === "lower_is_better" ? [...bins].reverse() : [...bins];
}

/**
 * The receipts a surface may read for one sealed run or history point: the
 * typed projection whenever the receipt exposes one, otherwise the legacy
 * committee shadow. The two families are never mixed per key, so a typed
 * unknown, abstained, error, or N/A state can never be replaced by a known
 * committee value, and a key the typed projection does not publish stays
 * "not observed" even if a committee receipt for it exists.
 */
export function modelEnsemblePrimaryMetrics(
  run: Pick<ModelEnsembleRadarData, "metrics" | "typed_metrics" | "metric_publication_v2" | "metric_states_v2" | "metric_evidence_readiness_v2">,
): readonly EnsembleMetric[] {
  const fromState = (
    state: MetricStateV2,
    guidance: PublishedMetricV2["guidance"] | null,
    implementationState: PublishedMetricV2["implementation_state"],
    readiness: MetricEvidenceReadinessRowV2 | null,
  ): ModelEnsembleV2Metric => {
    const statistics = state.statistics;
    const resolved = statistics.met_count + statistics.not_met_count;
    return {
      metric_key: state.metric_key,
      metric_version: guidance?.metric_version ?? 2,
      projection_version: state.projection_version,
      value_state: state.value_state,
      numerator: state.numerator ?? null,
      denominator: state.denominator ?? null,
      numeric_value: state.numeric_value ?? null,
      explanation_code: state.explanation_code,
      observed_message_count: resolved,
      eligible_message_count: statistics.eligible_count,
      coverage: statistics.eligible_count === 0 ? 0 : resolved / statistics.eligible_count,
      projection_source: "metric_contract_v2_live",
      source_kind: "metric_v2",
      implementation_state: implementationState,
      evidence_authority: state.evidence_authority,
      statistics,
      censoring_lower_bound: state.censoring_lower_bound ?? null,
      censoring_upper_bound: state.censoring_upper_bound ?? null,
      guidance,
      readiness,
    };
  };
  if (run.metric_publication_v2 !== undefined && run.metric_publication_v2 !== null) {
    const readiness = metricEvidenceReadinessForPublication(
      run.metric_evidence_readiness_v2,
      run.metric_publication_v2,
    );
    return run.metric_publication_v2.metrics.map((item, index) => (
      fromState(item.state, item.guidance, item.implementation_state, readiness?.metrics[index] ?? null)
    ));
  }
  if ((run.metric_states_v2?.length ?? 0) > 0) {
    return run.metric_states_v2!.map((state) => fromState(
      state,
      null,
      state.value_state === "known" ? "live_measured"
        : state.value_state === "pending" ? "pending"
          : state.value_state === "not_applicable" ? "no_opportunity"
            : state.value_state === "abstained" ? "abstained"
                : state.value_state === "execution_error" ? "error"
                : state.evidence_authority === "objective_receipt"
                  ? (state.statistics.capability_available && state.statistics.eligible_count > 0
                    ? "objective_evidence_unresolved"
                    : "objective_capability_missing")
                  : "method_only_withheld",
      null,
    ));
  }
  return (run.typed_metrics?.length ?? 0) > 0 ? run.typed_metrics : run.metrics;
}

/** Number of objective-authority contracts (of five) the canonical V2 receipt measured, or `null` without a V2 receipt. */
export const MODEL_ENSEMBLE_OBJECTIVE_CONTRACT_COUNT = 5;
export function modelEnsembleObjectiveMeasuredCount(
  run: Pick<ModelEnsembleRadarData, "metric_publication_v2" | "metric_states_v2">,
): number | null {
  if (run.metric_publication_v2 !== undefined && run.metric_publication_v2 !== null) {
    return run.metric_publication_v2.objective_measured_count;
  }
  if ((run.metric_states_v2?.length ?? 0) > 0) {
    return run.metric_states_v2!.filter(
      (state) => state.evidence_authority === "objective_receipt" && state.value_state === "known",
    ).length;
  }
  return null;
}

/**
 * Number of objective-authority contracts (of five) whose sealed state says the
 * current adapter can own their evidence family (`capability_available`), or
 * `null` without a V2 receipt. "Measurable" is derived from the same sealed
 * states as "measured" and is deliberately a separate count: an adapter that
 * can measure five contracts may have measured none of them yet, and the two
 * numbers are never merged. The additive readiness projection, when present,
 * must restate exactly this value.
 */
export function modelEnsembleObjectiveMeasurableCount(
  run: Pick<ModelEnsembleRadarData, "metric_publication_v2" | "metric_states_v2">,
): number | null {
  const states = run.metric_publication_v2 !== undefined && run.metric_publication_v2 !== null
    ? run.metric_publication_v2.metrics.map((item) => item.state)
    : (run.metric_states_v2?.length ?? 0) > 0
      ? run.metric_states_v2!
      : null;
  if (states === null) return null;
  return states.filter(
    (state) => state.evidence_authority === "objective_receipt" && state.statistics.capability_available === true,
  ).length;
}

/** Primary receipts keyed by metric key (a later duplicate key replaces an earlier one, as the radar always did). */
export function modelEnsembleReceiptsByKey(
  run: Pick<ModelEnsembleRadarData, "metrics" | "typed_metrics" | "metric_publication_v2" | "metric_states_v2" | "metric_evidence_readiness_v2">,
): Map<string, EnsembleMetric> {
  return new Map(modelEnsemblePrimaryMetrics(run).map((metric) => [metric.metric_key, metric]));
}

/**
 * Radar-quality value of one receipt: a known numeric value oriented so that
 * higher is always farther from the centre (`1 - raw` for lower-is-better);
 * every other state, a missing receipt, or a known receipt without a numeric
 * value is `null` — unplotted, never zero.
 */
export function modelEnsembleRadarQualityValue(
  metric: EnsembleMetric | null | undefined,
  direction: MetricDirection,
): number | null {
  const raw = metric?.value_state === "known" && metric.numeric_value != null
    ? metric.numeric_value
    : null;
  return raw == null ? null : direction === "lower_is_better" ? 1 - raw : raw;
}

export function modelEnsembleRadarAxes(
  run: ModelEnsembleRadarData,
  lensId: ModelEnsembleLensId,
): ModelEnsembleRadarAxis[] {
  const lens = MODEL_ENSEMBLE_LENSES.find((candidate) => candidate.id === lensId);
  if (lens === undefined) throw new Error("unknown model ensemble lens");
  const metrics = modelEnsembleReceiptsByKey(run);
  const predictions = new Map((run.predictive_metrics ?? []).map((metric) => [metric.metric_key, metric]));
  const completedSmallExperts = modelEnsembleCompletedSmallExperts(run);
  return lens.metrics.map(({ key }) => {
    const definition = DEFINITIONS.get(key);
    if (definition === undefined) throw new Error("model ensemble lens definition is missing");
    const metric = metrics.get(key) ?? null;
    const prediction = predictions.get(key) ?? null;
    const visibility = modelEnsemblePredictiveVisibility(prediction, completedSmallExperts);
    const distribution = visibility.visible;
    const visiblePrediction = distribution ? prediction! : null;
    const orient = (value: number | null | undefined): number | null => value == null
      ? null
      : definition.direction === "lower_is_better" ? 1 - value : value;
    return {
      key,
      label: definition.label,
      shortLabel: definition.shortLabel,
      direction: definition.direction,
      question: definition.question,
      metric,
      plotted: modelEnsembleRadarQualityValue(metric, definition.direction),
      prediction,
      predictiveMedian: distribution ? orient(visiblePrediction!.median) : null,
      predictiveQ05: distribution
        ? definition.direction === "lower_is_better" ? orient(visiblePrediction!.q95) : orient(visiblePrediction!.q05)
        : null,
      predictiveQ25: distribution
        ? definition.direction === "lower_is_better" ? orient(visiblePrediction!.q75) : orient(visiblePrediction!.q25)
        : null,
      predictiveQ75: distribution
        ? definition.direction === "lower_is_better" ? orient(visiblePrediction!.q25) : orient(visiblePrediction!.q75)
        : null,
      predictiveQ95: distribution
        ? definition.direction === "lower_is_better" ? orient(visiblePrediction!.q05) : orient(visiblePrediction!.q95)
        : null,
      predictiveWithheldReason: visibility.reason,
    };
  });
}

/** Adjacent known axes may connect; an unknown axis always breaks the outline. */
export function modelEnsembleRadarSegments(
  axes: readonly ModelEnsembleRadarAxis[],
): Array<readonly [number, number]> {
  if (axes.length < 2) return [];
  const segments: Array<readonly [number, number]> = [];
  axes.forEach((axis, index) => {
    const next = (index + 1) % axes.length;
    if (axis.plotted !== null && axes[next].plotted !== null) {
      segments.push([index, next]);
    }
  });
  return segments;
}

/**
 * Non-numeric states (N/A, pending, unknown, error, abstained, missing) sit in a
 * state lane outside the numeric scale (magnitude > 1). Only a proven numeric
 * zero renders at the center; the value geometry is never shifted.
 */
export const MODEL_ENSEMBLE_STATE_LANE_MAGNITUDE = 1.1;
export const MODEL_ENSEMBLE_WITHHELD_LANE_MAGNITUDE = 1.18;
export function modelEnsembleRadarMarkerMagnitude(plotted: number | null): number {
  if (plotted === null) return MODEL_ENSEMBLE_STATE_LANE_MAGNITUDE;
  return plotted;
}

/** Explicit zero is a property of the sealed raw measurement, not radar geometry. */
export function modelEnsembleIsRawExplicitZero(axis: ModelEnsembleRadarAxis): boolean {
  return axis.metric?.value_state === "known" && axis.metric.numeric_value === 0;
}

export function modelEnsemblePredictiveSegments(
  axes: readonly ModelEnsembleRadarAxis[],
): Array<readonly [number, number]> {
  if (axes.length < 2) return [];
  const segments: Array<readonly [number, number]> = [];
  axes.forEach((axis, index) => {
    const next = (index + 1) % axes.length;
    if (axis.predictiveMedian !== null && axes[next].predictiveMedian !== null) {
      segments.push([index, next]);
    }
  });
  return segments;
}

export function modelEnsemblePredictiveBandPath(
  axes: readonly ModelEnsembleRadarAxis[],
  outer: "predictiveQ95" | "predictiveQ75",
  inner: "predictiveQ05" | "predictiveQ25",
  point: (index: number, magnitude: number) => readonly [number, number],
): string | null {
  if (axes.length < 3 || axes.some((axis) => axis[outer] === null || axis[inner] === null)) {
    return null;
  }
  const outerPoints = axes.map((axis, index) => point(index, axis[outer]!));
  const innerPoints = axes.map((axis, index) => point(index, axis[inner]!)).reverse();
  return `M ${outerPoints.map((value) => value.join(" ")).join(" L ")} Z M ${innerPoints.map((value) => value.join(" ")).join(" L ")} Z`;
}

/**
 * Shared axis-tile presentation. The radar strip and the exact-value board are
 * two surfaces of the same sealed truth; these helpers keep their captions and
 * guidance inputs identical instead of re-deriving them per surface.
 */

/** Source-message coverage (typed) or eligible committee-observation coverage (legacy), 0..1. */
export function modelEnsembleAxisCoverage(axis: ModelEnsembleRadarAxis): number {
  return axis.metric === null
    ? 0
    : isTypedMetric(axis.metric)
      ? axis.metric.coverage
      : axis.metric.total_chunk_count === 0
        ? 0
        : axis.metric.known_chunk_count / axis.metric.total_chunk_count;
}

/** Radar-quality value label for a plotted axis, or the explicit state value when unplotted. */
export function modelEnsembleAxisPlottedLabel(axis: ModelEnsembleRadarAxis): string {
  if (axis.plotted === null) return stateValue(axis.metric);
  return axis.direction === "lower_is_better"
    ? `${Math.round(axis.plotted * 100)}% radar quality`
    : `${Math.round(axis.plotted * 100)}%`;
}

/** Raw lower-is-better rate caption (`raw rate 2%`), or `null` when not applicable. */
export function modelEnsembleAxisRawRateLabel(axis: ModelEnsembleRadarAxis): string | null {
  return axis.direction === "lower_is_better" && axis.metric?.value_state === "known" && axis.metric.numeric_value != null
    ? `raw rate ${Math.round(axis.metric.numeric_value * 100)}%`
    : null;
}

export interface ModelEnsembleAxisEvidence {
  state: EnsembleMetric["value_state"] | "missing";
  numericValue: number | null;
  numerator: number | null;
  denominator: number | null;
  /** Typed explanation code only; committee explanation codes are diagnostics, not guidance input. */
  explanationCode: string | null;
  evidenceAuthority: string | null;
  suppressionReason: null;
  comparabilityState: null;
}

/**
 * The receipt facts every guidance/inspector consumer reads from an axis. A
 * non-known metric never carries a numeric value, so guidance can never treat
 * pending, unknown, N/A, abstained, or error as a measurement.
 */
export function modelEnsembleAxisEvidence(axis: ModelEnsembleRadarAxis): ModelEnsembleAxisEvidence {
  const metric = axis.metric;
  return {
    state: metric?.value_state ?? "missing",
    numericValue: metric?.value_state === "known" ? metric.numeric_value ?? null : null,
    numerator: metric?.numerator ?? null,
    denominator: metric?.denominator ?? null,
    explanationCode: metric !== null && isTypedMetric(metric) ? metric.explanation_code : null,
    evidenceAuthority: metric !== null && isModelEnsembleV2Metric(metric)
      ? metric.evidence_authority
      : metricHelpV2(axis.key, "en")?.entry.objectiveEvidence ?? null,
    suppressionReason: null,
    comparabilityState: null,
  };
}

export interface ModelEnsembleAxisGuidanceOptions {
  /** Weakest predictive factor keys of a VISIBLE experimental estimate (model judgment, never measured). */
  experimentalFactorKeys?: readonly string[];
  experimentalVisible?: boolean;
  experimentalMedian?: number | null;
}

/**
 * The single two-sentence guidance every surface renders for one axis. A
 * canonical V2 receipt with a sealed guidance receipt is rendered from that
 * receipt (state class, template identities, counts, bounds, focus factors) and
 * is never re-decided from the numeric value; a compact V2 history point that
 * carries no guidance receipt keeps its state facts but says so instead of
 * inventing a retain/improve decision; legacy typed and committee receipts use
 * the state-aware inspector. Board, radar inspector, knowledge card and ARIA
 * descriptions all call this, so their action sentences cannot drift apart.
 */
export function modelEnsembleAxisGuidanceSentences(
  axis: ModelEnsembleRadarAxis,
  options: ModelEnsembleAxisGuidanceOptions = {},
): MetricInspectorSentences {
  const evidence = modelEnsembleAxisEvidence(axis);
  const metric = axis.metric;
  const experimentalVisible = options.experimentalVisible ?? axis.predictiveMedian !== null;
  const experimentalMedian = options.experimentalMedian ?? axis.predictiveMedian;
  if (metric !== null && isModelEnsembleV2Metric(metric)) {
    if (metric.guidance !== null) {
      return metricGuidanceReceiptSentences({
        metricKey: axis.key,
        label: axis.label,
        direction: axis.direction,
        projectionVersion: metric.projection_version,
        guidance: metric.guidance,
        evidenceAuthority: metric.evidence_authority,
        explanationCode: metric.explanation_code,
        capabilityAvailable: metric.statistics.capability_available,
      });
    }
    const facts = metricInspectorSentences({
      metricKey: axis.key,
      label: axis.label,
      projectionVersion: metric.projection_version,
      state: evidence.state,
      direction: axis.direction,
      numericValue: evidence.numericValue,
      numerator: evidence.numerator,
      denominator: evidence.denominator,
      explanationCode: evidence.explanationCode,
      evidenceAuthority: evidence.evidenceAuthority,
      suppressionReason: null,
      comparabilityState: null,
      experimentalFactorKeys: options.experimentalFactorKeys,
      experimentalVisible,
      experimentalMedian,
    });
    // A pending or r8 unknown compact row still carries exact censoring bounds; keep them
    // inside the one meaning sentence so the visible inspector and the hidden
    // ARIA description say the same thing.
    const bounds = modelEnsembleV2CensoringBounds(metric);
    const meaning = bounds !== null
      ? `${facts.meaning.replace(/\.$/u, "")}; the value is censored between a lower bound of ${exactPercent(bounds.lower)} and an upper bound of ${exactPercent(bounds.upper)}.`
      : facts.meaning;
    return {
      ...facts,
      meaning,
      action: "No sealed guidance receipt travels with this compact history point, so no retain-or-improve decision is shown here — verify: open the sealed snapshot to read the receipt's action for this metric.",
      basis: facts.kind === "measured" || facts.kind === "zero" ? "method-only" : facts.basis,
    };
  }
  return metricInspectorSentences({
    metricKey: axis.key,
    label: axis.label,
    state: evidence.state,
    direction: axis.direction,
    numericValue: evidence.numericValue,
    numerator: evidence.numerator,
    denominator: evidence.denominator,
    explanationCode: evidence.explanationCode,
    evidenceAuthority: evidence.evidenceAuthority,
    suppressionReason: evidence.suppressionReason,
    comparabilityState: evidence.comparabilityState,
    experimentalFactorKeys: options.experimentalFactorKeys,
    experimentalVisible,
    experimentalMedian,
  });
}

export interface ModelEnsembleKnowledgeEntry {
  key: string;
  label: string;
  status: string;
  /** Projection identity selecting frozen historical or current help copy. */
  projectionVersion: MetricHelpProjectionVersion | null;
  guidance: MetricInspectorSentences;
  context: MetricContextFacts;
}

/**
 * Per-axis contributor / model / evidence facts for the personal (Me) scope.
 * Every sentence is derived from the sealed receipt: a missing or non-known
 * state says so, a withheld model estimate carries its exact reason, and no
 * fact ever converts absence into zero.
 */
export function modelEnsembleAxisContextFacts(
  axis: ModelEnsembleRadarAxis,
  scope: MetricScopeContext = ME_SCOPE_CONTEXT,
): MetricContextFacts {
  const evidence = modelEnsembleAxisEvidence(axis);
  const metric = axis.metric;
  const readiness = metric !== null && isModelEnsembleV2Metric(metric) ? metric.readiness : null;
  const model = axis.predictiveMedian !== null
    ? `Experimental model range visible (median ${Math.round(axis.predictiveMedian * 100)}%) · a model judgment shown separately from measured evidence and never merged with it.`
    : axis.prediction === null || axis.prediction.state === "unavailable"
      ? null
      : axis.predictiveWithheldReason !== null
        ? `Model estimate withheld · ${axis.predictiveWithheldReason}`
        : `Model estimate state “${axis.prediction.state.replaceAll("_", " ")}” · not informative enough to show; nothing is drawn for it.`;
  const evidenceFact = metric === null
    ? "No sealed receipt for this metric in this snapshot · not observed, not zero, not plotted."
    : metric.value_state === "known"
      ? `${evidence.numerator === null || evidence.denominator === null ? "Measured value" : `${evidence.numerator}/${evidence.denominator} resolved opportunities`} · ${evidence.evidenceAuthority ?? "authority not reported by this receipt"}`
      : `State “${modelEnsembleMetricStateLabel(metric)}” · kept off the numeric scale and never drawn as zero · ${evidence.evidenceAuthority ?? "authority not reported by this receipt"}`;
  const readinessFact = readiness === null
    ? evidenceFact
    : `${evidenceFact} · readiness ${readableEvidenceAvailability(readiness.availability_state)} · requirement ${readiness.reason_code.replaceAll("_", " ")}${readiness.required_adapter_capabilities.length === 0 ? "" : ` · adapter proof families ${readiness.required_adapter_capabilities.map(readableAdapterCapability).join(", ")} (supplied by the adapter, not by user wording)`} · calibration not assessed · not product-metric eligible.`;
  return {
    ...scope,
    contributors: readiness === null
      ? scope.scope === "me" ? "One principal (you) · single-installation receipts, no cohort or member rows." : null
      : `${readiness.observed_contributors.length}/${readiness.required_contributors.length} proof contributors observed (evidence families, not people) · missing: ${readiness.missing_contributors.length === 0 ? "none" : readiness.missing_contributors.map(readableEvidenceContributor).join(", ")}.`,
    model,
    evidence: readinessFact,
  };
}

/** Knowledge-card entries (key, label, status label, context) for one lens's axes. */
export function modelEnsembleKnowledgeEntries(
  axes: readonly ModelEnsembleRadarAxis[],
  scope: MetricScopeContext = ME_SCOPE_CONTEXT,
): ModelEnsembleKnowledgeEntry[] {
  return axes.map((axis) => ({
    key: axis.key,
    label: axis.label,
    status: modelEnsembleMetricStateLabel(axis.metric),
    projectionVersion: axis.metric !== null && isModelEnsembleV2Metric(axis.metric)
      ? axis.metric.projection_version
      : null,
    context: modelEnsembleAxisContextFacts(axis, scope),
    guidance: modelEnsembleAxisGuidanceSentences(axis),
  }));
}
