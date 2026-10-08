import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentMessageContent } from "./AgentMessageContent";

describe("AgentMessageContent", () => {
  it("renders GFM structure, fenced code and a copy action", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<AgentMessageContent content={[
      "## Result",
      "",
      "- [x] synthetic check",
      "",
      "| File | State |",
      "| --- | --- |",
      "| `example.ts` | ready |",
      "",
      "```ts",
      "export const example = true;",
      "```",
    ].join("\n")} />);

    expect(screen.getByRole("heading", { name: "Result" })).toBeVisible();
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("table")).toHaveTextContent("example.ts");
    fireEvent.click(screen.getByRole("button", { name: "Copy ts code" }));
    expect(writeText).toHaveBeenCalledWith("export const example = true;");
  });

  it("drops raw HTML, blocks unsafe links and never mounts remote images", () => {
    const { container } = render(<AgentMessageContent content={[
      "<script>globalThis.bad = true</script>",
      "[unsafe](javascript:alert(1))",
      "![tracking pixel](https://example.invalid/private.png)",
    ].join("\n\n")} />);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText("Remote image omitted: tracking pixel")).toBeVisible();
  });

  it("keeps admitted external links isolated from the local Agent page", () => {
    render(<AgentMessageContent content="[Documentation](https://example.invalid/docs) [Uppercase](HTTPS://example.invalid/guide)" />);
    for (const name of ["Documentation", "Uppercase"]) {
      const link = screen.getByRole("link", { name });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer noopener");
    }
  });

  it("keeps hostile schemes, encoded traversal, control bytes and raw event handlers inert", () => {
    const openFile = vi.fn();
    const { container } = render(
      <AgentMessageContent
        content={[
          "[data](data:text/html,synthetic)",
          "[file](file:///synthetic/private.txt)",
          "[protocol relative](//example.invalid/private)",
          "[encoded traversal](workspace:%2e%2e/private.txt)",
          "[encoded drive](workspace:D%3A/private.txt)",
          "[control byte](workspace:src/%00private.txt)",
          '<img src="x" onerror="globalThis.syntheticBad=true">',
        ].join("\n\n")}
        onOpenWorkspaceFile={openFile}
      />,
    );

    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(openFile).not.toHaveBeenCalled();
  });

  it("opens only bounded workspace-relative links through the owned file viewer", () => {
    const openFile = vi.fn();
    const { container } = render(
      <AgentMessageContent
        content={[
          "[Open source](workspace:src/example.ts)",
          "[Traversal](workspace:../private.txt)",
          "[Absolute](workspace:D%3A%5Cprivate.txt)",
        ].join("\n\n")}
        onOpenWorkspaceFile={openFile}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open source" }));
    expect(openFile).toHaveBeenCalledWith("src/example.ts");
    expect(container.querySelectorAll("button")).toHaveLength(1);
    expect(screen.getByText("Traversal")).toHaveClass("agent-markdown__blocked-link");
    expect(screen.getByText("Absolute")).toHaveClass("agent-markdown__blocked-link");
  });

  it("keeps every link inert when rendering a verified artifact", () => {
    const { container } = render(
      <AgentMessageContent
        content="[External](https://example.invalid/private) and [section](#details)"
        linkPolicy="inert"
        variant="artifact"
      />,
    );

    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText("External")).toHaveAttribute(
      "title",
      "Links stay inert in verified artifact previews",
    );
    expect(screen.getByText("section")).toHaveClass("agent-markdown__inert-link");
  });
});
