import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCopyButton } from "./AgentCopyButton";

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

afterEach(() => {
  vi.useRealTimers();
  if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("AgentCopyButton", () => {
  it("reports success and returns to its stable label", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<AgentCopyButton label="Copy response" value="Synthetic answer" />);

    fireEvent.click(screen.getByRole("button", { name: "Copy response" }));
    await act(async () => { await Promise.resolve(); });
    expect(writeText).toHaveBeenCalledWith("Synthetic answer");
    expect(screen.getByRole("button", { name: "Copy response: copied" })).toHaveTextContent("Copied");

    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole("button", { name: "Copy response" })).toHaveTextContent("Copy");
  });

  it("makes rejected and unavailable clipboard writes visible", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(async () => { throw new Error("synthetic clipboard denial"); }) },
    });
    const rendered = render(<AgentCopyButton label="Copy output" value="Synthetic output" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy output" }));
    expect(await screen.findByRole("button", { name: "Copy output: copy failed" })).toHaveTextContent("Copy failed");

    rendered.unmount();
    Reflect.deleteProperty(navigator, "clipboard");
    render(<AgentCopyButton label="Copy output" value="Synthetic output" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy output" }));
    expect(screen.getByRole("button", { name: "Copy output: copy unavailable" })).toHaveTextContent("Copy unavailable");
  });
});
