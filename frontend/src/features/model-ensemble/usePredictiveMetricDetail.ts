import { useEffect, useState } from "react";
import type {
  ModelPredictiveMetricDetail,
  PromptEnhancerTransport,
} from "../../shared/api/contracts";
import type { ModelEnsembleRadarAxis } from "./metricAxisModel";

export type PredictiveMetricDetailState = "idle" | "loading" | "failed";

export interface PredictiveMetricDetailResult {
  detail: ModelPredictiveMetricDetail | null;
  state: PredictiveMetricDetailState;
}

interface PredictiveMetricDetailSlot extends PredictiveMetricDetailResult {
  metricKey: string | null;
  runId: string | null;
}

/**
 * Loads the content-free factor distribution for the selected axis, and only
 * when an informative experimental estimate is actually visible for it: a
 * withheld or absent estimate never triggers a request. Responses are admitted
 * only when both the requested run id and metric key match; a superseded
 * request is aborted and no completion owned by that aborted request is allowed
 * to change the current state.
 */
export function usePredictiveMetricDetail({
  transport,
  runId,
  axis,
}: {
  transport?: Pick<PromptEnhancerTransport, "getModelPredictiveMetricDetail">;
  runId?: string;
  axis: ModelEnsembleRadarAxis | undefined;
}): PredictiveMetricDetailResult {
  const [slot, setSlot] = useState<PredictiveMetricDetailSlot>({
    detail: null,
    metricKey: null,
    runId: null,
    state: "idle",
  });
  const metricKey = axis?.key;
  const prediction = axis?.prediction;
  const predictiveMedian = axis?.predictiveMedian;
  const load = transport?.getModelPredictiveMetricDetail;
  const loadable = load !== undefined
    && runId !== undefined
    && metricKey !== undefined
    && prediction !== null
    && prediction !== undefined
    && predictiveMedian !== null
    && predictiveMedian !== undefined;
  useEffect(() => {
    if (
      !loadable
      || load === undefined
      || runId === undefined
      || metricKey === undefined
    ) {
      setSlot({
        detail: null,
        metricKey: metricKey ?? null,
        runId: runId ?? null,
        state: "idle",
      });
      return undefined;
    }
    const controller = new AbortController();
    setSlot({ detail: null, metricKey, runId, state: "loading" });
    void load(runId, metricKey, controller.signal)
      .then((loaded) => {
        if (controller.signal.aborted) return;
        if (loaded.run_id !== runId || loaded.metric.metric_key !== metricKey) {
          throw new Error("predictive detail request identity mismatch");
        }
        setSlot({ detail: loaded, metricKey, runId, state: "idle" });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSlot({ detail: null, metricKey, runId, state: "failed" });
      });
    return () => controller.abort();
  }, [load, loadable, metricKey, prediction, predictiveMedian, runId]);
  if (!loadable) return { detail: null, state: "idle" };
  if (slot.runId !== runId || slot.metricKey !== metricKey) {
    return { detail: null, state: "loading" };
  }
  return { detail: slot.detail, state: slot.state };
}
