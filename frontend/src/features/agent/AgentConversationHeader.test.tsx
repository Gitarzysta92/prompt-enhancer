import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentConversationHeader } from "./AgentConversationHeader";

function renderHeader({
  showRuntimeNotice = false,
  runtimeState = "ready",
  runtimeStatus = "Synthetic model is ready.",
}: {
  showRuntimeNotice?: boolean;
  runtimeState?: string;
  runtimeStatus?: string;
} = {}) {
  return render(
    <AgentConversationHeader
      actionCount={2}
      actions={<button type="button">Files &amp; review</button>}
      activity={{ detail: "Ready for a synthetic request.", label: "Ready", tone: "ready" }}
      details={<p>Synthetic workspace · fictional-model</p>}
      reasoningLabel="Reasoning visible"
      reasoningState="visible"
      runtimeActions={<button type="button">Start model</button>}
      runtimeNote={<small>Runtime evidence is synthetic.</small>}
      runtimeState={runtimeState}
      runtimeStatus={runtimeStatus}
      showRuntimeNotice={showRuntimeNotice}
      turnCount={3}
    />,
  );
}

describe("AgentConversationHeader", () => {
  it("keeps operational actions visible and secondary chat metadata disclosed", () => {
    renderHeader();

    expect(screen.getByRole("region", { name: "Agent activity status" })).toHaveTextContent("3 turns");
    expect(screen.getByRole("region", { name: "Agent activity status" })).toHaveTextContent("2 observed actions");
    expect(screen.getByRole("button", { name: "Files & review" })).toBeVisible();
    const disclosure = screen.getByText("Chat details", { exact: true }).closest("details");
    expect(disclosure).not.toHaveAttribute("open");

    fireEvent.click(screen.getByText("Chat details", { exact: true }));

    expect(disclosure).toHaveAttribute("open");
    expect(screen.getByRole("group", { name: "Chat details" })).toBeVisible();
    expect(screen.getByText("Synthetic workspace · fictional-model")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Close chat details" }));

    expect(disclosure).not.toHaveAttribute("open");
    expect(screen.getByText("Chat details", { exact: true })).toHaveFocus();
  });

  it("keeps healthy duplicate runtime status assistive-only", () => {
    const { container } = renderHeader();

    expect(container.querySelector(".agent__model-readiness")).toBeNull();
    expect(screen.getByText("Synthetic model is ready.")).toHaveClass("sr-only");
  });

  it("surfaces runtime states that need attention with their recovery action", () => {
    const { container } = renderHeader({
      runtimeState: "stopped",
      runtimeStatus: "The selected model is stopped.",
      showRuntimeNotice: true,
    });

    expect(container.querySelector(".agent__model-readiness")).toHaveAttribute("data-state", "stopped");
    expect(screen.getByText("The selected model is stopped.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start model" })).toBeVisible();
    expect(screen.getByText("Runtime evidence is synthetic.")).toBeVisible();
  });
});
