import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelEnsembleRun, ModelEnsembleTrajectoryPoint } from "../../shared/api/contracts";
import { MetricDefinitionsOutOfDateError } from "../../shared/api/metricPublicationV2Contract";
import { modelEnsembleTrajectoryRadarData } from "./trajectorySelection";
import { useTrajectorySelection, type UseTrajectorySelectionResult } from "./useTrajectorySelection";

function point(runId: string, generation: number): ModelEnsembleTrajectoryPoint {
  return {
    generation,
    run_id: runId,
    published_at: `2040-01-0${generation}T10:00:01Z`,
    completed_at: `2040-01-0${generation}T10:00:00Z`,
    max_messages: 100,
    source_coverage_state: "complete_window",
    chunk_count: 1,
    comparable_to_head: true,
    metrics: [],
    typed_metrics: [],
    predictive_metrics: [],
  } as unknown as ModelEnsembleTrajectoryPoint;
}

function sealedRun(runId: string): ModelEnsembleRun {
  return { run_id: runId, metrics: [], typed_metrics: [], chunk_metrics: [], predictive_metrics: [] } as unknown as ModelEnsembleRun;
}

/** Mirrors the hook's `selectedRunId: string | null` so `rerender` may follow the head (null) again. */
type SelectionProps = { selectedRunId: string | null };

describe("useTrajectorySelection", () => {
  const head = sealedRun("9".repeat(64));
  const older = sealedRun("8".repeat(64));
  const points = [point(head.run_id, 2), point(older.run_id, 1)];

  it("does not fetch while following the exact head and fetches only the selected earlier snapshot", async () => {
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) => runId === older.run_id ? older : head);
    const transport = { getModelEnsembleSnapshot };
    const initialProps: SelectionProps = { selectedRunId: head.run_id };
    const { result, rerender } = renderHook<UseTrajectorySelectionResult, SelectionProps>(
      ({ selectedRunId }) => useTrajectorySelection({ transport, points, selectedRunId, headRun: head }),
      { initialProps },
    );
    expect(result.current.selectedRadarRun).toBe(head);
    expect(result.current.selectedExactRun).toBe(head);
    expect(result.current.historicalRun).toBeNull();
    expect(result.current.comparisonRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));
    expect(getModelEnsembleSnapshot).not.toHaveBeenCalled();

    rerender({ selectedRunId: older.run_id });
    expect(result.current.historicalRunId).toBe(older.run_id);
    expect(result.current.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));
    expect(result.current.selectedExactRun).toBeNull();
    await waitFor(() => expect(result.current.historicalRun).toBe(older));
    expect(result.current.selectedRadarRun).toBe(older);
    expect(result.current.selectedExactRun).toBe(older);
    expect(getModelEnsembleSnapshot).toHaveBeenCalledTimes(1);
    expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(older.run_id, expect.any(AbortSignal));

    rerender({ selectedRunId: head.run_id });
    expect(result.current.historicalRun).toBeNull();
    expect(result.current.selectedRadarRun).toBe(head);
    expect(result.current.selectedExactRun).toBe(head);
  });

  it("refuses a snapshot whose run id differs from the requested id and tolerates missing transport support", async () => {
    const wrong = vi.fn(async () => head);
    const wrongTransport = { getModelEnsembleSnapshot: wrong };
    const { result } = renderHook(() =>
      useTrajectorySelection({ transport: wrongTransport, points, selectedRunId: older.run_id, headRun: head }));
    await waitFor(() => expect(wrong).toHaveBeenCalledTimes(1));
    await Promise.resolve();
    expect(result.current.historicalRun).toBeNull();
    expect(result.current.selectedExactRun).toBeNull();
    expect(result.current.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));

    const noSnapshotTransport = {};
    const unsupported = renderHook(() =>
      useTrajectorySelection({ transport: noSnapshotTransport, points, selectedRunId: older.run_id, headRun: head }));
    expect(unsupported.result.current.historicalRun).toBeNull();
    expect(unsupported.result.current.selectedExactRun).toBeNull();
    expect(unsupported.result.current.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(points[1]));
  });

  it("never exposes loaded historical seal A as selected seal B while B is delayed", async () => {
    const runA = sealedRun("7".repeat(64));
    const runB = sealedRun("6".repeat(64));
    const transitionPoints = [point(head.run_id, 3), point(runA.run_id, 2), point(runB.run_id, 1)];
    let resolveA!: (run: ModelEnsembleRun) => void;
    const loadA = new Promise<ModelEnsembleRun>((resolve) => { resolveA = resolve; });
    const loadB = new Promise<ModelEnsembleRun>(() => undefined);
    const getModelEnsembleSnapshot = vi.fn((runId: string) => (
      runId === runA.run_id ? loadA : loadB
    ));
    const transitionTransport = { getModelEnsembleSnapshot };
    const renders: Array<{
      selectedRunId: string | null;
      historicalRunId: string | null;
      selectedExactRunId: string | null;
      refusal: string | null;
    }> = [];
    const hook = renderHook<UseTrajectorySelectionResult, SelectionProps>(
      ({ selectedRunId }) => {
        const value = useTrajectorySelection({
          transport: transitionTransport,
          points: transitionPoints,
          selectedRunId,
          headRun: head,
        });
        renders.push({
          selectedRunId,
          historicalRunId: value.historicalRun?.run_id ?? null,
          selectedExactRunId: value.selectedExactRun?.run_id ?? null,
          refusal: value.historicalRunRefused,
        });
        return value;
      },
      { initialProps: { selectedRunId: runA.run_id } },
    );
    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(
      runA.run_id,
      expect.any(AbortSignal),
    ));
    resolveA(runA);
    await waitFor(() => expect(hook.result.current.selectedExactRun).toBe(runA));

    const transitionRenderStart = renders.length;
    hook.rerender({ selectedRunId: runB.run_id });
    const bRenders = renders.slice(transitionRenderStart).filter((item) => item.selectedRunId === runB.run_id);
    expect(bRenders.length).toBeGreaterThan(0);
    expect(bRenders).toEqual(bRenders.map(() => ({
      selectedRunId: runB.run_id,
      historicalRunId: null,
      selectedExactRunId: null,
      refusal: null,
    })));
    expect(hook.result.current.historicalRun).toBeNull();
    expect(hook.result.current.selectedExactRun).toBeNull();
    expect(hook.result.current.selectedRadarRun).toEqual(modelEnsembleTrajectoryRadarData(transitionPoints[2]));
    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(
      runB.run_id,
      expect.any(AbortSignal),
    ));
  });

  it("never carries historical refusal A into delayed selection B", async () => {
    const runA = sealedRun("5".repeat(64));
    const runB = sealedRun("4".repeat(64));
    const transitionPoints = [point(head.run_id, 3), point(runA.run_id, 2), point(runB.run_id, 1)];
    const delayedB = new Promise<ModelEnsembleRun>(() => undefined);
    const getModelEnsembleSnapshot = vi.fn((runId: string) => runId === runA.run_id
      ? Promise.reject(new MetricDefinitionsOutOfDateError("registry_version"))
      : delayedB);
    const transitionTransport = { getModelEnsembleSnapshot };
    const renders: Array<{ selectedRunId: string | null; refusal: string | null }> = [];
    const hook = renderHook<UseTrajectorySelectionResult, SelectionProps>(
      ({ selectedRunId }) => {
        const value = useTrajectorySelection({
          transport: transitionTransport,
          points: transitionPoints,
          selectedRunId,
          headRun: head,
        });
        renders.push({ selectedRunId, refusal: value.historicalRunRefused });
        return value;
      },
      { initialProps: { selectedRunId: runA.run_id } },
    );
    await waitFor(() => expect(hook.result.current.historicalRunRefused).toBe("registry_version"));

    const transitionRenderStart = renders.length;
    hook.rerender({ selectedRunId: runB.run_id });
    const bRenders = renders.slice(transitionRenderStart).filter((item) => item.selectedRunId === runB.run_id);
    expect(bRenders.length).toBeGreaterThan(0);
    expect(bRenders.every((item) => item.refusal === null)).toBe(true);
    expect(hook.result.current.historicalRunRefused).toBeNull();
    expect(hook.result.current.selectedExactRun).toBeNull();
  });
});
