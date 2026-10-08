import type { SessionMetric } from "../../shared/api/contracts";
import {
  METRIC_ROUTE_CATEGORIES,
  type MetricCategory,
} from "../../shared/platform/platform";

export interface MetricCategoryDefinition {
  id: MetricCategory;
  label: string;
  shortLabel: string;
  question: string;
  description: string;
  availability: "stored" | "local-analysis" | "planned";
}

export const METRIC_TAXONOMY: readonly MetricCategoryDefinition[] = [
  {
    id: "readiness",
    label: "Data readiness",
    shortLabel: "Readiness",
    question: "Is there enough observable evidence to interpret this session?",
    description:
      "Coverage and evidence availability establish interpretation limits; they are not quality scores.",
    availability: "stored",
  },
  {
    id: "execution",
    label: "Execution flow",
    shortLabel: "Execution",
    question: "What work and iteration flow was observed?",
    description:
      "Descriptive workload, timing, and workflow observations without judging whether more or less is better.",
    availability: "stored",
  },
  {
    id: "tools",
    label: "Tools and reliability",
    shortLabel: "Tools",
    question: "How did observed tool lifecycles behave?",
    description:
      "Tool calls, results, durations, and reliability evidence kept separate from task success.",
    availability: "stored",
  },
  {
    id: "model-usage",
    label: "Model usage",
    shortLabel: "Model usage",
    question: "What provider-reported model usage is available?",
    description:
      "Token and model observations preserve missing values and provider coverage rather than estimating them.",
    availability: "stored",
  },
  {
    id: "outcome",
    label: "Outcome evidence",
    shortLabel: "Outcome",
    question: "What objective completion or verification evidence was observed?",
    description:
      "Observed checks and terminal states are shown as evidence, never as proof inferred from an assistant claim.",
    availability: "stored",
  },
  {
    id: "prompt-quality",
    label: "Problem and prompt quality",
    shortLabel: "Prompt quality",
    question: "How clearly were the goal, context, constraints, and acceptance criteria expressed?",
    description:
      "An explicit bounded local analysis of redacted text with metric-specific denominators and abstention states.",
    availability: "local-analysis",
  },
  {
    id: "reasoning",
    label: "Logic & decisions",
    shortLabel: "Logic",
    question: "How well do observable plans, actions, decisions, and evidence connect?",
    description:
      "An explicit evidence-grounded local analysis of observable work products; hidden reasoning and private chain-of-thought are neither required nor claimed.",
    availability: "local-analysis",
  },
  {
    id: "other",
    label: "Other observations",
    shortLabel: "Other",
    question: "Which versioned observations do not yet have a registered category?",
    description:
      "Unknown metric definitions remain visible with provenance instead of being dropped or guessed.",
    availability: "stored",
  },
] as const;

const CATEGORY_BY_ID = new Map(
  METRIC_TAXONOMY.map((definition) => [definition.id, definition]),
);

const DIMENSION_CATEGORY: Readonly<Record<string, MetricCategory>> = {
  data_quality: "readiness",
  readiness: "readiness",
  coverage: "readiness",
  workflow: "execution",
  execution: "execution",
  efficiency: "execution",
  reliability: "tools",
  tool: "tools",
  tools: "tools",
  tooling: "tools",
  usage: "model-usage",
  model_usage: "model-usage",
  token_usage: "model-usage",
  outcome: "outcome",
  verification: "outcome",
  prompt_quality: "prompt-quality",
  prompt: "prompt-quality",
  reasoning: "reasoning",
  logic: "reasoning",
};

function normalizeSegment(value: string): string {
  return value.trim().toLowerCase().replace(/-/g, "_");
}

export function metricCategoryFor(
  metric: Pick<SessionMetric, "dimension" | "key">,
): MetricCategory {
  const normalizedDimension = normalizeSegment(metric.dimension);
  // Data-readiness definitions stay readiness metrics even when their subject
  // is tool evidence (for example tool-result coverage).
  if (normalizedDimension === "data_quality") return "readiness";

  const keySegments = metric.key
    .toLowerCase()
    .split(/[.]/)
    .map(normalizeSegment)
    .filter(Boolean);
  const describesToolLifecycle = keySegments.some(
    (segment) =>
      segment === "tool" ||
      segment.startsWith("tool_") ||
      segment.includes("_tool_") ||
      segment.endsWith("_tool"),
  );
  if (
    describesToolLifecycle &&
    (normalizedDimension === "workflow" ||
      normalizedDimension === "efficiency" ||
      normalizedDimension === "reliability" ||
      normalizedDimension === "tool" ||
      normalizedDimension === "tools")
  ) {
    return "tools";
  }

  const dimensionCategory = DIMENSION_CATEGORY[normalizedDimension];
  if (dimensionCategory) return dimensionCategory;
  for (const segment of keySegments) {
    const category = DIMENSION_CATEGORY[segment];
    if (category) return category;
  }
  return "other";
}

export function metricCategoryDefinition(
  category: MetricCategory,
): MetricCategoryDefinition {
  const definition = CATEGORY_BY_ID.get(category);
  if (!definition) {
    throw new TypeError("Metric category is not registered.");
  }
  return definition;
}

// Keep navigation and presentation registries locked together at runtime as
// well as through the shared MetricCategory type.
if (
  METRIC_ROUTE_CATEGORIES.some((category) => !CATEGORY_BY_ID.has(category)) ||
  METRIC_TAXONOMY.some(
    (definition) => !METRIC_ROUTE_CATEGORIES.includes(definition.id),
  )
) {
  throw new TypeError("Metric route and presentation taxonomies disagree.");
}
