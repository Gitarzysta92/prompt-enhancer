import type {
  ModelLinkAnnotation,
  ModelLinkExperiment,
  ModelLinkExperimentOutcome,
} from "../../shared/api/contracts";

const SAFE_ID = /^[a-f0-9]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const REVISION = /^[a-f0-9]{40}$/;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length &&
    Object.keys(value).every((key) => keys.includes(key))
  );
}

function safeDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    !Number.isNaN(new Date(value).valueOf()) &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  );
}

function safeModel(value: unknown): boolean {
  if (
    !record(value) ||
    !exactKeys(value, [
      "key",
      "repository_id",
      "revision",
      "license_spdx",
      "tokenizer_id",
      "backend_key",
    ])
  ) {
    return false;
  }
  return (
    [
      value.key,
      value.repository_id,
      value.license_spdx,
      value.tokenizer_id,
      value.backend_key,
    ].every((item) => typeof item === "string" && SAFE_CODE.test(item)) &&
    typeof value.revision === "string" &&
    REVISION.test(value.revision)
  );
}

function safeLink(value: unknown): boolean {
  if (
    !record(value) ||
    !exactKeys(value, [
      "link_id",
      "candidate_kind",
      "qwen_score",
      "qwen_rank",
      "bge_score",
      "bge_rank",
      "recommended_by",
    ])
  ) {
    return false;
  }
  return (
    typeof value.link_id === "string" &&
    SAFE_ID.test(value.link_id) &&
    (value.candidate_kind === "response" || value.candidate_kind === "plan") &&
    typeof value.qwen_score === "number" &&
    Number.isFinite(value.qwen_score) &&
    value.qwen_score >= -1.000001 &&
    value.qwen_score <= 1.000001 &&
    Number.isInteger(value.qwen_rank) &&
    (value.qwen_rank as number) >= 1 &&
    (value.qwen_rank as number) <= 8 &&
    typeof value.bge_score === "number" &&
    Number.isFinite(value.bge_score) &&
    value.bge_score >= -100_000 &&
    value.bge_score <= 100_000 &&
    Number.isInteger(value.bge_rank) &&
    (value.bge_rank as number) >= 1 &&
    (value.bge_rank as number) <= 8 &&
    ["qwen", "bge", "both"].includes(value.recommended_by as string)
  );
}

export function parseModelLinkAnnotation(value: unknown): ModelLinkAnnotation {
  if (
    !record(value) ||
    !exactKeys(value, ["link_id", "revision", "label", "annotated_at"]) ||
    typeof value.link_id !== "string" ||
    !SAFE_ID.test(value.link_id) ||
    !Number.isInteger(value.revision) ||
    (value.revision as number) < 1 ||
    !["relevant", "incorrect", "unsure"].includes(value.label as string) ||
    !safeDate(value.annotated_at)
  ) {
    throw new Error("invalid-model-link-contract");
  }
  return value as unknown as ModelLinkAnnotation;
}

export function parseModelLinkExperiment(value: unknown): ModelLinkExperiment {
  if (
    !record(value) ||
    !exactKeys(value, ["run", "links", "annotations"]) ||
    !record(value.run) ||
    !exactKeys(value.run, [
      "run_id",
      "experiment_key",
      "experiment_version",
      "resolved_device",
      "qwen_model",
      "bge_model",
      "query_count",
      "link_count",
      "agreement_count",
      "started_at",
      "finished_at",
      "local_only",
    ]) ||
    typeof value.run.run_id !== "string" ||
    !SAFE_ID.test(value.run.run_id) ||
    value.run.experiment_key !== "local.neural-link-comparison" ||
    value.run.experiment_version !== 1 ||
    !["cpu", "cuda", "mps"].includes(value.run.resolved_device as string) ||
    !safeModel(value.run.qwen_model) ||
    !safeModel(value.run.bge_model) ||
    !Number.isInteger(value.run.query_count) ||
    (value.run.query_count as number) < 1 ||
    (value.run.query_count as number) > 8 ||
    !Number.isInteger(value.run.link_count) ||
    (value.run.link_count as number) < 1 ||
    (value.run.link_count as number) > 16 ||
    !Number.isInteger(value.run.agreement_count) ||
    (value.run.agreement_count as number) < 0 ||
    (value.run.agreement_count as number) > (value.run.query_count as number) ||
    !safeDate(value.run.started_at) ||
    !safeDate(value.run.finished_at) ||
    value.run.local_only !== true ||
    !Array.isArray(value.links) ||
    value.links.length !== value.run.link_count ||
    !value.links.every(safeLink) ||
    !Array.isArray(value.annotations) ||
    value.annotations.length > value.links.length
  ) {
    throw new Error("invalid-model-link-contract");
  }
  const linkIds = value.links.map((link) => (link as Record<string, unknown>).link_id);
  const annotations = value.annotations.map(parseModelLinkAnnotation);
  if (
    new Set(linkIds).size !== linkIds.length ||
    new Set(annotations.map((item) => item.link_id)).size !== annotations.length ||
    annotations.some((item) => !linkIds.includes(item.link_id))
  ) {
    throw new Error("invalid-model-link-contract");
  }
  return value as unknown as ModelLinkExperiment;
}

export function parseModelLinkOutcome(value: unknown): ModelLinkExperimentOutcome {
  if (
    !record(value) ||
    !exactKeys(value, ["experiment", "suggestions", "applied"]) ||
    typeof value.applied !== "boolean" ||
    !Array.isArray(value.suggestions)
  ) {
    throw new Error("invalid-model-link-contract");
  }
  const experiment = parseModelLinkExperiment(value.experiment);
  const linkIds = new Set(experiment.links.map((link) => link.link_id));
  const suggestions = value.suggestions;
  if (
    suggestions.length > experiment.links.length ||
    suggestions.some(
      (item) =>
        !record(item) ||
        !exactKeys(item, ["link_id", "query_excerpt", "candidate_excerpt"]) ||
        typeof item.link_id !== "string" ||
        !linkIds.has(item.link_id) ||
        typeof item.query_excerpt !== "string" ||
        item.query_excerpt.length < 1 ||
        item.query_excerpt.length > 361 ||
        typeof item.candidate_excerpt !== "string" ||
        item.candidate_excerpt.length < 1 ||
        item.candidate_excerpt.length > 361,
    ) ||
    new Set(
      suggestions.map((item) =>
        record(item) && typeof item.link_id === "string" ? item.link_id : "",
      ),
    ).size !== suggestions.length ||
    (!value.applied && suggestions.length !== 0)
  ) {
    throw new Error("invalid-model-link-contract");
  }
  return value as unknown as ModelLinkExperimentOutcome;
}
