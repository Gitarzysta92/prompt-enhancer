import { titleFromKey } from "../../shared/lib/format";

export type MetricGroupId =
  | "data-readiness"
  | "operational-effort"
  | "verification-evidence"
  | "other-observations";

export interface MetricGroupPresentation {
  id: MetricGroupId;
  eyebrow: string;
  title: string;
  question: string;
  description: string;
  order: number;
}

export interface MetricPresentation {
  dimension: string;
  displayName: string;
  question: string;
  group: MetricGroupPresentation;
}

const GROUPS: Record<MetricGroupId, MetricGroupPresentation> = {
  "data-readiness": {
    id: "data-readiness",
    eyebrow: "Interpretation first",
    title: "Data readiness",
    question: "How much of the eligible evidence is visible in this current snapshot?",
    description:
      "Coverage describes observability. It is not a task-quality score, and partial evidence limits every downstream interpretation.",
    order: 10,
  },
  "operational-effort": {
    id: "operational-effort",
    eyebrow: "Descriptive metrics",
    title: "Operational effort",
    question: "What workload and workflow activity are visible in this current snapshot?",
    description:
      "Counts, durations, token subtotals, and tool lifecycle results describe observed activity. They do not prove task success, and lower or higher values are not inherently better.",
    order: 20,
  },
  "verification-evidence": {
    id: "verification-evidence",
    eyebrow: "Outcome evidence",
    title: "Verification and outcome evidence",
    question: "What checks, tool results, or terminal states were actually observed?",
    description:
      "These observations remain separate from effort metrics and do not prove task completion without objective evidence.",
    order: 30,
  },
  "other-observations": {
    id: "other-observations",
    eyebrow: "Extensible metrics",
    title: "Other observations",
    question: "What else was measured in this current snapshot?",
    description:
      "Unregistered metrics stay visible with their source, definition version, and coverage instead of being silently discarded.",
    order: 40,
  },
};

const DIMENSION_GROUP: Record<string, MetricGroupId> = {
  data_quality: "data-readiness",
  efficiency: "operational-effort",
  usage: "operational-effort",
  workflow: "operational-effort",
  outcome: "verification-evidence",
  reliability: "operational-effort",
  verification: "verification-evidence",
};

const DIMENSION_QUESTION: Record<string, string> = {
  data_quality: "How complete is the evidence needed to interpret this metric?",
  efficiency: "What elapsed effort is visible in the current snapshot?",
  usage: "What provider-reported token usage is visible in the current snapshot?",
  workflow: "What workflow activity is visible in the current snapshot?",
  outcome: "What terminal state did the provider report?",
  reliability: "What tool lifecycle results are visible in the current snapshot?",
  verification: "What verification evidence is visible in the current snapshot?",
};

const REGISTERED_QUESTIONS: Record<string, string> = {
  "workflow.finalized_turn_count":
    "How many finalized agent turns were observed in the current snapshot?",
  "data_quality.turn_usage_coverage":
    "For how many finalized turns was token usage available?",
  "data_quality.turn_duration_coverage":
    "For how many finalized turns was duration available?",
  "data_quality.tool_result_coverage":
    "For how many completed tools was a result available?",
  "data_quality.tool_duration_coverage":
    "For how many completed tools was duration available?",
  "data_quality.unknown_event_kind_rate":
    "What share of observed events could not be classified?",
  "data_quality.direct_event_timestamp_rate":
    "What share of events has an event-specific provider timestamp?",
  "workflow.session_count":
    "How many reviewed sessions make up this task revision?",
  "workflow.observed_event_count":
    "How many events are visible across the reviewed task sessions?",
  "workflow.event_count": "How many events are visible in this session?",
  "workflow.plan_event_count": "How many plan events are visible in this session?",
  "workflow.compaction_count": "How many compaction events are visible in this session?",
  "workflow.tool_event_count": "How many completed tool events are visible in this session?",
  "verification.observed_count":
    "How many verification events are visible across the reviewed task sessions?",
  "verification.verification_count":
    "How many verification events are visible in this session?",
};

const REGISTERED_DISPLAY_NAMES: Record<string, string> = {
  "workflow.finalized_turn_count": "Observed agent iterations",
  "data_quality.turn_usage_coverage": "Usable turn usage coverage",
  "data_quality.turn_duration_coverage": "Turn duration coverage",
  "data_quality.tool_result_coverage": "Tool result coverage",
  "data_quality.tool_duration_coverage": "Tool duration coverage",
  "data_quality.unknown_event_kind_rate": "Unknown event kind rate",
  "data_quality.direct_event_timestamp_rate": "Direct event timestamp rate",
};

export function normalizeMetricKey(key: string): string {
  return key.startsWith("task.") ? key.slice("task.".length) : key;
}

const EVIDENCE_COVERAGE_RATES = new Set([
  "data_quality.turn_usage_coverage",
  "data_quality.turn_duration_coverage",
  "data_quality.tool_result_coverage",
  "data_quality.tool_duration_coverage",
]);

const OBSERVED_EVENT_RATES = new Set([
  "data_quality.unknown_event_kind_rate",
  "data_quality.direct_event_timestamp_rate",
  "reliability.tool_success_rate",
  "verification.pass_rate",
]);

export function formatRateBasis(input: {
  key: string;
  numericValue: number;
  observed: number;
  eligible: number;
}): string | null {
  const normalizedKey = normalizeMetricKey(input.key);
  const evidenceCoverage = EVIDENCE_COVERAGE_RATES.has(normalizedKey);
  const observedEventRate = OBSERVED_EVENT_RATES.has(normalizedKey);
  if (!evidenceCoverage && !observedEventRate) return null;
  const numerator = evidenceCoverage ? input.observed : input.numericValue * input.observed;
  const denominator = evidenceCoverage ? input.eligible : input.observed;
  const formattedNumerator = new Intl.NumberFormat("en", {
    maximumFractionDigits: 2,
  }).format(numerator);
  const formattedDenominator = new Intl.NumberFormat("en").format(denominator);
  return `${formattedNumerator}/${formattedDenominator}`;
}

export function inferMetricDimension(key: string, explicitDimension?: string): string {
  const explicit = explicitDimension?.trim();
  if (explicit) return explicit;
  return normalizeMetricKey(key).split(".")[0] || "unknown";
}

export function getMetricPresentation(input: {
  key: string;
  dimension?: string;
  displayName?: string;
}): MetricPresentation {
  const normalizedKey = normalizeMetricKey(input.key);
  const dimension = inferMetricDimension(input.key, input.dimension);
  const group = GROUPS[DIMENSION_GROUP[dimension] ?? "other-observations"];
  const displayName =
    input.displayName?.trim() ||
    REGISTERED_DISPLAY_NAMES[normalizedKey] ||
    titleFromKey(input.key);
  return {
    dimension,
    displayName,
    question:
      REGISTERED_QUESTIONS[normalizedKey] ??
      DIMENSION_QUESTION[dimension] ??
      `What does ${displayName} show in the current snapshot?`,
    group,
  };
}

export interface GroupedMetricItems<T> {
  presentation: MetricGroupPresentation;
  items: T[];
}

export function groupMetricItems<T>(
  items: readonly T[],
  describe: (item: T) => { key: string; dimension?: string; displayName?: string },
): GroupedMetricItems<T>[] {
  const grouped = new Map<MetricGroupId, GroupedMetricItems<T>>();
  for (const item of items) {
    const presentation = getMetricPresentation(describe(item));
    const existing = grouped.get(presentation.group.id);
    if (existing) existing.items.push(item);
    else {
      grouped.set(presentation.group.id, {
        presentation: presentation.group,
        items: [item],
      });
    }
  }
  return [...grouped.values()].sort(
    (left, right) => left.presentation.order - right.presentation.order,
  );
}
