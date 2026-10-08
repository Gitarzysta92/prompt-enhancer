import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("keeps known neutral state visually distinct from epistemically unknown state", () => {
    const { rerender } = render(<StatusPill tone="neutral">All read</StatusPill>);
    expect(screen.getByText("All read")).toHaveClass("status-pill--neutral");
    expect(screen.getByText("All read")).not.toHaveClass("status-pill--unknown");

    rerender(<StatusPill tone="unknown">Outcome unknown</StatusPill>);
    expect(screen.getByText("Outcome unknown")).toHaveClass("status-pill--unknown");
    expect(screen.getByText("Outcome unknown")).not.toHaveClass("status-pill--neutral");
  });
});
