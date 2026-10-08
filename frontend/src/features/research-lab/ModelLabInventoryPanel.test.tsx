import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { SYNTHETIC_MODEL_LAB_INVENTORY } from "../../shared/api/syntheticModelLabFixture";
import { ModelLabInventoryPanel } from "./ModelLabInventoryPanel";

describe("ModelLabInventoryPanel", () => {
  it("shows exact persisted counts without reading sessions", async () => {
    const transport = createSyntheticTransport();
    const inventorySpy = vi.spyOn(transport, "getModelLabInventory");
    const sessionSpy = vi.spyOn(transport, "listCodexSessions");
    const analysisSpy = vi.spyOn(transport, "startSessionQualityAnalysis");

    render(<ModelLabInventoryPanel transport={transport} />);

    expect(await screen.findByRole("heading", { name: "Synthetic evaluation inventory" })).toBeVisible();
    expect(screen.getByText("Registered plans").closest("div")).toHaveTextContent("1");
    expect(screen.getByText("Synthetic executions").closest("div")).toHaveTextContent("2");
    expect(screen.getByText("Model votes").closest("div")).toHaveTextContent("4");
    expect(screen.getByText("Product activation off")).toBeVisible();
    expect(screen.getByText(/opened no session/)).toBeVisible();
    expect(inventorySpy).toHaveBeenCalledTimes(1);
    expect(sessionSpy).not.toHaveBeenCalled();
    expect(analysisSpy).not.toHaveBeenCalled();
    expect(document.querySelector(".model-lab-inventory")?.textContent).not.toMatch(/[âÂ]/);
  });

  it("distinguishes a verified empty result from unavailable data", async () => {
    const transport = createSyntheticTransport();
    transport.getModelLabInventory = vi.fn().mockResolvedValue({
      ...SYNTHETIC_MODEL_LAB_INVENTORY,
      registered_plan_count: 0,
      synthetic_execution_count: 0,
      model_run_count: 0,
      model_vote_count: 0,
      metric_estimate_count: 0,
      plans: [],
    });

    render(<ModelLabInventoryPanel transport={transport} />);

    expect(await screen.findByText(/Zero synthetic estimator plans are registered/)).toBeVisible();
    expect(screen.queryByText(/Unknown/)).not.toBeInTheDocument();
  });

  it("renders Unknown with no numeric substitute when verification fails", async () => {
    const transport = createSyntheticTransport();
    transport.getModelLabInventory = vi.fn().mockRejectedValue(new Error("unavailable"));

    render(<ModelLabInventoryPanel transport={transport} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Model Lab inventory: Unknown");
    expect(alert).toHaveTextContent("No missing count is shown as zero");
    expect(screen.queryByText("Registered plans")).not.toBeInTheDocument();
  });
});
