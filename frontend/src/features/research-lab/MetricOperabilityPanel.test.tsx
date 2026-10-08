import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { MetricOperabilityDefinitionsOutOfDateError } from "../../shared/api/metricOperabilityContract";
import { MetricOperabilityPanel } from "./MetricOperabilityPanel";

describe("MetricOperabilityPanel", () => {
  it("shows the exact r6 16/0/4 partition and keeps model estimates separate", async () => {
    const transport = createSyntheticTransport();
    const sessions = vi.spyOn(transport, "listCodexSessions");

    render(<MetricOperabilityPanel transport={transport} />);

    expect(await screen.findByRole("heading", {
      name: "What can produce measured evidence today",
    })).toBeVisible();
    const summary = screen.getByLabelText("Metric operability summary");
    expect(within(summary).getByText("Measured paths shipped").closest("div")).toHaveTextContent("16");
    expect(within(summary).getByText("Need project profile").closest("div")).toHaveTextContent("0");
    expect(screen.queryByRole("heading", { name: "Project profile needed" })).toBeNull();
    expect(within(summary).getByText("Need source adapter").closest("div")).toHaveTextContent("4");
    expect(screen.getByRole("heading", { name: "Unavailable pending provider adapter" })).toBeVisible();
    expect(screen.getByText(/are explicitly unavailable pending a provider adapter/i)).toBeVisible();
    expect(within(summary).getByText("Model-authored metrics").closest("div")).toHaveTextContent("0");
    expect(screen.getByText("Constraint precision").closest("li")).toHaveAttribute(
      "data-operability-state",
      "available_when_evidence_exists",
    );
    expect(screen.getByText("Agent claim grounding").closest("li")).toHaveAttribute(
      "data-operability-state",
      "provider_adapter_required",
    );
    expect(screen.getAllByText("Separate experimental estimate may be available")).toHaveLength(8);
    expect(screen.getByText("20/20 contracts bound to the current client")).toBeVisible();
    expect(sessions).not.toHaveBeenCalled();
  });

  it("fails closed without the endpoint and never reads a session", async () => {
    const transport = createSyntheticTransport();
    const sessions = vi.spyOn(transport, "listCodexSessions");
    transport.getMetricOperabilityCatalog = undefined;

    render(<MetricOperabilityPanel transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Metric operability is unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("No session was read");
    expect(sessions).not.toHaveBeenCalled();
  });

  it("shows an update boundary for a newer contract identity", async () => {
    const transport = createSyntheticTransport();
    transport.getMetricOperabilityCatalog = vi.fn().mockRejectedValue(
      new MetricOperabilityDefinitionsOutOfDateError(),
    );

    render(<MetricOperabilityPanel transport={transport} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Metric definitions are newer than this app",
    );
    expect(screen.queryByText("Measured paths shipped")).not.toBeInTheDocument();
  });

  it("aborts the catalog request when the panel unmounts", () => {
    const transport = createSyntheticTransport();
    let observedSignal: AbortSignal | undefined;
    transport.getMetricOperabilityCatalog = vi.fn((signal) => {
      observedSignal = signal;
      return new Promise<never>(() => undefined);
    });

    const rendered = render(<MetricOperabilityPanel transport={transport} />);
    expect(observedSignal?.aborted).toBe(false);
    rendered.unmount();
    expect(observedSignal?.aborted).toBe(true);
  });
});
