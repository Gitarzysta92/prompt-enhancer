import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BootstrapFailure, BootstrapLoading } from "./BootstrapState";

describe("bootstrap states", () => {
  it("renders an immediate accessible loading state", () => {
    const { container } = render(<BootstrapLoading />);

    expect(screen.getByRole("status")).toHaveTextContent("Starting Prompt Enhancer…");
    expect(container.querySelector("[data-layout='bootstrap-loading']")).toBeInTheDocument();
  });

  it("fails closed without rendering an exception and exposes an explicit reload", () => {
    const onRetry = vi.fn();
    render(<BootstrapFailure onRetry={onRetry} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Prompt Enhancer could not start");
    expect(alert).toHaveTextContent("No provider error, local path, or session content is shown.");
    expect(alert).not.toHaveTextContent("SYNTHETIC_BOOTSTRAP_SECRET_CANARY");

    fireEvent.click(screen.getByRole("button", { name: "Reload app" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
