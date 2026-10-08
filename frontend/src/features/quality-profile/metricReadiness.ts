import type {
  MetricEvidenceCapability,
  MetricReadiness,
  MetricReadinessAction,
  MetricReadinessReason,
  MetricReadinessState,
} from "../../shared/api/contracts";
import type { QualityMetricObservation, QualityMetricState } from "./qualityProfile";

const CAPABILITY_LABELS: Record<MetricEvidenceCapability, string> = {
  request_text: "user request text",
  response_text: "agent response text",
  plan_text: "structured plan text",
  action_evidence: "typed ACTION evidence",
  decision_evidence: "typed DECISION evidence",
  feedback_text: "explicit FEEDBACK text",
  objective_verification: "objective VERIFICATION evidence",
};

const STATE_LABELS: Record<MetricReadinessState, string> = {
  known: "Measured",
  unknown: "Unknown",
  unsupported: "Unsupported",
  abstained: "Abstained",
  incompatible: "Incompatible",
  not_applicable: "Not applicable",
  failed: "Failed",
};

const REASON_COPY: Record<MetricReadinessReason, string> = {
  measured: "The latest compatible run produced a persisted metric value.",
  analysis_not_run: "No compatible local analysis has been run for this session.",
  analysis_in_progress: "The latest local analysis is still in progress.",
  result_unknown:
    "The analysis completed, but it could not establish a safe denominator or evidence boundary for this metric.",
  result_abstained:
    "The analyzer deliberately declined to estimate this metric from the available evidence.",
  explicitly_not_applicable:
    "The completed analysis explicitly determined that this metric does not apply to the selected window.",
  provider_capability_missing:
    "The reviewed provider projection does not expose every evidence channel this metric requires.",
  provider_adapter_unavailable:
    "No reviewed provider adapter is available for this metric surface.",
  provider_compatibility_unverified:
    "The installed provider schema has not been checked against the reviewed adapter.",
  provider_incompatible:
    "The installed provider schema is incompatible with the reviewed adapter.",
  provider_unavailable:
    "The provider was unavailable when its cached compatibility status was established.",
  analysis_failed: "The latest local analysis run failed before results were completed.",
  result_failed: "This metric failed inside an otherwise persisted analysis run.",
  result_missing:
    "The completed run did not contain the required result record for this metric.",
  metric_not_selected:
    "The completed run explicitly did not select this metric. It was omitted by scope, not missing or failed.",
  metric_scope_unknown:
    "This legacy run does not preserve its requested metric set, so an absent result cannot be classified as selected or omitted.",
};

const COMPACT_REASON_COPY: Record<MetricReadinessReason, string> = {
  measured: "A stored value is available.",
  analysis_not_run: "This metric has not been analyzed yet.",
  analysis_in_progress: "Local analysis is still in progress.",
  result_unknown: "A safe denominator or evidence boundary was unavailable.",
  result_abstained: "The analyzer declined to estimate this metric.",
  explicitly_not_applicable: "The metric was explicitly marked not applicable.",
  provider_capability_missing: "Required provider evidence is not exposed.",
  provider_adapter_unavailable: "No reviewed provider adapter is available.",
  provider_compatibility_unverified: "Provider compatibility has not been checked.",
  provider_incompatible: "The provider schema is incompatible.",
  provider_unavailable: "The provider was unavailable during its cached check.",
  analysis_failed: "The latest local analysis failed.",
  result_failed: "This metric failed during analysis.",
  result_missing: "The completed run omitted this metric result.",
  metric_not_selected: "This metric was not selected for the completed run.",
  metric_scope_unknown: "The legacy run's metric scope is unknown.",
};

const ACTION_COPY: Record<MetricReadinessAction, string> = {
  none: "No user action is requested for this state.",
  run_local_analysis: "Run local analysis for this session.",
  check_provider_compatibility:
    "Check the installed provider schema against the reviewed adapter.",
  update_provider_adapter: "Update Prompt Enhancer's reviewed provider adapter.",
  collect_action_evidence: "Import typed ACTION evidence from a supported provider event.",
  collect_decision_evidence:
    "Import typed DECISION evidence from a supported provider event.",
  collect_feedback_evidence: "Include explicit FEEDBACK evidence in a supported source.",
  collect_objective_verification:
    "Provide objective VERIFICATION evidence such as tests, artifacts, or explicit acceptance.",
  review_applicability:
    "Review whether the metric applies and whether its denominator exists in this window.",
  review_evidence_coverage: "Review which required evidence channels were observed.",
  retry_analysis: "Retry local analysis after checking the local service and provider adapter.",
  select_metric_for_analysis:
    "Select this metric for a new local analysis run if you want a current value.",
};

const COMPACT_ACTION_COPY: Record<MetricReadinessAction, string> = {
  none: "No action needed.",
  run_local_analysis: "Run local analysis.",
  check_provider_compatibility: "Check provider compatibility.",
  update_provider_adapter: "Update the reviewed adapter.",
  collect_action_evidence: "Add ACTION evidence.",
  collect_decision_evidence: "Add DECISION evidence.",
  collect_feedback_evidence: "Add FEEDBACK evidence.",
  collect_objective_verification: "Add objective VERIFICATION.",
  review_applicability: "Review applicability.",
  review_evidence_coverage: "Review evidence coverage.",
  retry_analysis: "Retry local analysis.",
  select_metric_for_analysis: "Select this metric for analysis.",
};

const EXPECTED_READINESS_STATES: Record<QualityMetricState, readonly MetricReadinessState[]> = {
  observed: ["known"],
  partial: ["known"],
  "not-selected": ["unknown"],
  incompatible: ["incompatible"],
  unavailable: ["unknown", "unsupported", "failed"],
  abstained: ["abstained"],
  "not-applicable": ["not_applicable"],
  "execution-error": ["failed"],
};

const EXPECTED_REASONS: Record<MetricReadinessState, readonly MetricReadinessReason[]> = {
  known: ["measured"],
  unknown: [
    "analysis_not_run",
    "analysis_in_progress",
    "result_unknown",
    "provider_compatibility_unverified",
    "metric_not_selected",
    "metric_scope_unknown",
  ],
  unsupported: ["provider_capability_missing", "provider_adapter_unavailable"],
  abstained: ["result_abstained"],
  incompatible: ["provider_incompatible"],
  not_applicable: ["explicitly_not_applicable"],
  failed: ["provider_unavailable", "analysis_failed", "result_failed", "result_missing"],
};

export interface MetricReadinessExplanation {
  readonly actionCopy: readonly string[];
  readonly compactActionCopy: string;
  readonly compactEvidenceCopy: string;
  readonly compactReasonCopy: string;
  readonly evidenceCopy: string;
  readonly label: string;
  readonly reasonCopy: string;
  readonly state: MetricReadinessState | "metadata_mismatch";
}

export function readinessIdentity(metric: {
  metric_key: string;
  metric_version: number;
}): string {
  return `${metric.metric_key}@${metric.metric_version}`;
}

export function indexMetricReadiness(
  metrics: readonly MetricReadiness[] | null | undefined,
): ReadonlyMap<string, MetricReadiness> {
  const index = new Map<string, MetricReadiness>();
  const duplicates = new Set<string>();
  for (const metric of metrics ?? []) {
    if (
      typeof metric?.metric_key !== "string" ||
      metric.metric_key.length === 0 ||
      !Number.isSafeInteger(metric.metric_version) ||
      metric.metric_version < 1
    ) {
      continue;
    }
    const identity = readinessIdentity(metric);
    if (index.has(identity)) {
      duplicates.add(identity);
      index.delete(identity);
    } else if (!duplicates.has(identity)) {
      index.set(identity, metric);
    }
  }
  return index;
}

function isKnownCapability(value: unknown): value is MetricEvidenceCapability {
  return (
    typeof value === "string" &&
    Object.prototype.hasOwnProperty.call(CAPABILITY_LABELS, value)
  );
}

function isKnownAction(value: unknown): value is MetricReadinessAction {
  return (
    typeof value === "string" &&
    Object.prototype.hasOwnProperty.call(ACTION_COPY, value)
  );
}

function readinessMetadataIsWellFormed(readiness: MetricReadiness): boolean {
  const actions = readiness.next_actions;
  const missingCapabilities = readiness.missing_capabilities;
  const availableCapabilities = readiness.available_capabilities;
  const capabilityGroups = readiness.capability_groups;
  return (
    Object.prototype.hasOwnProperty.call(STATE_LABELS, readiness.state) &&
    Object.prototype.hasOwnProperty.call(REASON_COPY, readiness.reason_code) &&
    EXPECTED_REASONS[readiness.state]?.includes(readiness.reason_code) === true &&
    Array.isArray(actions) &&
    actions.length > 0 &&
    new Set(actions).size === actions.length &&
    actions.every(isKnownAction) &&
    (!actions.includes("none") || actions.length === 1) &&
    Array.isArray(missingCapabilities) &&
    new Set(missingCapabilities).size === missingCapabilities.length &&
    missingCapabilities.every(isKnownCapability) &&
    Array.isArray(availableCapabilities) &&
    new Set(availableCapabilities).size === availableCapabilities.length &&
    availableCapabilities.every(isKnownCapability) &&
    Array.isArray(capabilityGroups) &&
    capabilityGroups.every(
      (group) =>
        Array.isArray(group) &&
        new Set(group).size === group.length &&
        group.every(isKnownCapability),
    )
  );
}

function capabilityList(capabilities: readonly MetricEvidenceCapability[]): string {
  return capabilities.map((capability) => CAPABILITY_LABELS[capability]).join(", ");
}

function capabilityRequirement(
  groups: readonly (readonly MetricEvidenceCapability[])[],
): string {
  return groups
    .map((group) => group.map((capability) => CAPABILITY_LABELS[capability]).join(" or "))
    .join("; plus ");
}

function evidenceCopy(readiness: MetricReadiness): string {
  if (readiness.reason_code === "metric_not_selected") {
    return "No result was expected for this metric in the exact stored run scope; no failure or zero is inferred.";
  }
  if (readiness.reason_code === "metric_scope_unknown") {
    return "The legacy run has no recoverable selection receipt, so the absent value remains unknown rather than failed.";
  }
  if (readiness.missing_capabilities.length > 0) {
    return `Missing evidence channels: ${capabilityList(readiness.missing_capabilities)}.`;
  }
  if (readiness.state === "incompatible") {
    return "Evidence requirements cannot be checked until provider compatibility is resolved.";
  }
  if (readiness.state === "failed") {
    return "The stored evidence and prior metric state remain unchanged; no value was inferred from the failure.";
  }
  if (readiness.state === "not_applicable") {
    return "No additional evidence is requested for a metric explicitly marked not applicable.";
  }
  if (readiness.state === "known") {
    return "The persisted value remains the authoritative observation.";
  }
  return `Evidence requirement: ${capabilityRequirement(readiness.capability_groups)}.`;
}

function compactEvidenceCopy(readiness: MetricReadiness): string {
  if (readiness.reason_code === "metric_not_selected") {
    return "Omitted by exact run scope; not failed.";
  }
  if (readiness.reason_code === "metric_scope_unknown") {
    return "Legacy run scope is unavailable.";
  }
  if (readiness.missing_capabilities.length > 0) {
    return `Missing: ${capabilityList(readiness.missing_capabilities)}.`;
  }
  if (readiness.state === "incompatible") return "Resolve provider compatibility first.";
  if (readiness.state === "failed") return "No value was inferred from the failure.";
  if (readiness.state === "not_applicable") return "No further evidence is needed.";
  if (readiness.state === "known") return "Stored value is authoritative.";
  return `Needs: ${capabilityRequirement(readiness.capability_groups)}.`;
}

export function explainMetricReadiness(
  observation: QualityMetricObservation,
  readiness: MetricReadiness | null | undefined,
): MetricReadinessExplanation | null {
  if (readiness === null || readiness === undefined) return null;
  if (
    readiness.metric_key !== observation.definition.key ||
    readiness.metric_version !== observation.definition.version
  ) {
    return null;
  }

  if (
    !EXPECTED_READINESS_STATES[observation.state].includes(readiness.state) ||
    !readinessMetadataIsWellFormed(readiness)
  ) {
    return {
      actionCopy: [
        "Refresh readiness metadata or rerun the compatible local analysis before acting on it.",
      ],
      compactActionCopy: "Refresh readiness metadata.",
      compactEvidenceCopy: "Stored value state is authoritative.",
      compactReasonCopy: "Stored value and readiness metadata disagree.",
      evidenceCopy:
        "The persisted metric state and value remain authoritative; readiness metadata cannot create, erase, or replace them.",
      label: "Readiness metadata mismatch",
      reasonCopy:
        "The explanatory readiness state does not match the stored metric result state.",
      state: "metadata_mismatch",
    };
  }

  return {
    actionCopy: readiness.next_actions.map((action) => ACTION_COPY[action]),
    compactActionCopy:
      COMPACT_ACTION_COPY[readiness.next_actions[0]] ??
      "Refresh readiness metadata.",
    compactEvidenceCopy: compactEvidenceCopy(readiness),
    compactReasonCopy: COMPACT_REASON_COPY[readiness.reason_code],
    evidenceCopy: evidenceCopy(readiness),
    label: STATE_LABELS[readiness.state],
    reasonCopy: REASON_COPY[readiness.reason_code],
    state: readiness.state,
  };
}
