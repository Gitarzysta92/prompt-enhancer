import { describe, expect, it } from "vitest";
import type { MetricReadiness } from "../../shared/api/contracts";
import {
  SYNTHETIC_CURRENT_SESSION_QUALITY_RUN,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_SESSION_METRIC_READINESS,
} from "../../shared/api/syntheticFixtures";
import { explainMetricReadiness, indexMetricReadiness } from "./metricReadiness";
import { createQualityMetricProfile } from "./qualityProfile";

describe("metric readiness fail-closed presentation", () => {
  it("withholds duplicate identities instead of accepting the last row", () => {
    const row = structuredClone(SYNTHETIC_SESSION_METRIC_READINESS.metrics[0]);
    const duplicate = { ...row, reason_code: "analysis_failed" as const };
    const index = indexMetricReadiness([row, duplicate]);

    expect(index.has(`${row.metric_key}@${row.metric_version}`)).toBe(false);
  });

  it("uses a safe refresh action when malformed readiness has no next action", () => {
    const profile = createQualityMetricProfile(
      "prompt-quality",
      structuredClone(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN),
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const observation = profile.latest.metrics[0];
    const readiness = {
      ...structuredClone(SYNTHETIC_SESSION_METRIC_READINESS.metrics[0]),
      metric_key: observation.definition.key,
      metric_version: observation.definition.version,
      next_actions: [],
    } as MetricReadiness;

    expect(explainMetricReadiness(observation, readiness)).toMatchObject({
      compactActionCopy: "Refresh readiness metadata.",
      state: "metadata_mismatch",
    });
  });

  it.each([
    {
      patch: { reason_code: "analysis_failed" },
      name: "contradictory state and reason",
    },
    {
      patch: { next_actions: ["fictional_private_action"] },
      name: "unknown action",
    },
    {
      patch: { missing_capabilities: ["fictional_private_capability"] },
      name: "unknown evidence capability",
    },
  ])("withholds $name metadata behind a fixed mismatch explanation", ({ patch }) => {
    const profile = createQualityMetricProfile(
      "prompt-quality",
      structuredClone(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN),
      SYNTHETIC_QUALITY_SESSION_ID,
    )!;
    const observation = profile.latest.metrics[0];
    const readiness = {
      ...structuredClone(SYNTHETIC_SESSION_METRIC_READINESS.metrics[0]),
      metric_key: observation.definition.key,
      metric_version: observation.definition.version,
      ...patch,
    } as MetricReadiness;

    expect(explainMetricReadiness(observation, readiness)).toMatchObject({
      compactActionCopy: "Refresh readiness metadata.",
      state: "metadata_mismatch",
    });
  });
});
