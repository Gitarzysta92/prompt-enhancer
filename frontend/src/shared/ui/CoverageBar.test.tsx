import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoverageBar } from "./CoverageBar";

describe("CoverageBar", () => {
  it("preserves a small nonzero value for sighted and assistive output", () => {
    render(<CoverageBar coverage={1 / 1000} eligible={1000} observed={1} />);

    const meter = screen.getByRole("meter", {
      name: "1 of 1000 observations (0.1%)",
    });
    expect(meter).toHaveAttribute("aria-valuenow", "0.1");
    expect(screen.getByText("0.1%")).toBeVisible();
  });

  it("does not represent no eligible evidence as numeric zero", () => {
    const { container } = render(<CoverageBar coverage={0} eligible={0} observed={0} />);

    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText("Not observed")).toBeVisible();
    expect(screen.getByText("No eligible evidence")).toBeVisible();
    expect(container.querySelector(".coverage__track")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector("[aria-valuenow]")).toBeNull();
  });

  it("fails closed when the coverage inputs are inconsistent or non-finite", () => {
    const { rerender } = render(<CoverageBar coverage={Number.NaN} eligible={2} observed={1} />);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.getAllByText("Coverage unavailable").length).toBeGreaterThan(0);

    rerender(<CoverageBar coverage={0.5} eligible={2} observed={3} />);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(screen.getAllByText("Coverage unavailable").length).toBeGreaterThan(0);
  });
});
