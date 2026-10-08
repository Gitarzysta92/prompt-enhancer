import type { ModelPredictiveMetricDetail } from "./contracts";
import {
  ModelEnsemblePayloadError,
  parseModelPredictiveMetricSummary,
} from "./modelEnsembleContract";

export class ModelPredictiveMetricDetailPayloadError extends Error {
  constructor() {
    super("Local predictive metric detail response was invalid");
    this.name = "ModelPredictiveMetricDetailPayloadError";
  }
}

type Row = Record<string, unknown>;
const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_LABEL = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
}

function probability(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  return value;
}

function timestamp(value: unknown): string {
  if (
    typeof value !== "string"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    || Number.isNaN(new Date(value).getTime())
  ) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  return value;
}

export function parseModelPredictiveMetricDetail(value: unknown): ModelPredictiveMetricDetail {
  const detail = row(value);
  exact(detail, [
    "run_id", "projection_version", "projected_at", "metric", "density_bins", "factors",
    "experimental_label", "local_only", "content_persisted", "universal_trust_percentage_available",
  ]);
  if (
    typeof detail.run_id !== "string" || !HEX_64.test(detail.run_id)
    || detail.projection_version !== "local-probabilistic-radar-v1"
    || detail.experimental_label !== "Experimental model range"
    || detail.local_only !== true
    || detail.content_persisted !== false
    || detail.universal_trust_percentage_available !== false
  ) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  timestamp(detail.projected_at);
  try {
    parseModelPredictiveMetricSummary(detail.metric);
  } catch (error) {
    if (error instanceof ModelEnsemblePayloadError) {
      throw new ModelPredictiveMetricDetailPayloadError();
    }
    throw error;
  }
  if (!Array.isArray(detail.density_bins) || detail.density_bins.length !== 20) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  const densityTotal = detail.density_bins.reduce((total, item) => total + probability(item), 0);
  if (Math.abs(densityTotal - 1) > 1e-8) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  if (!Array.isArray(detail.factors) || detail.factors.length < 1 || detail.factors.length > 16) {
    throw new ModelPredictiveMetricDetailPayloadError();
  }
  const factorKeys = new Set<string>();
  for (const candidate of detail.factors) {
    const factor = row(candidate);
    exact(factor, [
      "factor_key", "scale", "weight", "applicability_probability", "present_probability",
      "neutral_probability", "absent_probability", "expert_count", "critical",
    ]);
    if (
      typeof factor.factor_key !== "string" || !SAFE_LABEL.test(factor.factor_key)
      || factorKeys.has(factor.factor_key)
      || !["binary", "ordinal", "proportion"].includes(String(factor.scale))
      || typeof factor.weight !== "number" || !Number.isFinite(factor.weight) || factor.weight <= 0
      || !Number.isInteger(factor.expert_count) || (factor.expert_count as number) < 1 || (factor.expert_count as number) > 8
      || typeof factor.critical !== "boolean"
    ) {
      throw new ModelPredictiveMetricDetailPayloadError();
    }
    factorKeys.add(factor.factor_key);
    const states = [
      probability(factor.present_probability),
      probability(factor.neutral_probability),
      probability(factor.absent_probability),
    ];
    probability(factor.applicability_probability);
    if (Math.abs(states.reduce((total, item) => total + item, 0) - 1) > 1e-8) {
      throw new ModelPredictiveMetricDetailPayloadError();
    }
  }
  return value as ModelPredictiveMetricDetail;
}
