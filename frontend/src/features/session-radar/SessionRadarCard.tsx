import { useEffect, useState } from "react";
import type { PromptEnhancerTransport } from "../../shared/api/contracts";
import { PromptMetricRadar } from "../prompt-check/promptCheckPlots";
import "./SessionRadarCard.css";

const SHORT: Record<string, string> = {
  "prompt.task_definition_coverage": "Task definition",
  "prompt.problem_evidence_quality": "Problem evidence",
  "prompt.context_sufficiency": "Context",
  "prompt.constraint_precision": "Constraints",
  "prompt.acceptance_testability": "Acceptance",
  "prompt.deliverable_contract": "Deliverable",
  "collaboration.ambiguity_resolution": "Ambiguity resolved",
  "logic.requirement_action_traceability": "Req → action",
  "logic.open_loop_closure": "Loops closed",
  "outcome.first_pass_verification": "First-pass checks",
  "outcome.verification_strategy_adequacy": "Verification",
  "outcome.agent_claim_grounding": "Claims grounded",
};
const AXES = Object.keys(SHORT);
const LOWER_IS_BETTER = new Set<string>([]);

type MetricRow = { key?: unknown; metric_key?: unknown; numeric_value?: unknown; value_state?: unknown };

function collectValues(rows: MetricRow[]): Map<string, number> {
  const byKey = new Map<string, number>();
  for (const row of rows) {
    const key = typeof row.metric_key === "string" ? row.metric_key : typeof row.key === "string" ? row.key : "";
    if (!AXES.includes(key) || byKey.has(key)) continue;
    if (typeof row.value_state === "string" && row.value_state !== "known" && row.value_state !== "measured") continue;
    if (typeof row.numeric_value === "number") byKey.set(key, row.numeric_value);
  }
  return byKey;
}

/**
 * One radar of this session's measured coaching values - the numbers come from
 * the latest local analysis run (the same lane the metric deck reads), with the
 * deterministic session metrics as a fallback. Metrics without a measured value
 * sit at the centre marked n/a; nothing here is a model judgment.
 */
export function SessionRadarCard({
  sessionId,
  transport,
}: {
  sessionId: string;
  transport: Pick<PromptEnhancerTransport, "getSessionMetrics"> &
    Partial<Pick<PromptEnhancerTransport, "getLatestModelEnsemble">>;
}) {
  const [values, setValues] = useState<Map<string, number> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setValues(null);
    setFailed(false);
    (async () => {
      const collected = new Map<string, number>();
      // Primary source: the latest analysis run's typed metrics.
      if (transport.getLatestModelEnsemble) {
        try {
          const run = await transport.getLatestModelEnsemble(sessionId, controller.signal);
          const typed = (run as { typed_metrics?: MetricRow[] }).typed_metrics;
          if (Array.isArray(typed)) for (const [k, v] of collectValues(typed)) collected.set(k, v);
        } catch {
          // No run yet (404) or lane unavailable - the fallback below still applies.
        }
      }
      // Fallback: deterministic per-session metrics (covers any axis they measure).
      if (collected.size === 0) {
        try {
          const value = await transport.getSessionMetrics(sessionId, controller.signal);
          const rows = (value as { metrics?: MetricRow[] }).metrics;
          if (Array.isArray(rows)) for (const [k, v] of collectValues(rows)) collected.set(k, v);
        } catch {
          if (!controller.signal.aborted) setFailed(true);
          return;
        }
      }
      if (!controller.signal.aborted) setValues(collected);
    })();
    return () => controller.abort();
  }, [sessionId, transport]);

  if (failed || values === null) return null;
  const readings = AXES.map((key) => ({
    key,
    label: SHORT[key],
    value: values.has(key) ? Math.max(0, Math.min(1, values.get(key) as number)) : null,
    higherIsBetter: !LOWER_IS_BETTER.has(key),
  }));
  const known = readings.filter((r) => r.value !== null).length;

  return (
    <section aria-labelledby="session-radar-title" className="session-radar">
      <header>
        <div>
          <p className="eyebrow">Measured values · same numbers as the metric deck</p>
          <h3 id="session-radar-title">Session radar</h3>
        </div>
        <span className="session-radar__count">{known} of {readings.length} measurable</span>
      </header>
      {known === 0 ? (
        <p className="session-radar__empty">
          No measured coaching values for this session yet, so there is no shape to draw.
          Run the bounded local analysis from the prompt-quality view; measured axes appear here as soon as values exist.
        </p>
      ) : (
        <PromptMetricRadar readings={readings} />
      )}
    </section>
  );
}
