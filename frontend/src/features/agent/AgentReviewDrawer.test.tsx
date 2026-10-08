import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AgentReviewDrawer, type AgentReviewView } from "./AgentReviewDrawer";

function Harness({ onClose = vi.fn() }: { onClose?: () => void }) {
  const [view, setView] = useState<AgentReviewView>("files");
  return (
    <AgentReviewDrawer
      activeView={view}
      changesPanel={<div><label>Change note<input aria-label="Change note" defaultValue="kept" /></label></div>}
      filesPanel={<div><label>File draft<textarea aria-label="File draft" defaultValue="synthetic draft" /></label></div>}
      onActiveViewChange={setView}
      onClose={onClose}
    />
  );
}

describe("AgentReviewDrawer", () => {
  it("switches between persistent Files and Changes panels", () => {
    render(<Harness />);

    expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute("aria-selected", "true");
    fireEvent.change(screen.getByLabelText("File draft"), { target: { value: "edited synthetic draft" } });

    fireEvent.click(screen.getByRole("tab", { name: "Changes" }));
    expect(screen.getByRole("tab", { name: "Changes" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Change note")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    expect(screen.getByLabelText("File draft")).toHaveValue("edited synthetic draft");
  });

  it("supports roving arrow-key tabs and an explicit close action", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);

    const files = screen.getByRole("tab", { name: "Files" });
    files.focus();
    fireEvent.keyDown(files, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Changes" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Changes" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("button", { name: "Hide workspace" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
