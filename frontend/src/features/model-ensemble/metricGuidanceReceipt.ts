import type { ModelEnsembleRun } from "../../shared/api/contracts";
import {
  MAX_GUIDANCE_FOCUS_FACTOR_KEYS,
  METRIC_CONTRACT_V2_REGISTRY_VERSION,
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
  METRIC_V2_KEYS,
  expectedMetricGuidanceTemplateIdentities,
} from "../../shared/api/metricPublicationV2Contract";
import { metricDecisionGuidance } from "../quality-profile/metricGuidance";
import {
  metricHelpV2,
  observationUnitCounted,
  observationUnitSingular,
  type MetricHelpProjectionVersion,
  type MetricInspectorKind,
  type MetricInspectorSentences,
} from "./metricHelpV2";

/**
 * Canonical V2 guidance presentation.
 *
 * The producer publishes one sealed, content-free guidance receipt per metric:
 * a state class, three template identities, a basis, counts, censoring bounds,
 * and (only when per-factor statistics were measured) up to two focus factor
 * keys. This module turns that receipt into exactly two deterministic sentences
 * — meaning and action — without ever re-deciding the state class from the
 * numeric value. Every surface (full board, radar inspector, knowledge card,
 * compact overlay, ARIA descriptions) reads the same two sentences from here.
 *
 * The wording is bound to one exact registry version, contract-set fingerprint
 * and template catalog version; a receipt from any other identity is refused
 * upstream by the compatibility gate and never rendered beside fresh values.
 */
export const METRIC_GUIDANCE_PRESENTATION_BINDING = {
  registryVersion: METRIC_CONTRACT_V2_REGISTRY_VERSION,
  contractSetFingerprint: METRIC_CONTRACT_V2_SET_FINGERPRINT,
  templateCatalogVersion: METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
  templateVersion: 1,
} as const;

export type MetricGuidanceReceipt = NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number]["guidance"];
export type MetricGuidanceStateClass = MetricGuidanceReceipt["state_class"];
export type MetricGuidanceDirection = "higher_is_better" | "lower_is_better";

export const METRIC_GUIDANCE_STATE_CLASSES: readonly MetricGuidanceStateClass[] = [
  "known_retain", "known_improve", "pending_closure", "objective_evidence_missing",
  "objective_evidence_unresolved", "evidence_unresolved", "no_opportunity",
  "evidence_coverage_abstained", "analysis_failed",
];

/** The three template identities the producer publishes for one metric and state class (mirrors the catalog). */
export function metricGuidanceTemplateIds(
  metricKey: string,
  stateClass: MetricGuidanceStateClass,
): { diagnosis: string; action: string; verification: string } {
  return expectedMetricGuidanceTemplateIdentities(metricKey, stateClass);
}

function lowerFirst(value: string): string {
  return value.charAt(0).toLowerCase() + value.slice(1);
}

function stripEnd(value: string): string {
  return value.trim().replace(/[.\s]+$/u, "");
}

/** Reviewed wording for the generic (metric-independent) action and verification templates. */
const GENERIC_TEMPLATE_TEXT: Readonly<Record<string, string>> = {
  "action.await_opportunity_closure": "Nothing to change yet: the open opportunity must close before this metric can be judged, so it is pending rather than measured or zero",
  "verification.await_opportunity_closure": "re-measure after the episode horizon closes; only then is a value decidable",
  "action.collect_objective_receipt": "No user wording or agent action can supply this value: when a supported structured-evidence adapter is available, use its confirmation workflow to emit typed tool, test, artifact, or acceptance receipts; until then keep the metric unknown",
  "verification.objective_receipt_scope": "adapter readiness — a supported adapter produces a fresh sealed receipt scoped to this metric; collecting more prose is not verification",
  "action.resolve_objective_evidence": "Resolve the opportunities the existing typed receipt leaves open rather than collecting a new receipt",
  "verification.objective_evidence_completeness": "the unresolved count reaches zero across every eligible opportunity before any value is read",
  "action.hold_state_unknown": "Keep this metric unknown until its opportunity family and evidence are observable; do not read it as low",
  "verification.review_opportunity_evidence": "review the opportunity and evidence this contract needs and re-measure once they are present",
  "action.no_change_required": "No change is required: no eligible opportunity existed in this window",
  "verification.reassess_on_new_opportunity": "reassess only when a later comparable window contains an eligible opportunity",
  "action.review_evidence_coverage": "Review evidence coverage for this window; the analysis abstained instead of guessing",
  "verification.review_evidence_coverage": "confirm the required evidence is present in a later sealed receipt before reading a value",
  "action.repair_local_analysis_stage": "Repair or retry the failed local analysis stage; the last valid receipt stands",
  "verification.fresh_sealed_receipt": "a fresh sealed receipt completes without error before this metric is compared",
};

/**
 * Resolve one template identity to reviewed wording, or `null` when this client
 * ships no wording for it. Metric-specific templates map onto the reviewed
 * decision-guidance registry (diagnosis = why it matters, improve = try next,
 * verification = confirm with); retain wording is metric-scoped.
 */
export function metricGuidanceTemplateText(
  templateIdentity: string,
  projectionVersion: MetricHelpProjectionVersion | null = null,
): string | null {
  const match = /^(diagnosis|action\.retain|action\.improve|verification|action\.[a-z_]+|verification\.[a-z_]+)(?:\.([a-z]+\.[a-z_]+))?\.v(\d+)$/u.exec(templateIdentity);
  if (match === null) return null;
  const [, family, metricKey, version] = match;
  if (Number(version) !== METRIC_GUIDANCE_PRESENTATION_BINDING.templateVersion) return null;
  if (metricKey === undefined) {
    return GENERIC_TEMPLATE_TEXT[family] ?? null;
  }
  if (!METRIC_V2_KEYS.includes(metricKey as typeof METRIC_V2_KEYS[number])) return null;
  const decision = metricDecisionGuidance(metricKey);
  const help = metricHelpV2(metricKey, "en", projectionVersion)?.entry;
  switch (family) {
    case "diagnosis":
      return stripEnd(decision.whyItMatters);
    case "action.retain":
      return `Retain: keep the practice that produced this ${observationUnitSingular(help?.observationUnit ?? "observation")} result visible in the next comparable task instead of adding process for it`;
    case "action.improve":
      return stripEnd(decision.tryNext);
    case "verification":
      return stripEnd(decision.confirmWith);
    default:
      return null;
  }
}

function readableFactor(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

function readableCode(value: string): string {
  return value.replaceAll("_", " ");
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Exact bound as a percentage with at most one decimal (`33.3%`), never silently rounded to a whole. */
export function exactPercent(value: number): string {
  const scaled = Math.round(value * 1000) / 10;
  return `${Number.isInteger(scaled) ? scaled.toFixed(0) : scaled.toFixed(1)}%`;
}

export interface MetricGuidanceReceiptInput {
  metricKey: string;
  label: string;
  direction: MetricGuidanceDirection;
  /** Projection identity carried by the exact sealed state beside this guidance. */
  projectionVersion: MetricHelpProjectionVersion;
  guidance: MetricGuidanceReceipt;
  /** Authority declared by the exact V2 state receipt (never inferred). */
  evidenceAuthority: string | null;
  /** Explanation code from the exact V2 state receipt. */
  explanationCode: string | null;
  /** Whether the sealed state says this adapter can own the metric's evidence family. */
  capabilityAvailable?: boolean;
}

function kindFor(
  stateClass: MetricGuidanceStateClass,
  radarQuality: number | null,
  capabilityAvailable?: boolean,
): MetricInspectorKind {
  switch (stateClass) {
    case "known_retain":
    case "known_improve":
      return radarQuality === 0 ? "zero" : "measured";
    case "pending_closure": return "pending";
    case "objective_evidence_missing": return capabilityAvailable === false ? "unavailable" : "unknown";
    case "objective_evidence_unresolved": return "unknown";
    case "evidence_unresolved": return "unknown";
    case "no_opportunity": return "not_applicable";
    case "evidence_coverage_abstained": return "abstained";
    case "analysis_failed": return "execution_error";
    default: return "unknown";
  }
}

function stateFor(stateClass: MetricGuidanceStateClass): MetricInspectorSentences["state"] {
  switch (stateClass) {
    case "known_retain":
    case "known_improve": return "known";
    case "pending_closure": return "pending";
    case "no_opportunity": return "not_applicable";
    case "evidence_coverage_abstained": return "abstained";
    case "analysis_failed": return "execution_error";
    default: return "unknown";
  }
}

/** Exact censoring bounds of a pending or unknown-censored receipt. */
export function metricGuidanceCensoringBounds(
  guidance: Pick<MetricGuidanceReceipt, "censoring_lower_bound" | "censoring_upper_bound">,
): { lower: number; upper: number } | null {
  const lower = guidance.censoring_lower_bound ?? null;
  const upper = guidance.censoring_upper_bound ?? null;
  return lower === null || upper === null ? null : { lower, upper };
}

/** Focus factors this receipt may name: at most two, and only from measured per-factor statistics. */
export function metricGuidanceFocusFactors(
  guidance: Pick<MetricGuidanceReceipt, "factor_evidence" | "focus_factor_keys">,
): readonly string[] {
  if (guidance.factor_evidence !== "per_factor_measured") return [];
  return [...new Set(guidance.focus_factor_keys)].slice(0, MAX_GUIDANCE_FOCUS_FACTOR_KEYS);
}

/**
 * Exactly two deterministic sentences from one sealed guidance receipt. The
 * state class is rendered as published — a `known_retain` receipt retains even
 * when not every factor was met — and the numeric value is only ever quoted,
 * never used to choose the sentence family.
 */
export function metricGuidanceReceiptSentences(input: MetricGuidanceReceiptInput): MetricInspectorSentences {
  const { guidance, label, direction } = input;
  const observationUnit = metricHelpV2(
    input.metricKey,
    "en",
    input.projectionVersion,
  )?.entry.observationUnit ?? "observation";
  /** "opportunities (one per agent question)" for counts and fractions. */
  const unit = observationUnitCounted(observationUnit);
  /** "agent question" for "no eligible … was observed". */
  const unitSingular = observationUnitSingular(observationUnit);
  const diagnosisId = guidance.diagnosis_template_id;
  const actionId = guidance.action_template_id;
  const verificationId = guidance.verification_template_id;
  const diagnosis = metricGuidanceTemplateText(diagnosisId, input.projectionVersion)
    ?? `this client has no reviewed wording for template ${diagnosisId}`;
  const actionText = metricGuidanceTemplateText(actionId, input.projectionVersion)
    ?? `No reviewed action wording for template ${actionId}; treat the state class “${readableCode(guidance.state_class)}” as the decision`;
  const verificationText = metricGuidanceTemplateText(verificationId, input.projectionVersion)
    ?? `no reviewed verification wording for template ${verificationId}`;
  const numerator = guidance.numerator ?? null;
  const denominator = guidance.denominator ?? null;
  const rawValue = numerator !== null && denominator !== null ? numerator / denominator : null;
  const radarQuality = rawValue === null ? null : direction === "lower_is_better" ? 1 - rawValue : rawValue;
  const kind = kindFor(guidance.state_class, radarQuality, input.capabilityAvailable);
  const eligible = guidance.eligible_count;
  const notMet = guidance.not_met_count;
  const bounds = metricGuidanceCensoringBounds(guidance);
  const focus = metricGuidanceFocusFactors(guidance).map(readableFactor);
  const reason = readableCode(guidance.reason_code);
  const fraction = numerator !== null && denominator !== null
    ? `${numerator}/${denominator} ${unit}`
    : `an unexposed fraction of ${unit}`;
  const valueClause = rawValue === null
    ? ""
    : direction === "lower_is_better"
      ? `a raw rate of ${percent(rawValue)}, radar quality ${percent(radarQuality!)} because lower is better`
      : `exactly ${percent(rawValue)}`;
  const basisClause = guidance.basis === "method-only" && guidance.factor_evidence === "aggregate_only"
    ? " on aggregate-only factor evidence, so no individual factor is named"
    : "";
  const r8VerifiedRequirement = input.projectionVersion === "metric-contract-v2-projection-8"
    && input.metricKey === "outcome.verified_requirement_coverage";
  const boundsClause = bounds === null
    ? "this receipt published no censoring bounds"
    : `the exact right-censored interval is ${exactPercent(bounds.lower)}–${exactPercent(bounds.upper)}`;
  const optionalBoundsClause = bounds === null ? "" : `; ${boundsClause}`;

  let meaning: string;
  let action = `${stripEnd(actionText)} — verify: ${lowerFirst(stripEnd(verificationText))}.`;
  switch (guidance.state_class) {
    case "known_retain":
      meaning = `Measured: ${fraction} met the contract for ${label} (${valueClause}), and the sealed guidance receipt classes it as retain${notMet > 0 ? ` even though ${notMet} ${notMet === 1 ? "opportunity" : "opportunities"} did not meet it` : ""}${basisClause}; this is a receipt decision, not a validated quality band — ${lowerFirst(diagnosis)}.`;
      break;
    case "known_improve": {
      const focusClause = focus.length > 0 ? `Focus on ${focus.join(" and ")} (measured per-factor statistics): ` : "";
      meaning = `Measured: ${fraction} met the contract for ${label} (${valueClause}), and the sealed guidance receipt classes it as improve${basisClause}; this is a receipt decision, not a validated quality band — ${lowerFirst(diagnosis)}.`;
      action = `${focusClause}${stripEnd(actionText)} — verify: ${lowerFirst(stripEnd(verificationText))}.`;
      break;
    }
    case "pending_closure": {
      const pendingBoundsClause = bounds === null
        ? "this receipt published no censoring bounds"
        : `the value is censored between a lower bound of ${exactPercent(bounds.lower)} and an upper bound of ${exactPercent(bounds.upper)}`;
      meaning = `Pending: ${guidance.pending_count} of ${eligible} ${unit} ${guidance.pending_count === 1 ? "is" : "are"} still open at the right edge of the window, so ${pendingBoundsClause}; this is open evidence, not a measurement and not a zero — ${lowerFirst(diagnosis)}.`;
      break;
    }
    case "objective_evidence_missing":
      if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_authority_unavailable") {
        meaning = `Reviewed requirement authority missing: no exact reviewed active-requirement set is available for ${label}, so no denominator or value exists and this is not zero — ${lowerFirst(diagnosis)}.`;
        action = "Complete and natively confirm the reviewed requirement-plan authority, then run a fresh sealed r8 analysis — verify: every active requirement is bound before any verification result or acceptance is interpreted.";
      } else if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_authority_invalid") {
        meaning = `Reviewed requirement authority invalid: the denominator for ${label} failed exact source-window validation, so the metric stays unknown rather than scoring stale requirements — ${lowerFirst(diagnosis)}.`;
        action = "Replace the invalid requirement-plan authority through the native review workflow, then run a fresh sealed r8 analysis — verify: the new receipt binds the exact current confirmation and requirement set.";
      } else if (r8VerifiedRequirement && input.explanationCode === "typed_objective_opportunity_count_exceeds_receipt_bound") {
        meaning = `Receipt bound exceeded: the complete reviewed requirement set for ${label} is larger than the bounded local verification receipt, so it was withheld rather than truncated, sampled, or converted to zero — ${lowerFirst(diagnosis)}.`;
        action = "Analyze a smaller coherent sealed window without dropping individual requirements from its complete authority — verify: the complete reviewed set fits the published receipt bound before reading a value.";
      } else if (input.capabilityAvailable === false) {
        meaning = `Adapter capability missing: the current adapter cannot measure ${label}, and no user wording or agent action can fix that; no typed receipt exists for this window (reason: ${reason}), so this is missing capability, not a low value — ${lowerFirst(diagnosis)}.`;
      } else {
        meaning = `Objective evidence missing: the adapter exposes the required evidence family for ${label}, but this sealed window has no authoritative opportunity set or typed receipt to classify (reason: ${reason}), so no value exists and this is not a low value — ${lowerFirst(diagnosis)}.`;
      }
      break;
    case "objective_evidence_unresolved":
      if (r8VerifiedRequirement && input.explanationCode === "requirement_verification_evidence_unavailable") {
        meaning = `Verification evidence unavailable: the reviewed denominator contains ${eligible} ${unit}, but all ${guidance.unknown_count} remain unresolved; ${boundsClause}. App-issued verification results or separately typed native human acceptances are required, and assistant completion claims never count — ${lowerFirst(diagnosis)}.`;
        action = "Restore the local verification-evidence reader or issue exact typed verification results or native acceptances, then run a fresh sealed r8 analysis — verify: the new receipt preserves the reviewed denominator and resolves authority without using prose.";
      } else if (r8VerifiedRequirement && input.explanationCode === "requirement_verification_authority_invalid") {
        meaning = `Verification authority invalid: the typed authority did not validate against this exact reviewed requirement set, so all ${guidance.unknown_count} of ${eligible} ${unit} remain unresolved; ${boundsClause}, never zero — ${lowerFirst(diagnosis)}.`;
        action = "Repair or replace the invalid local verification authority and run a fresh sealed r8 analysis — verify: every app-issued result or separately typed native acceptance matches the exact current requirement opportunity.";
      } else if (r8VerifiedRequirement && input.explanationCode === "app_issued_requirement_verification_pending") {
        meaning = `Verification authority is partial: exact local authority resolves ${eligible - guidance.unknown_count} of ${eligible} ${unit} and leaves ${guidance.unknown_count} unresolved; ${boundsClause}. App-issued passing results or separately typed native human acceptances establish met requirements, while assistant completion claims never count — ${lowerFirst(diagnosis)}.`;
        action = "Resolve the remaining reviewed requirements with app-issued verification results or separately typed native human acceptances — verify: a fresh sealed r8 receipt reaches zero unresolved requirements before publishing a numeric value.";
      } else {
        meaning = `Objective evidence unresolved: a typed receipt exists for ${label} but leaves ${guidance.unknown_count} of ${eligible} ${unit} unresolved (reason: ${reason})${optionalBoundsClause}, so no value is published and this is not a low value — ${lowerFirst(diagnosis)}.`;
      }
      break;
    case "evidence_unresolved":
      meaning = `Unknown: the contract could not establish the opportunity family or resolve the sufficient statistics ${label} needs in this window (reason: ${reason}), so no value exists and it is not a low value — ${lowerFirst(diagnosis)}.`;
      break;
    case "no_opportunity":
      if (r8VerifiedRequirement && input.explanationCode === "reviewed_requirement_set_empty") {
        meaning = `Not applicable: the exact reviewed active-requirement set is empty, so ${label} has no denominator and no value is implied — ${lowerFirst(diagnosis)}.`;
        action = "No verification action is justified for this empty reviewed set — verify: reassess only after a fresh native review establishes at least one active requirement.";
      } else {
        meaning = `Not applicable: no eligible ${unitSingular} was observed in this window, so ${label} has nothing to score and no value is implied — ${lowerFirst(diagnosis)}.`;
      }
      break;
    case "evidence_coverage_abstained":
      meaning = `Needs evidence: the local contract abstained for ${label} instead of guessing (reason: ${reason}); nothing was scored and this is not a low value — ${lowerFirst(diagnosis)}.`;
      break;
    case "analysis_failed":
      meaning = `Error: the local analysis stage for ${label} failed before producing a value (reason: ${reason}); the last valid receipt stands and this is not a low score — ${lowerFirst(diagnosis)}.`;
      break;
    default:
      meaning = `State “${readableCode(guidance.state_class)}” for ${label}: no value is published — ${lowerFirst(diagnosis)}.`;
      break;
  }
  return {
    kind,
    state: stateFor(guidance.state_class),
    meaning,
    action,
    audience: guidance.audience,
    basis: guidance.basis,
    evidenceAuthority: input.evidenceAuthority,
    explanationCode: input.explanationCode ?? guidance.reason_code,
    suppressionReason: null,
    comparabilityState: null,
  };
}
