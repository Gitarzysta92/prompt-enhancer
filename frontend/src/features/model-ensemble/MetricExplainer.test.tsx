import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MetricExplainerCardSlot,
  MetricExplainerDescriptions,
  metricExplainerDescriptionId,
  metricExplainerTriggerProps,
  type MetricExplainerEntry,
} from "./MetricExplainer";
import {
  METRIC_KNOWLEDGE_CARD_LEAVE_DELAY_MS,
  useMetricKnowledgeCardController,
} from "./MetricKnowledgeCard";
import { METRIC_HELP_V2_KEYS, metricExplainerSentences, metricHelpV2, metricInspectorSentences } from "./metricHelpV2";
import { metricDecisionGuidance } from "../quality-profile/metricGuidance";

afterEach(() => {
  vi.useRealTimers();
});

describe("metricExplainerSentences", () => {
  it("returns exactly two sentences from the canonical registry for every workspace metric", () => {
    for (const key of METRIC_HELP_V2_KEYS) {
      const sentences = metricExplainerSentences(key, { provenance: "measured", numericValue: 0.5 })!;
      expect(sentences).not.toBeNull();
      expect(sentences.explanation).toBe(metricHelpV2(key)!.entry.meaning.trim().replace(/[^.!?]$/u, (last) => `${last}.`));
      expect(sentences.explanation).toMatch(/[.!?]$/u);
      expect(sentences.improvement).toMatch(/[.!?]$/u);
      expect(sentences.improvement).toContain(metricDecisionGuidance(key).tryNext.replace(/[.\s]+$/u, ""));
      expect(sentences.provenanceLabel).toBe("Measured · typed evidence");
      expect(sentences.basis).toBe("measured");
    }
  });

  it("keeps experimental and missing provenance out of the measured voice", () => {
    const experimental = metricExplainerSentences("prompt.context_sufficiency", { provenance: "experimental" })!;
    expect(experimental.improvement).toMatch(/^If the experimental signal persists, /u);
    expect(experimental.provenanceLabel).toMatch(/not measured/u);
    expect(experimental.basis).toBe("experimental");
    const missing = metricExplainerSentences("outcome.first_pass_verification", { provenance: "not_measured" })!;
    expect(missing.improvement).toMatch(/receipt/u);
    expect(missing.provenanceLabel).toBe("Not measured in this scope");
    expect(missing.basis).toBe("readiness");
    const fullyMet = metricExplainerSentences("prompt.task_definition_coverage", { provenance: "measured", numericValue: 1 })!;
    expect(fullyMet.improvement).toMatch(/^Keep the observed practice/u);
  });

  it("returns null for an unregistered metric key", () => {
    expect(metricExplainerSentences("prompt.not_a_metric")).toBeNull();
  });
});

const ENTRIES: readonly MetricExplainerEntry[] = [
  { key: "prompt.task_definition_coverage", label: "Task definition coverage", provenance: "measured", numericValue: 0.72, valueLabel: "72% · 41/57" },
  { key: "logic.decision_rationale_coverage", label: "Decision rationale coverage", provenance: "experimental", numericValue: null, valueLabel: "Unknown" },
];

function Harness({
  compact = false,
  contextIdentity = "team-context-a",
  entries = ENTRIES,
}: {
  compact?: boolean;
  contextIdentity?: string;
  entries?: readonly MetricExplainerEntry[];
}) {
  const controller = useMetricKnowledgeCardController(contextIdentity);
  return (
    <div>
      <MetricExplainerDescriptions controller={controller} entries={entries} surface="team-board" />
      {entries.map((entry) => (
        <button
          key={entry.key}
          {...metricExplainerTriggerProps(controller, "team-board", entry.key)}
          onClick={() => controller.togglePin({ surface: "team-board", metricKey: entry.key })}
          type="button"
        >
          {entry.label}
        </button>
      ))}
      <MetricExplainerCardSlot compact={compact} controller={controller} entries={entries} surface="team-board" />
    </div>
  );
}

describe("MetricExplainer affordance", () => {
  it("describes every trigger with both sentences even when no card is open", () => {
    render(<Harness />);
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);
    for (const entry of ENTRIES) {
      const trigger = screen.getByRole("button", { name: entry.label });
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!);
      expect(description).not.toBeNull();
      const sentences = metricInspectorSentences({
        metricKey: entry.key,
        label: entry.label,
        state: entry.numericValue === null ? "missing" : "known",
        direction: "higher_is_better",
        numericValue: entry.numericValue,
        numerator: null,
        denominator: null,
        experimentalVisible: entry.provenance === "experimental",
      });
      expect(description!.textContent).toContain(sentences.meaning);
      expect(description!.textContent).toContain(sentences.action);
    }
  });

  it("opens one card on hover or focus, pins on click, and closes on Escape", () => {
    vi.useFakeTimers();
    render(<Harness compact />);
    const [first, second] = ENTRIES.map((entry) => screen.getByRole("button", { name: entry.label }));
    fireEvent.pointerEnter(first);
    let cards = document.querySelectorAll('[role="region"][data-metric-key]');
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveAttribute("data-metric-key", "prompt.task_definition_coverage");
    expect(cards[0]).toHaveAttribute("data-provenance", "measured");
    expect(cards[0].className).toContain("metric-explainer-card--compact");
    expect(cards[0].querySelectorAll("p")).toHaveLength(2);
    expect(cards[0].textContent).toContain("Meaning");
    expect(cards[0].textContent).toContain("Next action");
    expect(cards[0].textContent).toContain("Evidence authority");

    fireEvent.pointerLeave(first);
    act(() => { vi.advanceTimersByTime(METRIC_KNOWLEDGE_CARD_LEAVE_DELAY_MS + 1); });
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);

    fireEvent.focus(second);
    cards = document.querySelectorAll('[role="region"][data-metric-key]');
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveAttribute("data-provenance", "experimental");
    expect(cards[0].textContent).toContain("Experimental");

    fireEvent.click(second);
    expect(document.querySelector('[role="region"][data-metric-key]')).toHaveAttribute("data-pinned", "true");
    fireEvent.blur(second);
    act(() => { vi.advanceTimersByTime(METRIC_KNOWLEDGE_CARD_LEAVE_DELAY_MS + 1); });
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(1);
    fireEvent.pointerEnter(first);
    expect(document.querySelector('[role="region"][data-metric-key]')).toHaveAttribute("data-metric-key", "logic.decision_rationale_coverage");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);
  });

  it("binds a touch-pinned explainer to its trigger and positions it outside the row", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1024);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(768);
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Task definition coverage" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 250,
      height: 50,
      left: 700,
      right: 900,
      top: 200,
      width: 200,
      x: 700,
      y: 200,
      toJSON: () => undefined,
    });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.pointerDown(trigger, { pointerType: "touch" });
    fireEvent.click(trigger);

    const card = screen.getByRole("region", { name: "Task definition coverage explainer" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger.getAttribute("aria-controls")).toBe(card.id);
    expect(card).toHaveAttribute("data-pinned", "true");
    expect(card).toHaveAttribute("tabindex", "0");
    expect(card.style.top).toBe("258px");
    expect(card.style.left).toBe("652px");
    expect(card.style.maxHeight).toBe("498px");
  });

  it("dismisses a pinned explainer whose metric disappears from the surface", () => {
    const view = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Task definition coverage" }));
    expect(screen.getByRole("region", { name: "Task definition coverage explainer" }))
      .toHaveAttribute("data-pinned", "true");

    view.rerender(<Harness entries={[ENTRIES[1]]} />);
    expect(screen.queryByRole("region", { name: /explainer/ })).toBeNull();
    fireEvent.focus(screen.getByRole("button", { name: "Decision rationale coverage" }));
    expect(screen.getByRole("region", { name: "Decision rationale coverage explainer" }))
      .toHaveAttribute("data-provenance", "experimental");
  });

  it("dismisses pinned and preview cards before a same-key context changes provenance", () => {
    const entryA = ENTRIES[0];
    const entryB: MetricExplainerEntry = {
      ...entryA,
      provenance: "experimental",
      numericValue: null,
      valueLabel: "Experimental only",
      evidenceAuthority: "Context B exposes model judgment only.",
    };
    const entryC: MetricExplainerEntry = {
      ...entryA,
      numericValue: 0.25,
      valueLabel: "25% · 1/4",
      evidenceAuthority: "Context C exposes a separate typed receipt.",
    };
    const view = render(<Harness contextIdentity="team-context-a" entries={[entryA]} />);
    fireEvent.click(screen.getByRole("button", { name: entryA.label }));
    expect(screen.getByRole("region", { name: `${entryA.label} explainer` }))
      .toHaveAttribute("data-pinned", "true");

    view.rerender(<Harness contextIdentity="team-context-b" entries={[entryB]} />);
    expect(screen.queryByRole("region", { name: /explainer/ })).toBeNull();

    fireEvent.pointerEnter(screen.getByRole("button", { name: entryB.label }));
    const preview = screen.getByRole("region", { name: `${entryB.label} explainer` });
    expect(preview).toHaveAttribute("data-pinned", "false");
    expect(preview).toHaveAttribute("data-provenance", "experimental");
    expect(preview).toHaveTextContent("Context B exposes model judgment only.");

    view.rerender(<Harness contextIdentity="team-context-c" entries={[entryC]} />);
    expect(screen.queryByRole("region", { name: /explainer/ })).toBeNull();
  });

  it("uses distinct description ids per surface", () => {
    const controller = { idPrefix: ":x:" };
    expect(metricExplainerDescriptionId(controller, "team-board", "prompt.a.b"))
      .not.toBe(metricExplainerDescriptionId(controller, "team-compact", "prompt.a.b"));
    expect(metricExplainerDescriptionId(controller, "team-board", "prompt.a.b")).not.toContain(".");
  });

  it("uses r5 reviewed-profile units in both full and compact explainer descriptions and cards", () => {
    const entries: readonly MetricExplainerEntry[] = [{
      key: "prompt.acceptance_testability",
      label: "Acceptance testability",
      projectionVersion: "metric-contract-v2-projection-5",
      provenance: "measured",
      numericValue: 2 / 3,
      valueLabel: "67% · 2/3",
      state: "known",
      direction: "higher_is_better",
      numerator: 2,
      denominator: 3,
    }];
    const copies: string[] = [];
    for (const compact of [false, true]) {
      const view = render(<Harness compact={compact} entries={entries} />);
      const trigger = screen.getByRole("button", { name: "Acceptance testability" });
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toContain("one per expected-outcome slot in the reviewed task profile");
      expect(description.textContent).not.toContain("one per detected requirement clause");
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key="prompt.acceptance_testability"]')!;
      expect(card).toHaveAttribute("data-projection-version", "metric-contract-v2-projection-5");
      expect(card.textContent).toContain("one per expected-outcome slot in the reviewed task profile");
      copies.push(card.textContent ?? "");
      view.unmount();
    }
    expect(copies[1]).toBe(copies[0]);
  });
});
