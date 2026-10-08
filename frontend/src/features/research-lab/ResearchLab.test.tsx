import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelEvaluationJob, ModelRuntimeInventory } from "../../shared/api/contracts";
import { ModelCompatibilityPayloadError } from "../../shared/api/modelCompatibilityContract";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { ResearchLab } from "./ResearchLab";

afterEach(() => vi.useRealTimers());

function benchmarkJob(status: ModelEvaluationJob["status"] = "queued"): ModelEvaluationJob {
  return { job_id: "a".repeat(32), status,
    candidate: { allow_download: false, candidate: "session-link", device: "auto", mode: "smoke" },
    created_at: "2040-01-03T09:00:00Z", started_at: null, completed_at: null,
    error_code: null, resolved_device: null, outcomes: [] };
}

describe("ResearchLab", () => {
  it("renders shutdown cancellation as terminal without claiming a completed screen", async () => {
    const transport = createSyntheticTransport();
    transport.startTextModelEvaluation = vi.fn(async () => ({
      ...benchmarkJob("cancelled"), error_code: "application_shutdown" as const,
    }));
    transport.getTextModelEvaluation = vi.fn();
    render(<ResearchLab transport={transport} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Model candidates" }));
    fireEvent.click(screen.getByRole("button", { name: "Test cached session models" }));
    expect(await screen.findByText("Screen cancelled")).toBeVisible();
    expect(screen.getByText(/No evaluation result was accepted/)).toBeVisible();
    expect(screen.queryByText("Screen in progress")).toBeNull();
    expect(screen.queryByText("Screen complete")).toBeNull();
    expect(transport.getTextModelEvaluation).not.toHaveBeenCalled();
  });

  it.each(["missing", "rejected"] as const)("does not show an endless device check when runtime inventory is %s", async (kind) => {
    const transport = createSyntheticTransport();
    const inventory = await transport.getTextModelRuntime!();
    const getRuntime = vi.fn().mockRejectedValueOnce(new Error("synthetic read failure")).mockResolvedValue(inventory);
    const start = vi.spyOn(transport, "startTextModelEvaluation");
    transport.getTextModelRuntime = kind === "missing" ? undefined : getRuntime;
    render(<ResearchLab transport={transport} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Model candidates" }));
    const panel = screen.getByRole("region", { name: "Prepare real local models" });
    expect(await within(panel).findByText(/Local runtime inventory is unavailable/)).toBeVisible();
    expect(within(panel).queryByText("Checking…")).toBeNull();
    if (kind === "rejected") {
      fireEvent.click(within(panel).getByRole("button", { name: "Retry runtime status" }));
      expect(await within(panel).findByText(inventory.preferred_device.toUpperCase())).toBeVisible();
      expect(getRuntime).toHaveBeenCalledTimes(2);
    } else expect(within(panel).queryByRole("button", { name: "Retry runtime status" })).toBeNull();
    expect(start).not.toHaveBeenCalled();
  });

  it("recovers a failed status poll by retrying the same job, never by starting another benchmark", async () => {
    const transport = createSyntheticTransport();
    transport.startTextModelEvaluation = vi.fn(async () => benchmarkJob());
    const poll = vi.fn().mockRejectedValueOnce(new Error("example-status-unavailable")).mockResolvedValue(benchmarkJob("completed"));
    transport.getTextModelEvaluation = poll;
    render(<ResearchLab transport={transport} />);
    await screen.findByRole("tab", { name: "Model candidates" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Test cached session models" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(screen.getByText("Benchmark status unknown")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download & test session models" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry benchmark status" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(screen.getByText("Screen complete")).toBeVisible();
    expect(screen.getByRole("button", { name: "Test cached session models" })).toBeEnabled();
    expect(poll).toHaveBeenCalledTimes(2);
    expect(poll.mock.calls.every(([id]) => id === "a".repeat(32))).toBe(true);
    expect(transport.startTextModelEvaluation).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("The local benchmark status is unavailable.")).not.toBeInTheDocument();
  });

  it("keeps failed status reads unknown and retryable without inventing a failed job", async () => {
    const transport = createSyntheticTransport();
    transport.startTextModelEvaluation = vi.fn(async () => benchmarkJob());
    transport.getTextModelEvaluation = vi.fn().mockRejectedValue(new Error("example-poll-failure"));
    render(<ResearchLab transport={transport} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Model candidates" }));
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Test cached session models" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    fireEvent.click(screen.getByRole("button", { name: "Retry benchmark status" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(screen.getByText("Benchmark status unknown")).toBeVisible();
    expect(screen.queryByText("Screen incomplete")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry benchmark status" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run all cached candidates" })).toBeDisabled();
    expect(transport.startTextModelEvaluation).toHaveBeenCalledTimes(1);
  });

  it("disowns a pending start after transport replacement and prevents double submission", async () => {
    let resolve!: (value: ModelEvaluationJob) => void;
    const pending = new Promise<ModelEvaluationJob>((accept) => { resolve = accept; });
    const transport = createSyntheticTransport();
    const start = vi.fn((_request: unknown, _signal?: AbortSignal) => pending);
    transport.startTextModelEvaluation = start;
    const view = render(<ResearchLab transport={transport} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Model candidates" }));
    const button = screen.getByRole("button", { name: "Test cached session models" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(start).toHaveBeenCalledTimes(1);
    view.rerender(<ResearchLab transport={createSyntheticTransport()} />);
    await act(async () => { resolve(benchmarkJob("completed")); await pending; });
    expect(start.mock.calls[0][1]?.aborted).toBe(true);
    expect(screen.queryByText("Screen complete")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test cached session models" })).toBeEnabled();
  });

  it("shows a compact metric roadmap without reading sessions or activating models", async () => {
    const transport = createSyntheticTransport();
    const inventorySpy = vi.spyOn(transport, "getModelLabInventory");
    const catalogSpy = vi.spyOn(transport, "getTextAnalysisResearch");
    const operabilitySpy = vi.spyOn(transport, "getMetricOperabilityCatalog");
    const sessionSpy = vi.spyOn(transport, "listCodexSessions");
    const analysisSpy = vi.spyOn(transport, "startSessionQualityAnalysis");

    render(<ResearchLab transport={transport} />);

    expect(await screen.findByRole("heading", { name: "Methods & models" })).toBeVisible();
    expect(screen.getByText("One profile, not one developer score")).toBeVisible();
    expect(screen.getByText("Task definition")).toBeVisible();
    expect(screen.getByText("Clarification value")).toBeVisible();
    expect(await screen.findByRole("heading", { name: "What can produce measured evidence today" })).toBeVisible();
    const summary = screen.getByLabelText("Research catalog summary");
    expect(within(summary).getByText("0").closest("div")).toHaveTextContent("neural models activated");
    expect(catalogSpy).toHaveBeenCalledTimes(1);
    expect(operabilitySpy).toHaveBeenCalledTimes(1);
    expect(sessionSpy).not.toHaveBeenCalled();
    expect(analysisSpy).not.toHaveBeenCalled();
    expect(inventorySpy).not.toHaveBeenCalled();
  });

  it("separates methods and candidate decisions into fast views", async () => {
    const transport = createSyntheticTransport();
    const modelStart = vi.spyOn(transport, "startTextModelEvaluation");
    const inventorySpy = vi.spyOn(transport, "getModelLabInventory");
    const compatibilitySpy = vi.spyOn(transport, "getTextModelCompatibility");
    const sessionSpy = vi.spyOn(transport, "listCodexSessions");
    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });

    fireEvent.click(screen.getByRole("tab", { name: "Method stack" }));
    expect(screen.getByRole("heading", { name: "Multilingual semantic retrieval" })).toBeVisible();
    expect(screen.getByText("Blocked by validation")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));
    expect(screen.getByRole("heading", { name: "Multilingual E5 small" })).toBeVisible();
    expect(screen.getAllByText("Rejected by gate").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Product use is off").length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "Synthetic evaluation inventory" })).toBeVisible();
    expect(inventorySpy).toHaveBeenCalledTimes(1);
    const compatibilityTitle = await screen.findByRole("heading", { name: "Model compatibility" });
    const compatibilityPanel = compatibilityTitle.closest("section");
    expect(compatibilityPanel).not.toBeNull();
    const compatibility = within(compatibilityPanel!);
    expect(compatibility.getByRole("heading", { name: "Structured rubric" })).toBeVisible();
    expect(compatibility.getAllByText("Qwen3 4B rubric")).toHaveLength(2);
    expect(compatibility.getByText("Full-precision CUDA screen")).toBeVisible();
    expect(compatibility.getByText("NF4 disposable-child diagnostic")).toBeVisible();
    expect(compatibility.getByText("Documented approximate GPU peak 3.84 GiB; child memory not measured.")).toBeVisible();
    expect(compatibility.getAllByText("Research only").length).toBeGreaterThan(0);
    expect(compatibility.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(compatibility.queryByRole("button")).not.toBeInTheDocument();
    expect(compatibility.queryByText("qwen3_4b_rubric_bitsandbytes_nf4_child_v1")).not.toBeInTheDocument();
    expect(compatibility.queryByText("resource_measurement_missing")).not.toBeInTheDocument();
    expect(compatibilitySpy).toHaveBeenCalledTimes(1);
    expect((await screen.findAllByText("CUDA")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Test cached session models" }));
    expect(await screen.findByText("Screen complete")).toBeVisible();
    expect(screen.getAllByText(/Top1 Accuracy 75%/).length).toBeGreaterThan(0);
    expect(modelStart).toHaveBeenCalledWith(
      {
        candidate: "session-link",
        device: "auto",
        mode: "smoke",
        allow_download: false,
      },
      expect.any(AbortSignal),
    );
    expect(sessionSpy).not.toHaveBeenCalled();
  });

  it("exposes stable, keyboard-operated tabs with valid panel relationships", async () => {
    const transport = createSyntheticTransport();
    const inventorySpy = vi.spyOn(transport, "getModelLabInventory");
    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });

    const tablist = screen.getByRole("tablist", { name: "Research catalog view" });
    const metricTab = screen.getByRole("tab", { name: "Metric roadmap" });
    const methodTab = screen.getByRole("tab", { name: "Method stack" });
    const modelTab = screen.getByRole("tab", { name: "Model candidates" });
    const tabs = [metricTab, methodTab, modelTab];

    for (const tab of tabs) {
      const controlledId = tab.getAttribute("aria-controls");
      expect(controlledId).not.toBeNull();
      expect(document.getElementById(controlledId!)).not.toBeNull();
    }
    const metricPanel = document.getElementById(metricTab.getAttribute("aria-controls")!);
    expect(metricTab).toHaveAttribute("tabindex", "0");
    expect(methodTab).toHaveAttribute("tabindex", "-1");
    expect(metricPanel).toHaveAttribute("aria-labelledby", metricTab.id);
    expect(metricPanel).toHaveAttribute("tabindex", "0");
    expect(metricPanel).not.toHaveAttribute("hidden");

    metricTab.focus();
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    expect(methodTab).toHaveFocus();
    expect(methodTab).toHaveAttribute("aria-selected", "false");
    expect(document.getElementById(methodTab.getAttribute("aria-controls")!)).toHaveAttribute("hidden");
    fireEvent.click(methodTab);
    expect(methodTab).toHaveAttribute("aria-selected", "true");
    expect(document.getElementById(methodTab.getAttribute("aria-controls")!)).not.toHaveAttribute("hidden");

    fireEvent.keyDown(tablist, { key: "End" });
    expect(modelTab).toHaveFocus();
    expect(modelTab).toHaveAttribute("aria-selected", "false");
    expect(inventorySpy).not.toHaveBeenCalled();
    fireEvent.click(modelTab);
    expect(modelTab).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("heading", { name: "Synthetic evaluation inventory" })).toBeVisible();
    expect(inventorySpy).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(tablist, { key: "Home" });
    expect(metricTab).toHaveFocus();
    expect(metricTab).toHaveAttribute("aria-selected", "false");
    fireEvent.click(metricTab);
    expect(metricTab).toHaveAttribute("aria-selected", "true");
  });

  it("names the available download action in missing-cache recovery guidance", async () => {
    const transport = createSyntheticTransport();
    const missingCacheJob: ModelEvaluationJob = {
      candidate: {
        allow_download: false,
        candidate: "session-link",
        device: "auto",
        mode: "smoke",
      },
      completed_at: "2040-01-03T09:00:08Z",
      created_at: "2040-01-03T09:00:00Z",
      error_code: "candidate_evaluation_incomplete",
      job_id: "b".repeat(32),
      outcomes: [{
        error_code: "model_cache_missing_or_invalid",
        key: "multilingual_e5_small",
        status: "not_completed",
      }],
      resolved_device: "cpu",
      started_at: "2040-01-03T09:00:01Z",
      status: "failed",
    };
    transport.startTextModelEvaluation = vi.fn(async () => missingCacheJob);

    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));
    fireEvent.click(await screen.findByRole("button", { name: "Test cached session models" }));

    expect(await screen.findByText(/One or more verified snapshots are missing/)).toHaveTextContent(
      "Download & test session models",
    );
    expect(screen.getByRole("button", { name: "Download & test session models" })).toBeVisible();
  });

  it("fails closed when the catalog capability is absent", async () => {
    const transport = createSyntheticTransport();
    transport.getTextAnalysisResearch = undefined;
    render(<ResearchLab transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The methods catalog is unavailable",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No session was read");
  });

  const cudaInventoryCases = [
    {
      name: "unknown",
      expected: "CUDA status unknown",
      patch: {
        preferred_device: "cpu",
        cuda_state: "unknown",
        cuda_available: null,
        cuda_vram_bucket: null,
        cuda_capability_bucket: null,
        discovery_reason_codes: ["cuda_inventory_unknown"],
      },
    },
    {
      name: "unavailable",
      expected: "CUDA unavailable",
      patch: {
        preferred_device: "cpu",
        cuda_state: "unavailable",
        cuda_available: false,
        cuda_vram_bucket: null,
        cuda_capability_bucket: null,
        discovery_reason_codes: [],
      },
    },
    {
      name: "available",
      expected: "16 GiB class",
      patch: {},
    },
  ] satisfies Array<{
    name: string;
    expected: string;
    patch: Partial<ModelRuntimeInventory>;
  }>;

  it.each(cudaInventoryCases)("renders a human CUDA label when discovery is $name", async ({ expected, patch }) => {
    const transport = createSyntheticTransport();
    const base = await transport.getTextModelRuntime!();
    const compatibility = await transport.getTextModelCompatibility!();
    transport.getTextModelRuntime = vi.fn().mockResolvedValue({
      ...base,
      ...patch,
    } satisfies ModelRuntimeInventory);
    transport.getTextModelCompatibility = vi.fn().mockResolvedValue({
      ...compatibility,
      inventory: {
        ...compatibility.inventory,
        ...patch,
      } satisfies ModelRuntimeInventory,
    });

    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));

    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
    expect(screen.queryByText("Not detected")).not.toBeInTheDocument();
    expect(screen.queryByText("16_gib_class")).not.toBeInTheDocument();
  });

  it("renders a fixed compatibility error without exposing response detail", async () => {
    const transport = createSyntheticTransport();
    transport.getTextModelCompatibility = vi.fn().mockRejectedValue(
      new Error("SYNTHETIC_PRIVATE_CANARY"),
    );

    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Model compatibility is unavailable. No local model action was taken.",
    );
    expect(screen.queryByText("SYNTHETIC_PRIVATE_CANARY")).not.toBeInTheDocument();
  });

  it("renders no model rows when strict compatibility validation rejects the response", async () => {
    const transport = createSyntheticTransport();
    transport.getTextModelCompatibility = vi.fn().mockRejectedValue(
      new ModelCompatibilityPayloadError(),
    );

    render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Model compatibility is unavailable. No local model action was taken.",
    );
    expect(screen.queryByText("Qwen3 4B rubric")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Documented approximate GPU peak 3.84 GiB; child memory not measured."),
    ).not.toBeInTheDocument();
  });

  it("aborts compatibility discovery when the models view unmounts", async () => {
    const transport = createSyntheticTransport();
    let observedSignal: AbortSignal | undefined;
    transport.getTextModelCompatibility = vi.fn((signal) => {
      observedSignal = signal;
      return new Promise<never>(() => undefined);
    });

    const rendered = render(<ResearchLab transport={transport} />);
    await screen.findByRole("heading", { name: "Methods & models" });
    fireEvent.click(screen.getByRole("tab", { name: "Model candidates" }));
    expect(await screen.findByRole("heading", { name: "Model compatibility" })).toBeVisible();
    expect(observedSignal?.aborted).toBe(false);

    rendered.unmount();
    expect(observedSignal?.aborted).toBe(true);
  });
});
