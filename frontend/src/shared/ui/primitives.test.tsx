import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";
import { Disclosure } from "./Disclosure";
import { FactList } from "./FactList";
import { LoadingState } from "./AsyncState";
import { ProgressMeter } from "./ProgressMeter";
import { TabList, tabPanelId } from "./Tabs";

afterEach(() => cleanup());

function DialogHarness({ onClose }: { onClose: () => void }) {
  const [tick, setTick] = useState(0);
  return (
    <>
      <button type="button">Opener</button>
      <button onClick={() => setTick((value) => value + 1)} type="button">Tick {tick}</button>
      <Dialog description="A short description." onClose={onClose} open title="Example dialog">
        <button type="button">First</button>
        <button type="button">Second</button>
      </Dialog>
    </>
  );
}

describe("shared UI primitives", () => {
  it("LoadingState announces atomically without suppressing its own live message", () => {
    render(<LoadingState label="Loading synthetic fixtures" />);

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-atomic", "true");
    expect(status).not.toHaveAttribute("aria-busy");
    expect(status).toHaveTextContent("Loading synthetic fixtures");
  });

  it("Dialog traps focus, closes on Escape, restores focus, and does not re-focus on unrelated re-renders", () => {
    const onClose = vi.fn();
    const view = render(<DialogHarness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Opener" });
    opener.focus();
    // Mount with open=true focused the close button; simulate an opener-driven flow instead.
    view.rerender(<DialogHarness onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Example dialog" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("A short description.");
    const close = screen.getByRole("button", { name: "Close dialog" });
    const second = screen.getByRole("button", { name: "Second" });
    second.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(second).toHaveFocus();
    // Unrelated re-render while open must not move focus back to the initial control.
    second.focus();
    fireEvent.click(screen.getByRole("button", { name: /Tick/ }));
    expect(screen.getByRole("button", { name: /Tick 1/ })).toBeInTheDocument();
    expect(second).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Dialog returns focus to the element focused before it opened", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)} type="button">Open</button>
          <Dialog onClose={() => setOpen(false)} open={open} title="Return focus">
            <p>Body</p>
          </Dialog>
        </>
      );
    }
    render(<Harness />);
    const open = screen.getByRole("button", { name: "Open" });
    open.focus();
    fireEvent.click(open);
    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(open).toHaveFocus();
  });

  it("Dialog skips focusable descendants of a collapsed Disclosure", () => {
    function Harness() {
      const hiddenActionRef = useRef<HTMLButtonElement>(null);
      return (
        <Dialog
          initialFocusRef={hiddenActionRef}
          onClose={vi.fn()}
          open
          title="Disclosure dialog"
        >
          <Disclosure summary="Advanced options">
            <button ref={hiddenActionRef} type="button">Hidden action</button>
          </Disclosure>
        </Dialog>
      );
    }
    render(<Harness />);

    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
    const trigger = screen.getByRole("button", { name: "Advanced options" });
    trigger.focus();
    fireEvent.keyDown(document, { key: "Tab" });

    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  });

  it("Dialog falls back when the requested initial control is disabled", () => {
    function Harness() {
      const disabledRef = useRef<HTMLButtonElement>(null);
      return (
        <Dialog initialFocusRef={disabledRef} onClose={vi.fn()} open title="Disabled initial control">
          <button disabled ref={disabledRef} type="button">Unavailable action</button>
        </Dialog>
      );
    }
    render(<Harness />);

    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  });

  it("Dialog falls back when CSS hides the requested initial control", () => {
    function Harness() {
      const hiddenRef = useRef<HTMLButtonElement>(null);
      return (
        <Dialog initialFocusRef={hiddenRef} onClose={vi.fn()} open title="CSS-hidden initial control">
          <button ref={hiddenRef} style={{ display: "none" }} type="button">Hidden action</button>
        </Dialog>
      );
    }
    render(<Harness />);

    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  });

  it.each([
    { label: "disabled", props: { disabled: true } },
    { label: "aria-disabled", props: { "aria-disabled": true } },
    { label: "CSS-hidden", props: { style: { display: "none" } } },
  ])("Dialog recaptures Tab when the active control becomes $label", ({ props }) => {
    function Harness({ unavailable }: { unavailable: boolean }) {
      const targetRef = useRef<HTMLButtonElement>(null);
      return (
        <Dialog initialFocusRef={targetRef} onClose={vi.fn()} open title="Dynamic availability">
          <button ref={targetRef} type="button" {...(unavailable ? props : {})}>Changing action</button>
        </Dialog>
      );
    }
    const rendered = render(<Harness unavailable={false} />);
    const target = screen.getByRole("button", { name: "Changing action" });
    expect(target).toHaveFocus();

    rendered.rerender(<Harness unavailable />);
    fireEvent.keyDown(document, { key: "Tab" });

    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  });

  it("Dialog excludes every negative tabindex from its sequential focus loop", () => {
    render(
      <Dialog onClose={vi.fn()} open title="Negative tabindex">
        <button tabIndex={-2} type="button">Programmatic only</button>
      </Dialog>,
    );
    const close = screen.getByRole("button", { name: "Close dialog" });
    close.focus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });

    expect(close).toHaveFocus();
  });

  it("Dialog portals, isolates the page, and restores pre-existing inert and scroll state", () => {
    const preInert = document.createElement("aside");
    preInert.setAttribute("inert", "preserve-me");
    document.body.append(preInert);
    document.body.style.overflow = "clip";
    document.documentElement.style.overflow = "scroll";
    const rendered = render(<Dialog onClose={vi.fn()} open title="Isolated"><p>Body</p></Dialog>);
    const root = document.querySelector<HTMLElement>("[data-ui-dialog-root]");

    expect(root?.parentElement).toBe(document.body);
    expect(rendered.container).toHaveAttribute("inert");
    expect(preInert).toHaveAttribute("inert", "preserve-me");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");

    rendered.rerender(<Dialog onClose={vi.fn()} open={false} title="Isolated"><p>Body</p></Dialog>);

    expect(rendered.container).not.toHaveAttribute("inert");
    expect(preInert).toHaveAttribute("inert", "preserve-me");
    expect(document.body.style.overflow).toBe("clip");
    expect(document.documentElement.style.overflow).toBe("scroll");
    preInert.remove();
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  });

  it("Dialog keeps isolation until the last modal closes and only the top modal handles Escape", () => {
    const outerClose = vi.fn();
    const innerClose = vi.fn();
    function Harness({ innerOpen, outerOpen }: { innerOpen: boolean; outerOpen: boolean }) {
      return (
        <Dialog onClose={outerClose} open={outerOpen} title="Outer">
          <button type="button">Outer action</button>
          <Dialog onClose={innerClose} open={innerOpen} title="Inner"><p>Inner body</p></Dialog>
        </Dialog>
      );
    }
    const rendered = render(<Harness innerOpen outerOpen />);
    const roots = [...document.querySelectorAll<HTMLElement>("[data-ui-dialog-root]")];
    expect(roots).toHaveLength(2);
    const innerRoot = roots.find((root) => root.textContent?.includes("Inner body"));
    const outerRoot = roots.find((root) => root.textContent?.includes("Outer action"));
    expect(innerRoot).toBeDefined();
    expect(outerRoot).toBeDefined();
    expect(Number(innerRoot?.dataset.uiDialogLayer)).toBeGreaterThan(
      Number(outerRoot?.dataset.uiDialogLayer),
    );
    expect(innerRoot).not.toHaveAttribute("inert");
    expect(innerRoot).not.toHaveAttribute("aria-hidden");
    expect(innerRoot?.querySelector("[role='dialog']")).toHaveAttribute("aria-modal", "true");
    expect(outerRoot).toHaveAttribute("inert");
    expect(outerRoot).toHaveAttribute("aria-hidden", "true");
    expect(outerRoot?.querySelector("[role='dialog']")).toHaveAttribute("aria-modal", "false");

    fireEvent.click(innerRoot!.querySelector<HTMLElement>(".ui-dialog__scrim")!);
    expect(innerClose).toHaveBeenCalledTimes(1);
    expect(outerClose).not.toHaveBeenCalled();
    innerClose.mockClear();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(innerClose).toHaveBeenCalledTimes(1);
    expect(outerClose).not.toHaveBeenCalled();

    rendered.rerender(<Harness innerOpen={false} outerOpen />);
    const remainingRoot = document.querySelector<HTMLElement>("[data-ui-dialog-root]");
    expect(remainingRoot).not.toHaveAttribute("inert");
    expect(remainingRoot).not.toHaveAttribute("aria-hidden");
    expect(remainingRoot?.querySelector("[role='dialog']")).toHaveAttribute("aria-modal", "true");
    expect(document.body.style.overflow).toBe("hidden");
    expect(rendered.container).toHaveAttribute("inert");
    rendered.rerender(<Harness innerOpen={false} outerOpen={false} />);
    expect(document.body.style.overflow).toBe("");
    expect(rendered.container).not.toHaveAttribute("inert");
  });

  it("Disclosure is a real button bound to its panel and keeps the panel mounted but hidden", () => {
    render(<Disclosure detail="2 items" summary="Members"><p>Panel body</p></Disclosure>);
    const trigger = screen.getByRole("button", { name: /Members/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    expect(panel).toHaveAttribute("hidden");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel).not.toHaveAttribute("hidden");
  });

  it("FactList renders null details as an explicit not-reported texture, never blank", () => {
    render(<FactList facts={[{ term: "Model", detail: null, missingLabel: "No model estimate reported" }, { term: "Scope", detail: "Me" }]} label="Facts" />);
    const list = screen.getByLabelText("Facts");
    const rows = list.querySelectorAll("div");
    expect(rows[0]).toHaveAttribute("data-unknown", "true");
    expect(rows[0].textContent).toBe("ModelNo model estimate reported");
    expect(rows[1]).not.toHaveAttribute("data-unknown");
  });

  it("ProgressMeter never draws an unknown amount as zero and echoes state in aria-valuetext", () => {
    const { rerender } = render(<ProgressMeter detail="waiting for consent" label="Transfer" state="idle" value={null} />);
    const bar = screen.getByRole("progressbar", { name: "Transfer" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).toHaveAttribute("data-unknown", "true");
    expect(bar).toHaveAttribute("aria-valuetext", "waiting for consent · amount unknown");
    rerender(<ProgressMeter detail="paused" label="Transfer" max={200} state="paused" value={50} />);
    expect(bar).toHaveAttribute("aria-valuenow", "25");
    expect(bar).toHaveAttribute("aria-valuetext", "25% · paused");
  });

  it("ProgressMeter preserves small nonzero percentages and fails closed on invalid numbers", () => {
    const { rerender } = render(<ProgressMeter detail="one synthetic unit" label="Transfer" max={1000} state="active" value={1} />);
    const bar = screen.getByRole("progressbar", { name: "Transfer" });
    expect(bar).toHaveAttribute("aria-valuenow", "0.1");
    expect(bar).toHaveAttribute("aria-valuetext", "0.1% · one synthetic unit");
    expect(screen.getByText("0.1%")).toBeVisible();

    rerender(<ProgressMeter detail="invalid maximum" label="Transfer" max={Number.POSITIVE_INFINITY} state="active" value={1} />);
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).toHaveAttribute("data-unknown", "true");
    expect(bar).toHaveAttribute("aria-valuetext", "invalid maximum · amount unknown");

    rerender(<ProgressMeter detail="invalid value" label="Transfer" max={100} state="active" value={Number.NaN} />);
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).toHaveAttribute("data-unknown", "true");
  });

  it("TabList exposes tabs with roving arrow-key focus and selection", () => {
    function Harness() {
      const [tab, setTab] = useState<"a" | "b">("a");
      return (
        <>
          <TabList idPrefix="x" label="Sections" onChange={setTab} tabs={[{ id: "a", label: "Alpha" }, { id: "b", label: "Beta", badge: 2 }]} value={tab} />
          <div id={tabPanelId("x", tab)} role="tabpanel">{tab}</div>
        </>
      );
    }
    render(<Harness />);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    const beta = screen.getByRole("tab", { name: /Beta/ });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    expect(beta).toHaveAttribute("tabindex", "-1");
    alpha.focus();
    fireEvent.keyDown(screen.getByRole("tablist", { name: "Sections" }), { key: "ArrowRight" });
    expect(beta).toHaveFocus();
    expect(beta).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("b");
    expect(screen.getByLabelText("2 unread")).toBeInTheDocument();
  });

  it("TabList leaves vertical arrows alone and supports manual activation", () => {
    function Harness() {
      const [tab, setTab] = useState<"a" | "b">("a");
      return <TabList activationMode="manual" idPrefix="manual" label="Manual sections" onChange={setTab} tabs={[{ id: "a", label: "Alpha" }, { id: "b", label: "Beta" }]} value={tab} />;
    }
    render(<Harness />);
    const tablist = screen.getByRole("tablist", { name: "Manual sections" });
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    const beta = screen.getByRole("tab", { name: "Beta" });
    alpha.focus();

    expect(fireEvent.keyDown(tablist, { key: "ArrowDown" })).toBe(true);
    expect(alpha).toHaveFocus();
    expect(alpha).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    expect(beta).toHaveFocus();
    expect(beta).toHaveAttribute("tabindex", "0");
    expect(beta).toHaveAttribute("aria-selected", "false");

    fireEvent.click(beta);
    expect(beta).toHaveAttribute("aria-selected", "true");
  });
});
