import type { ModelEnsembleTrajectoryPage } from "./contracts";
import {
  ModelEnsemblePayloadError,
  parseModelEnsembleMetricReceipt,
  parseModelPredictiveMetricSummary,
  parseModelEnsembleTypedMetricReceipt,
} from "./modelEnsembleContract";
import { METRIC_V2_KEYS, MetricDefinitionsOutOfDateError, parseMetricV2State } from "./metricPublicationV2Contract";

export class ModelEnsembleTrajectoryPayloadError extends Error {
  constructor() {
    super("Local model ensemble trajectory response was invalid");
    this.name = "ModelEnsembleTrajectoryPayloadError";
  }
}

type Row = Record<string, unknown>;
const HEX_64 = /^[0-9a-f]{64}$/;

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  return value as number;
}

function digest(value: unknown): string {
  if (typeof value !== "string" || !HEX_64.test(value)) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  return value;
}

function timestamp(value: unknown): string {
  if (
    typeof value !== "string"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
  ) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  const parsed = new Date(value);
  if (
    match === null
    || Number.isNaN(parsed.getTime())
    || parsed.getUTCFullYear() !== Number(match[1])
    || parsed.getUTCMonth() + 1 !== Number(match[2])
    || parsed.getUTCDate() !== Number(match[3])
    || parsed.getUTCHours() !== Number(match[4])
    || parsed.getUTCMinutes() !== Number(match[5])
    || parsed.getUTCSeconds() !== Number(match[6])
  ) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  return value;
}

export function parseModelEnsembleTrajectoryPage(
  value: unknown,
  expectHead = true,
): ModelEnsembleTrajectoryPage {
  const page = row(value);
  exact(page, [
    "watch_id", "head_run_id", "head_generation", "points",
    "next_before_generation", "content_persisted", "calibrated_as_truth",
  ]);
  digest(page.watch_id);
  const headRunId = page.head_run_id === null ? null : digest(page.head_run_id);
  const headGeneration = page.head_generation === null
    ? null
    : integer(page.head_generation, 1, 1_000_000_000);
  if ((headRunId === null) !== (headGeneration === null)) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  if (page.content_persisted !== false || page.calibrated_as_truth !== false) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  if (!Array.isArray(page.points) || page.points.length > 60) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }

  let previousGeneration: number | null = null;
  const runIds = new Set<string>();
  const generations = new Set<number>();
  let headObserved = false;
  for (const candidate of page.points) {
    const point = row(candidate);
    exact(point, [
      "generation", "run_id", "published_at", "completed_at", "max_messages",
      "source_coverage_state", "chunk_count", "comparable_to_head", "metrics",
      "metric_projection_version", "metric_projection_completed_at", "typed_metrics",
      "metric_states_v2",
      "predictive_projection_version", "predictive_metrics",
    ]);
    const generation = integer(point.generation, 1, 1_000_000_000);
    const runId = digest(point.run_id);
    const publishedAt = timestamp(point.published_at);
    const completedAt = timestamp(point.completed_at);
    if (
      (previousGeneration !== null && generation >= previousGeneration)
      || generations.has(generation)
      || runIds.has(runId)
      || new Date(publishedAt).getTime() < new Date(completedAt).getTime()
      || !["complete_window", "incomplete_source"].includes(String(point.source_coverage_state))
      || typeof point.comparable_to_head !== "boolean"
    ) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    previousGeneration = generation;
    if (headGeneration !== null && generation > headGeneration) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    generations.add(generation);
    runIds.add(runId);
    const chunkCount = integer(point.chunk_count, 1, 8);
    integer(point.max_messages, 1, 100);
    if (!Array.isArray(point.metrics) || point.metrics.length < 1 || point.metrics.length > 20) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    const metricKeys = new Set<string>();
    try {
      for (const metricCandidate of point.metrics) {
        const metric = parseModelEnsembleMetricReceipt(metricCandidate, chunkCount);
        if (metricKeys.has(metric.metric_key)) throw new ModelEnsembleTrajectoryPayloadError();
        metricKeys.add(metric.metric_key);
      }
    } catch (error) {
      if (error instanceof ModelEnsemblePayloadError) {
        throw new ModelEnsembleTrajectoryPayloadError();
      }
      throw error;
    }
    const projectionVersion = point.metric_projection_version;
    const projectionCompletedAt = point.metric_projection_completed_at;
    if (!Array.isArray(point.typed_metrics) || point.typed_metrics.length > 20) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (
      (projectionVersion === null) !== (projectionCompletedAt === null)
      || (projectionVersion === null) !== (point.typed_metrics.length === 0)
      || (projectionVersion !== null && projectionVersion !== "coaching-typed-projection-v1")
    ) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (projectionCompletedAt !== null) timestamp(projectionCompletedAt);
    const typedKeys = new Set<string>();
    try {
      for (const metricCandidate of point.typed_metrics) {
        const metric = parseModelEnsembleTypedMetricReceipt(metricCandidate);
        if (!metricKeys.has(metric.metric_key) || typedKeys.has(metric.metric_key)) {
          throw new ModelEnsembleTrajectoryPayloadError();
        }
        typedKeys.add(metric.metric_key);
      }
    } catch (error) {
      if (error instanceof ModelEnsemblePayloadError) {
        throw new ModelEnsembleTrajectoryPayloadError();
      }
      throw error;
    }
    if (point.typed_metrics.length > 0 && typedKeys.size !== metricKeys.size) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (!Array.isArray(point.metric_states_v2) || ![0, 20].includes(point.metric_states_v2.length)) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (point.metric_states_v2.length > 0) {
      try {
        // All twenty compact rows of one point come from one readable projection,
        // exactly as the rows of a full publication must agree.
        let pointProjection: string | null = null;
        point.metric_states_v2.forEach((state, ordinal) => {
          const parsed = parseMetricV2State(state, METRIC_V2_KEYS[ordinal]);
          if (!metricKeys.has(parsed.metric_key)) {
            throw new ModelEnsembleTrajectoryPayloadError();
          }
          if (pointProjection === null) {
            pointProjection = parsed.projection_version;
          } else if (parsed.projection_version !== pointProjection) {
            throw new ModelEnsembleTrajectoryPayloadError();
          }
        });
      } catch (error) {
        if (error instanceof ModelEnsembleTrajectoryPayloadError) throw error;
        // Definitions out of date is a distinct client-update condition, not a
        // malformed page: let the surface show the update alert.
        if (error instanceof MetricDefinitionsOutOfDateError) throw error;
        throw new ModelEnsembleTrajectoryPayloadError();
      }
    }
    const predictiveVersion = point.predictive_projection_version;
    if (!Array.isArray(point.predictive_metrics) || point.predictive_metrics.length > 20) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (
      (predictiveVersion === null) !== (point.predictive_metrics.length === 0)
      || (predictiveVersion !== null && predictiveVersion !== "local-probabilistic-radar-v1")
    ) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    const predictiveKeys = new Set<string>();
    try {
      for (const metricCandidate of point.predictive_metrics) {
        const metric = parseModelPredictiveMetricSummary(metricCandidate);
        if (!metricKeys.has(metric.metric_key) || predictiveKeys.has(metric.metric_key)) {
          throw new ModelEnsembleTrajectoryPayloadError();
        }
        predictiveKeys.add(metric.metric_key);
      }
    } catch (error) {
      if (error instanceof ModelEnsemblePayloadError) {
        throw new ModelEnsembleTrajectoryPayloadError();
      }
      throw error;
    }
    if (point.predictive_metrics.length > 0 && predictiveKeys.size !== metricKeys.size) {
      throw new ModelEnsembleTrajectoryPayloadError();
    }
    if (runId === headRunId) {
      if (generation !== headGeneration || point.comparable_to_head !== true) {
        throw new ModelEnsembleTrajectoryPayloadError();
      }
      headObserved = true;
    }
  }

  const cursor = page.next_before_generation === null
    ? null
    : integer(page.next_before_generation, 1, 1_000_000_000);
  if (cursor !== null && (previousGeneration === null || cursor !== previousGeneration)) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  if (
    (headObserved && page.points[0]?.run_id !== headRunId)
    || (expectHead && headRunId !== null && !headObserved)
  ) {
    throw new ModelEnsembleTrajectoryPayloadError();
  }
  // The head can be outside a later cursor page, but a first page containing
  // it must always put that exact publication first.
  return value as ModelEnsembleTrajectoryPage;
}
