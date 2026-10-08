import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelEnsembleRun, PromptEnhancerTransport } from "../../shared/api/contracts";
import {
  syntheticMetricPublicationV2,
  type MetricKeyV2,
  type MetricScenarioV2,
} from "../../test/metricPublicationV2Fixture";
import { MetricWorkspace } from "./MetricWorkspace";
import { ModelEnsembleRadar, type ModelEnsembleRadarData } from "./ModelEnsembleRadar";
import {
  metricKnowledgeCardViewportStyle,
} from "./MetricKnowledgeCard";

type TypedMetric = ModelEnsembleRun["typed_metrics"][number];
type ProjectionVersion = NonNullable<ModelEnsembleRun["metric_publication_v2"]>["projection_version"];

function typedMetric(metricKey: string, patch: Partial<TypedMetric>): TypedMetric {
  return {
    metric_key: metricKey,
    value_state: "known",
    numeric_value: 0.5,
    numerator: 1,
    denominator: 2,
    coverage: 1,
    observed_message_count: 2,
    eligible_message_count: 2,
    projection_source: "example-projection",
    explanation_code: null,
    ...patch,
  } as unknown as TypedMetric;
}

const run: ModelEnsembleRadarData = {
  metrics: [],
  chunk_metrics: [],
  typed_metrics: [
    typedMetric("prompt.task_definition_coverage", { numeric_value: 0.5, numerator: 1, denominator: 2 }),
    typedMetric("prompt.problem_evidence_quality", { value_state: "unknown", numeric_value: null, numerator: null, denominator: null }),
    typedMetric("prompt.context_sufficiency", { value_state: "not_applicable", numeric_value: null, numerator: null, denominator: null }),
    typedMetric("prompt.constraint_precision", { value_state: "unknown", numeric_value: null, numerator: null, denominator: null, explanation_code: "episode_horizon_open" }),
    typedMetric("prompt.acceptance_testability", { value_state: "abstained", numeric_value: null, numerator: null, denominator: null }),
    typedMetric("prompt.deliverable_contract", { numeric_value: 0, numerator: 0, denominator: 3 }),
  ],
  predictive_metrics: [],
};

const transport = {
  getModelPredictiveMetricDetail: vi.fn(() => new Promise(() => undefined)),
} as unknown as Pick<PromptEnhancerTransport, "getModelPredictiveMetricDetail">;

function renderWorkspace(mode: "full" | "compact", data: ModelEnsembleRadarData = run) {
  return render(
    <MetricWorkspace
      lensId="task-framing"
      mode={mode}
      onLensChange={() => undefined}
      run={data}
      runId="example-run-0001"
      snapshotLabel="Synthetic snapshot"
      transport={transport}
    />,
  );
}

function projectedRun(
  projectionVersion: ProjectionVersion,
  scenarios: Partial<Record<MetricKeyV2, MetricScenarioV2>>,
): ModelEnsembleRadarData {
  const base = syntheticMetricPublicationV2(scenarios);
  const publication = {
    ...base,
    projection_version: projectionVersion,
    metrics: base.metrics.map((item) => ({
      ...item,
      state: { ...item.state, projection_version: projectionVersion },
    })),
  } as typeof base;
  return {
    metrics: [],
    chunk_metrics: [],
    typed_metrics: [],
    predictive_metrics: [],
    metric_publication_v2: publication,
  };
}

function r5ProfileRun(): ModelEnsembleRadarData {
  return projectedRun("metric-contract-v2-projection-5", {
    "prompt.constraint_precision": { value_state: "known", numerator: 1, denominator: 2 },
    "prompt.acceptance_testability": { value_state: "known", numerator: 2, denominator: 3 },
    "prompt.deliverable_contract": { value_state: "known", numerator: 1, denominator: 2 },
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("personal metric explainers", () => {
  it("names the radar figure, focused inspector, and reading guide without changing metric truth", () => {
    render(<ModelEnsembleRadar contextIdentity="example-run-0001" lensId="task-framing" run={run} snapshotLabel="Synthetic snapshot" />);

    const figure = screen.getByRole("figure", { name: "Task framing" });
    expect(within(figure).getByRole("heading", { level: 4, name: "Task framing" })).toBeVisible();
    expect(within(figure).getByRole("group", { name: "Task framing radar summary" })).toBeVisible();
    expect(within(figure).getByRole("region", { name: "Task definition coverage" })).toBeVisible();
    expect(within(figure).getByRole("heading", { level: 5, name: "Task definition coverage" })).toBeVisible();
    expect(within(figure).getByRole("group", { name: "Task definition coverage value and state" })).toBeVisible();
    const caption = figure.querySelector("figcaption")!;
    expect(figure.getAttribute("aria-describedby")).toBe(caption.id);
    expect(caption.querySelectorAll(":scope > p")).toHaveLength(3);
    expect(caption.textContent).toMatch(/gaps are unknown, not zero/i);
    expect(caption.textContent).toMatch(/not one overall quality score/i);
  });

  it("keeps the radar SVG presentation-only", () => {
    renderWorkspace("full");
    const svg = document.querySelector(".model-ensemble__radar svg")!;
    expect(svg.querySelectorAll("[role], [tabindex], a, button, foreignObject")).toHaveLength(0);
    expect(document.querySelectorAll(".model-ensemble__radar-state").length).toBeGreaterThan(0);
  });

  it("shows exactly one visible card across strip and board surfaces with pointer, focus, pin, and Escape", () => {
    vi.useFakeTimers();
    renderWorkspace("full");
    const cards = () => document.querySelectorAll('[role="region"][data-metric-key]');
    expect(cards()).toHaveLength(0);
    const strip = screen.getByRole("navigation", { name: /metric axes/ });
    const stripButtons = strip.querySelectorAll("button");
    const board = screen.getByRole("region", { name: /exact metric values/i });
    const boardButtons = board.querySelectorAll("button");
    for (const button of [...stripButtons, ...boardButtons]) {
      const description = document.getElementById(button.getAttribute("aria-describedby")!);
      expect(description?.textContent).toMatch(/: /);
    }
    fireEvent.pointerEnter(stripButtons[0]);
    expect(cards()).toHaveLength(1);
    expect(cards()[0].closest(".metric-knowledge-slot")?.getAttribute("data-surface")).toBe("strip");
    fireEvent.pointerEnter(boardButtons[1]);
    expect(cards()).toHaveLength(1);
    expect(cards()[0].closest(".metric-knowledge-slot")?.getAttribute("data-surface")).toBe("board");
    fireEvent.pointerLeave(boardButtons[1]);
    act(() => { vi.advanceTimersByTime(200); });
    expect(cards()).toHaveLength(0);
    fireEvent.focus(stripButtons[2]);
    expect(cards()).toHaveLength(1);
    fireEvent.click(stripButtons[2]);
    expect(cards()[0].getAttribute("data-pinned")).toBe("true");
    fireEvent.pointerEnter(boardButtons[0]);
    expect(cards()).toHaveLength(1);
    expect(cards()[0].getAttribute("data-metric-key")).toBe("prompt.context_sufficiency");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(cards()).toHaveLength(0);
    expect(document.querySelectorAll(".metric-knowledge-slot")).toHaveLength(2);
  });

  it("shows state and provenance-aware two-sentence guidance", () => {
    renderWorkspace("full");
    fireEvent.pointerEnter(screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!);
    const card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card.textContent).toContain("Current state");
    expect(card.textContent).toContain("Next action");
    expect(card).toHaveAttribute("data-state", "known");
    expect([...card.querySelectorAll("dt")].filter((item) => item.textContent === "Evidence authority")).toHaveLength(1);
    expect(card.textContent).not.toContain("Candidate definition evidence notes");
    expect(card.querySelectorAll(".metric-knowledge-card__guidance > p")).toHaveLength(2);
    expect(card.textContent).not.toMatch(/confidence|probability of success/i);
  });

  it("carries scope, contributor, model, and evidence context in full and compact cards and in the hidden description", () => {
    for (const mode of ["full", "compact"] as const) {
      const view = renderWorkspace(mode);
      const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
      expect(document.getElementById(trigger.getAttribute("aria-describedby")!)!.textContent).toMatch(/Scope: Me · this installation\.$/);
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key]')!;
      const context = within(card as HTMLElement).getByRole("region", { name: "Context and evidence" });
      expect(context).toHaveAttribute("data-scope", "me");
      const terms = [...context.querySelectorAll("dt")].map((item) => item.textContent);
      expect(terms).toEqual(["Scope", "Contributors", "Model", "Evidence"]);
      expect(context.textContent).toContain("Me · this installation");
      expect(context.textContent).toContain("One principal (you)");
      expect(context.textContent).toContain("No model estimate reported");
      expect(context.querySelector("[data-unknown='true']")).not.toBeNull();
      expect(context.textContent).not.toMatch(/\b0%|\b0\/0\b/);
      view.unmount();
    }
  });

  it("renders the same two inspector sentences in full and compact mode for the same selection", () => {
    const full = renderWorkspace("full");
    fireEvent.click(screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[3]);
    const fullText = [...document.querySelectorAll(".metric-inspector-sentences p")].map((p) => p.textContent);
    expect(fullText).toHaveLength(2);
    expect(fullText[0]).toMatch(/Pending: the newest episode is still open/);
    expect(document.querySelectorAll(".model-ensemble__guidance")).toHaveLength(0);
    full.unmount();
    renderWorkspace("compact");
    fireEvent.click(screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[3]);
    const compactText = [...document.querySelectorAll(".metric-inspector-sentences p")].map((p) => p.textContent);
    expect(compactText).toEqual(fullText);
  });

  it("keeps a standalone radar working without a workspace controller", () => {
    render(<ModelEnsembleRadar contextIdentity="example-run-0001" lensId="task-framing" run={run} />);
    fireEvent.pointerEnter(screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!);
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(1);
  });

  it("renders the compact card in a viewport overlay without inserting panel height", () => {
    renderWorkspace("compact");
    fireEvent.pointerEnter(screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!);
    const card = document.querySelector('[role="region"][data-metric-key]')!;
    const slot = card.closest(".metric-knowledge-slot");
    expect(slot).not.toBeNull();
    expect(slot?.getAttribute("data-surface")).toBe("strip");
    expect(card.classList.contains("metric-knowledge-card--viewport")).toBe(true);
    expect(card.classList.contains("metric-knowledge-card--compact")).toBe(true);
  });

  it("exposes the open card relationship and captures a touch anchor before pinning", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1280);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(720);
    renderWorkspace("full");
    const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 430,
      height: 70,
      left: 740,
      right: 860,
      top: 360,
      width: 120,
      x: 740,
      y: 360,
      toJSON: () => undefined,
    });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.pointerDown(trigger, { pointerType: "touch" });
    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const card = screen.getByRole("region", { name: "Task definition coverage knowledge card" });
    expect(trigger.getAttribute("aria-controls")).toBe(card.id);
    expect(card).toHaveAttribute("data-pinned", "true");
    expect(card).toHaveAttribute("tabindex", "0");
    expect(card.style.top).toBe("438px");
    expect(card.style.left).toBe("740px");
    card.focus();
    expect(card).toHaveFocus();
    fireEvent.keyDown(card, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("renders projection-r5 reviewed-profile numerators and denominators identically in full and compact knowledge surfaces", () => {
    const cardCopy: string[] = [];
    for (const mode of ["full", "compact"] as const) {
      const view = renderWorkspace(mode, r5ProfileRun());
      const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[3];
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toContain("one per expected constraint-kind slot in the reviewed task profile");
      expect(description.textContent).not.toContain("one per detected constraint clause");
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key="prompt.constraint_precision"]')!;
      expect(card).toHaveAttribute("data-projection-version", "metric-contract-v2-projection-5");
      expect(card.textContent).toContain("Sealed r5 reviewed-profile definition");
      expect(card.textContent).toContain("Denominator: exactly the configured expected_constraint_kinds slots, not detected constraint clauses");
      expect(card.textContent).toContain("Numerator: one configured expected constraint kind");
      expect(card.textContent).toContain("Sealed r5 reviewed-profile measurement");
      expect(card.textContent).not.toContain("Share of detected constraint clauses");
      cardCopy.push(card.textContent ?? "");
      view.unmount();
    }
    expect(cardCopy[1]).toBe(cardCopy[0]);
  });

  it("renders the exact r3 explicit-PLAN lifecycle in full and compact knowledge surfaces", () => {
    const data = projectedRun("metric-contract-v2-projection-3", {
      "logic.open_loop_closure": { value_state: "known", numerator: 1, denominator: 2 },
    });
    const copies: string[] = [];
    for (const mode of ["full", "compact"] as const) {
      const view = render(
        <MetricWorkspace
          lensId="reasoning-trace"
          mode={mode}
          onLensChange={() => undefined}
          run={data}
          runId="example-run-open-loop"
          snapshotLabel="Synthetic open-loop snapshot"
          transport={transport}
        />,
      );
      const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[2];
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toContain("one per documented agent PLAN episode");
      expect(description.textContent).not.toContain("one per detected question");
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key="logic.open_loop_closure"]')!;
      expect(card).toHaveAttribute("data-projection-version", "metric-contract-v2-projection-3");
      expect(card.textContent).toContain("Sealed r3 explicit-plan lifecycle definition");
      expect(card.textContent).toContain("Numerator: one PLAN episode with a later agent ACTION or VERIFICATION whose supersedes_message_ids names that exact PLAN message");
      expect(card.textContent).toContain("Denominator: exactly the provider-declared agent PLAN messages in the bounded window, not detected questions");
      expect(card.textContent).toContain("Documented agent PLAN episodes explicitly superseded by a later agent ACTION or VERIFICATION naming that exact PLAN message divided by the exact documented agent PLAN episodes");
      copies.push(card.textContent ?? "");
      view.unmount();
    }
    expect(copies[1]).toBe(copies[0]);
  });

  it("renders the exact r4 confirmed lifecycle in full and compact knowledge surfaces", () => {
    const data = projectedRun("metric-contract-v2-projection-4", {
      "collaboration.ambiguity_resolution": { value_state: "known", numerator: 1, denominator: 2 },
    });
    const copies: string[] = [];
    for (const mode of ["full", "compact"] as const) {
      const view = render(
        <MetricWorkspace
          lensId="collaboration-flow"
          mode={mode}
          onLensChange={() => undefined}
          run={data}
          runId="example-run-lifecycle"
          snapshotLabel="Synthetic lifecycle snapshot"
          transport={transport}
        />,
      );
      const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[0];
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toContain("one per confirmed enumerated ambiguity opportunity");
      expect(description.textContent).not.toContain("one per clause with an ambiguity marker");
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key="collaboration.ambiguity_resolution"]')!;
      expect(card).toHaveAttribute("data-projection-version", "metric-contract-v2-projection-4");
      expect(card.textContent).toContain("Sealed r4 confirmed-lifecycle definition");
      expect(card.textContent).toContain("Numerator: one enumerated ambiguity opportunity with a confirmed ambiguity_resolution link whose outcome is ambiguity_resolved");
      expect(card.textContent).toContain("Denominator: exactly the authenticated local user's confirmed ambiguity enumeration, not detected ambiguity clauses");
      expect(card.textContent).toContain("Proposed, rejected, undecided, or non-enumerated opportunities do not enter it");
      expect(card.textContent).toContain("Confirmed enumerated ambiguity opportunities with an ambiguity_resolution link whose outcome is ambiguity_resolved divided by the exact authenticated local-user confirmed ambiguity enumeration");
      copies.push(card.textContent ?? "");
      view.unmount();
    }
    expect(copies[1]).toBe(copies[0]);
  });

  it("renders the exact r6 reviewed requirement-plan denominator in full and compact knowledge surfaces", () => {
    const data = projectedRun("metric-contract-v2-projection-6", {
      "logic.decomposition_coverage": {
        value_state: "known",
        numerator: 1,
        denominator: 3,
        explanation_code: "reviewed_requirement_plan_links",
      },
    });
    const copies: string[] = [];
    for (const mode of ["full", "compact"] as const) {
      const view = render(
        <MetricWorkspace
          lensId="reasoning-trace"
          mode={mode}
          onLensChange={() => undefined}
          run={data}
          runId="example-run-requirement-plan"
          snapshotLabel="Synthetic requirement-plan snapshot"
          transport={transport}
        />,
      );
      const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelectorAll("button")[0];
      const description = document.getElementById(trigger.getAttribute("aria-describedby")!)!;
      expect(description.textContent).toContain("one per native-reviewed active requirement clause");
      expect(description.textContent).not.toContain("one per detected requirement");
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector('[role="region"][data-metric-key="logic.decomposition_coverage"]')!;
      expect(card).toHaveAttribute("data-projection-version", "metric-contract-v2-projection-6");
      expect(card.textContent).toContain("Sealed r6 reviewed requirement-plan definition");
      expect(card.textContent).toContain("Numerator: one native-reviewed active requirement clause with disposition linked");
      expect(card.textContent).toContain("Denominator: exactly the active_requirement clauses from the complete native-confirmed classification");
      expect(card.textContent).toContain("excluded clauses, atomic requirements, or lexically detected requirements");
      expect(card.textContent).toContain("Native-reviewed active requirement clauses with disposition linked to one or more revalidated later agent PLAN coordinates divided by the exact active_requirement subset");
      copies.push(card.textContent ?? "");
      view.unmount();
    }
    expect(copies[1]).toBe(copies[0]);
  });

  it("anchors the overlay outside the entire triggering axis row", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1280);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(720);
    const row = { top: 360, bottom: 430, left: 740, right: 860 };
    const below = metricKnowledgeCardViewportStyle({ anchor: row });
    expect(below).toMatchObject({ top: 438, bottom: "auto", maxHeight: 270 });
    expect(Number(below?.top)).toBeGreaterThan(row.bottom);

    const lowRow = { top: 650, bottom: 700, left: 740, right: 860 };
    const above = metricKnowledgeCardViewportStyle({ anchor: lowRow });
    expect(above).toMatchObject({ top: "auto", bottom: 78, maxHeight: 630 });
    expect(720 - Number(above?.bottom)).toBeLessThan(lowRow.top);
  });

  it("keeps an overlay inside narrow and extremely short viewports", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(280);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(100);
    const style = metricKnowledgeCardViewportStyle({
      anchor: { top: 40, bottom: 60, left: 260, right: 280 },
    });

    expect(style).toMatchObject({
      top: 12,
      bottom: "auto",
      left: 12,
      right: "auto",
      maxHeight: 76,
    });
  });

  it("keeps a pinned overlay visible after its captured anchor scrolls out of view", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1024);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(600);
    vi.spyOn(window, "scrollY", "get").mockReturnValue(500);
    const style = metricKnowledgeCardViewportStyle({
      anchor: {
        top: 100,
        bottom: 150,
        left: 500,
        right: 650,
        viewportScrollX: 0,
        viewportScrollY: 0,
      },
    });

    expect(style).toMatchObject({ top: 12, bottom: "auto", left: 500, maxHeight: 576 });
  });

  it("repositions an open anchored card after the viewport changes", () => {
    let viewportHeight = 720;
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1280);
    vi.spyOn(window, "innerHeight", "get").mockImplementation(() => viewportHeight);
    renderWorkspace("full");
    const trigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 430,
      height: 70,
      left: 740,
      right: 860,
      top: 360,
      width: 120,
      x: 740,
      y: 360,
      toJSON: () => undefined,
    });
    fireEvent.pointerEnter(trigger);
    const card = screen.getByRole("region", { name: "Task definition coverage knowledge card" });
    expect(card.style.top).toBe("438px");

    viewportHeight = 400;
    fireEvent(window, new Event("resize"));
    expect(card.style.top).toBe("auto");
    expect(card.style.bottom).toBe("48px");
    expect(card.style.maxHeight).toBe("340px");
  });

  it("dismisses a pinned key when a lens change makes that target unavailable", () => {
    const view = renderWorkspace("full");
    const first = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    fireEvent.click(first);
    expect(document.querySelector('[role="region"][data-metric-key]')?.getAttribute("data-pinned")).toBe("true");

    view.rerender(
      <MetricWorkspace
        lensId="collaboration-flow"
        mode="full"
        onLensChange={() => undefined}
        run={run}
        runId="example-run-0001"
        snapshotLabel="Synthetic snapshot"
        transport={transport}
      />,
    );

    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);
    const next = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    fireEvent.pointerEnter(next);
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(1);
  });

  it("dismisses pinned and preview cards before a same-key sealed-run context changes", () => {
    const runB: ModelEnsembleRadarData = {
      ...run,
      typed_metrics: run.typed_metrics.map((metric) => metric.metric_key === "prompt.task_definition_coverage"
        ? typedMetric(metric.metric_key, {
          value_state: "unknown",
          numeric_value: null,
          numerator: null,
          denominator: null,
          explanation_code: "synthetic_context_b_unknown",
        })
        : metric),
    };
    const view = renderWorkspace("full");
    const firstTrigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    fireEvent.click(firstTrigger);
    expect(document.querySelector('[role="region"][data-metric-key="prompt.task_definition_coverage"]'))
      .toHaveAttribute("data-pinned", "true");

    view.rerender(
      <MetricWorkspace
        lensId="task-framing"
        mode="full"
        onLensChange={() => undefined}
        run={runB}
        runId="example-run-0002"
        snapshotLabel="Synthetic snapshot B"
        transport={transport}
      />,
    );
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);

    const nextTrigger = screen.getByRole("navigation", { name: /metric axes/ }).querySelector("button")!;
    fireEvent.pointerEnter(nextTrigger);
    const preview = document.querySelector('[role="region"][data-metric-key="prompt.task_definition_coverage"]')!;
    expect(preview).toHaveAttribute("data-pinned", "false");
    expect(preview).toHaveAttribute("data-state", "unknown");

    view.rerender(
      <MetricWorkspace
        lensId="task-framing"
        mode="full"
        onLensChange={() => undefined}
        run={run}
        runId="example-run-0003"
        snapshotLabel="Synthetic snapshot C"
        transport={transport}
      />,
    );
    expect(document.querySelectorAll('[role="region"][data-metric-key]')).toHaveLength(0);
  });
});
