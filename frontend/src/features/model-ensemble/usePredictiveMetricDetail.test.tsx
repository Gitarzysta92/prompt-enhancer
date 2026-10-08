import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelEnsembleRun, ModelPredictiveMetricDetail } from "../../shared/api/contracts";
import { modelEnsembleRadarAxes, type ModelEnsembleRadarAxis } from "./metricAxisModel";
import { usePredictiveMetricDetail, type PredictiveMetricDetailResult } from "./usePredictiveMetricDetail";

const METRIC = "prompt.task_definition_coverage";
const RUN_ID = "b".repeat(64);
const NEXT_RUN_ID = "c".repeat(64);

function prediction(metricKey = METRIC) {
  return {
    metric_key: metricKey,
    target: "metric_value" as const,
    state: "experimental" as const,
    mean: 0.5,
    median: 0.5,
    q05: 0.2,
    q25: 0.4,
    q75: 0.6,
    q95: 0.8,
    applicability_probability: 0.9,
    pending_probability: 0.05,
    model_disagreement: 0.2,
    effective_observation_count: 2,
    model_set_version: "example-model-set-v1",
    calibration_version: "not-calibrated-v1",
    contract_version: "example-contract-v1",
    contract_fingerprint: "a".repeat(64),
    product_metric_eligible: false as const,
  };
}

function axesFor(experts: number): ModelEnsembleRadarAxis[] {
  const run = {
    typed_metrics: [],
    metrics: [],
    chunk_metrics: [],
    predictive_metrics: [prediction(), prediction("prompt.context_sufficiency")],
    predictive_model_stages: Array.from({ length: experts }, (_, index) => ({
      model_key: `example_small_${index}`,
      repository_id: `example-org/small-${index}`,
      status: "completed",
    })),
  } as unknown as ModelEnsembleRun;
  return modelEnsembleRadarAxes(run, "task-framing");
}

function detail(metricKey: string, runId = RUN_ID): ModelPredictiveMetricDetail {
  return {
    run_id: runId,
    projection_version: "local-probabilistic-radar-v1",
    projected_at: "2040-01-02T10:00:02Z",
    metric: prediction(metricKey),
    density_bins: Array.from({ length: 20 }, () => 0.05),
    factors: [],
    experimental_label: "Experimental model range",
    local_only: true,
    content_persisted: false,
    universal_trust_percentage_available: false,
  };
}

type Loader = (runId: string, metricKey: string, signal?: AbortSignal) => Promise<ModelPredictiveMetricDetail>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

/**
 * Hook props mirror the hook's own optionality (`axis` may be undefined, `runId`
 * may be absent). Naming the type and typing `initialProps` with it keeps
 * `renderHook`'s `Props` inference on this shape rather than on the narrower
 * literal passed first, so `rerender` may legitimately drop the axis or run id.
 */
type DetailProps = { axis: ModelEnsembleRadarAxis | undefined; runId: string | undefined };
type AxisProps = { axis: ModelEnsembleRadarAxis };

describe("usePredictiveMetricDetail", () => {
  it("never requests factor density for a withheld estimate or without a run id", () => {
    const forbidden: Loader = () => { throw new Error("factor density must not be requested"); };
    const getModelPredictiveMetricDetail = vi.fn(forbidden);
    const transport = { getModelPredictiveMetricDetail };
    const withheld = axesFor(1)[0];
    expect(withheld.prediction).not.toBeNull();
    expect(withheld.predictiveMedian).toBeNull();
    const initialProps: DetailProps = { axis: withheld, runId: RUN_ID };
    const { result, rerender } = renderHook<PredictiveMetricDetailResult, DetailProps>(
      ({ axis, runId }) => usePredictiveMetricDetail({ transport, runId, axis }),
      { initialProps },
    );
    expect(result.current).toEqual({ detail: null, state: "idle" });
    rerender({ axis: axesFor(2)[0], runId: undefined });
    rerender({ axis: undefined, runId: RUN_ID });
    expect(getModelPredictiveMetricDetail).not.toHaveBeenCalled();
    expect(result.current).toEqual({ detail: null, state: "idle" });
  });

  it("loads the distribution for a visible estimate with an abort signal and admits only the requested metric", async () => {
    const loader: Loader = async (_runId, metricKey) => detail(metricKey);
    const getModelPredictiveMetricDetail = vi.fn(loader);
    const transport = { getModelPredictiveMetricDetail };
    const [first, , third] = axesFor(3);
    expect(first.predictiveMedian).not.toBeNull();
    const initialProps: AxisProps = { axis: first };
    const { result, rerender } = renderHook<PredictiveMetricDetailResult, AxisProps>(
      ({ axis }) => usePredictiveMetricDetail({ transport, runId: RUN_ID, axis }),
      { initialProps },
    );
    expect(result.current.state).toBe("loading");
    await waitFor(() => expect(result.current.detail?.metric.metric_key).toBe(METRIC));
    expect(result.current.state).toBe("idle");
    expect(getModelPredictiveMetricDetail).toHaveBeenCalledWith(RUN_ID, METRIC, expect.any(AbortSignal));

    rerender({ axis: third });
    expect(result.current).toEqual({ detail: null, state: "loading" });
    await waitFor(() => expect(result.current.detail?.metric.metric_key).toBe("prompt.context_sufficiency"));
    expect(getModelPredictiveMetricDetail).toHaveBeenCalledTimes(2);
  });

  it("reports a mismatched detail as failed rather than showing another metric's distribution", async () => {
    const mismatchLoader: Loader = async () => detail("prompt.context_sufficiency");
    const mismatch = vi.fn(mismatchLoader);
    const transport = { getModelPredictiveMetricDetail: mismatch };
    const first = axesFor(3)[0];
    const { result } = renderHook(() => usePredictiveMetricDetail({ transport, runId: RUN_ID, axis: first }));
    await waitFor(() => expect(result.current.state).toBe("failed"));
    expect(result.current.detail).toBeNull();
  });

  it("never exposes cached detail from run A during the first same-key render of run B", async () => {
    const loader: Loader = async (runId, metricKey) => detail(metricKey, runId);
    const transport = { getModelPredictiveMetricDetail: vi.fn(loader) };
    const axis = axesFor(3)[0];
    const renders: Array<{ contextRunId: string; detailRunId: string | null }> = [];
    const hook = renderHook<PredictiveMetricDetailResult, { runId: string }>(
      ({ runId }) => {
        const value = usePredictiveMetricDetail({ transport, runId, axis });
        renders.push({ contextRunId: runId, detailRunId: value.detail?.run_id ?? null });
        return value;
      },
      { initialProps: { runId: RUN_ID } },
    );
    await waitFor(() => expect(hook.result.current.detail?.run_id).toBe(RUN_ID));

    const transitionRenderStart = renders.length;
    hook.rerender({ runId: NEXT_RUN_ID });
    const firstRunBRender = renders.slice(transitionRenderStart)
      .find((item) => item.contextRunId === NEXT_RUN_ID);
    expect(firstRunBRender).toEqual({ contextRunId: NEXT_RUN_ID, detailRunId: null });
    await waitFor(() => expect(hook.result.current.detail?.run_id).toBe(NEXT_RUN_ID));
  });

  it("ignores a same-key run A response that resolves after run B", async () => {
    const requests = new Map<string, ReturnType<typeof deferred<ModelPredictiveMetricDetail>>>();
    const loader: Loader = (runId) => {
      const request = deferred<ModelPredictiveMetricDetail>();
      requests.set(runId, request);
      return request.promise;
    };
    const transport = { getModelPredictiveMetricDetail: vi.fn(loader) };
    const axis = axesFor(3)[0];
    const hook = renderHook<PredictiveMetricDetailResult, { runId: string }>(
      ({ runId }) => usePredictiveMetricDetail({ transport, runId, axis }),
      { initialProps: { runId: RUN_ID } },
    );
    hook.rerender({ runId: NEXT_RUN_ID });
    expect(transport.getModelPredictiveMetricDetail.mock.calls[0][2]?.aborted).toBe(true);

    await act(async () => {
      requests.get(NEXT_RUN_ID)!.resolve(detail(METRIC, NEXT_RUN_ID));
    });
    await waitFor(() => expect(hook.result.current.detail?.run_id).toBe(NEXT_RUN_ID));
    await act(async () => {
      requests.get(RUN_ID)!.resolve(detail(METRIC, RUN_ID));
      await Promise.resolve();
    });
    expect(hook.result.current).toMatchObject({
      detail: { run_id: NEXT_RUN_ID },
      state: "idle",
    });
  });

  it("ignores a late non-Abort rejection owned by run A", async () => {
    const requests = new Map<string, ReturnType<typeof deferred<ModelPredictiveMetricDetail>>>();
    const loader: Loader = (runId) => {
      const request = deferred<ModelPredictiveMetricDetail>();
      requests.set(runId, request);
      return request.promise;
    };
    const transport = { getModelPredictiveMetricDetail: vi.fn(loader) };
    const axis = axesFor(3)[0];
    const hook = renderHook<PredictiveMetricDetailResult, { runId: string }>(
      ({ runId }) => usePredictiveMetricDetail({ transport, runId, axis }),
      { initialProps: { runId: RUN_ID } },
    );
    hook.rerender({ runId: NEXT_RUN_ID });
    await act(async () => {
      requests.get(NEXT_RUN_ID)!.resolve(detail(METRIC, NEXT_RUN_ID));
    });
    await waitFor(() => expect(hook.result.current.detail?.run_id).toBe(NEXT_RUN_ID));

    await act(async () => {
      requests.get(RUN_ID)!.reject(new Error("late synthetic transport failure"));
      await Promise.resolve();
    });
    expect(hook.result.current).toMatchObject({
      detail: { run_id: NEXT_RUN_ID },
      state: "idle",
    });
  });

  it("fails closed when the response has the requested metric but the wrong run id", async () => {
    const wrongRunLoader: Loader = async (_runId, metricKey) => detail(metricKey, NEXT_RUN_ID);
    const transport = { getModelPredictiveMetricDetail: vi.fn(wrongRunLoader) };
    const axis = axesFor(3)[0];
    const { result } = renderHook(() => usePredictiveMetricDetail({ transport, runId: RUN_ID, axis }));

    await waitFor(() => expect(result.current.state).toBe("failed"));
    expect(result.current.detail).toBeNull();
  });

  it("aborts a superseded request and does not report its abort as a failure", async () => {
    const settlers: Array<{ resolve: () => void; reject: (reason: unknown) => void }> = [];
    const gatedLoader: Loader = (_runId, metricKey) => new Promise<ModelPredictiveMetricDetail>((resolve, reject) => {
      settlers.push({ resolve: () => resolve(detail(metricKey)), reject });
    });
    const gated = vi.fn(gatedLoader);
    const transport = { getModelPredictiveMetricDetail: gated };
    const [first, , third] = axesFor(3);
    const initialProps: AxisProps = { axis: first };
    const { result, rerender } = renderHook<PredictiveMetricDetailResult, AxisProps>(
      ({ axis }) => usePredictiveMetricDetail({ transport, runId: RUN_ID, axis }),
      { initialProps },
    );
    expect(result.current.state).toBe("loading");

    rerender({ axis: third });
    expect(gated).toHaveBeenCalledTimes(2);
    expect(gated.mock.calls[0][2]?.aborted).toBe(true);
    expect(gated.mock.calls[1][2]?.aborted).toBe(false);

    await act(async () => {
      settlers[0].reject(new DOMException("aborted", "AbortError"));
      await Promise.resolve();
    });
    expect(result.current).toEqual({ detail: null, state: "loading" });

    await act(async () => {
      settlers[1].resolve();
    });
    await waitFor(() => expect(result.current.detail?.metric.metric_key).toBe("prompt.context_sufficiency"));
    expect(result.current.state).toBe("idle");
  });
});
