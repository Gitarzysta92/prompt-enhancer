import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MetricReadiness } from "../../shared/api/contracts";
import "../../styles.css";
import {
  QualityRadar,
  radarMetricsFor,
  radarRingPoints,
} from "./QualityRadar";
import type {
  QualityMetricObservation,
  QualityMetricPolarity,
  QualityMetricState,
} from "./qualityProfile";

function syntheticMetric({
  dimension = "prompt",
  key,
  label,
  modelId = null,
  polarity = "capability",
  ratio,
  state = ratio === null ? "unavailable" : "observed",
}: {
  dimension?: QualityMetricObservation["definition"]["dimension"];
  key: string;
  label: string;
  modelId?: string | null;
  polarity?: QualityMetricPolarity;
  ratio: number | null;
  state?: QualityMetricState;
}): QualityMetricObservation {
  const denominator = ratio === null ? null : 10;
  const numerator = ratio === null ? null : Math.round(ratio * denominator!);
  return {
    definition: {
      key,
      version: key === "prompt.deliverable_contract" ? 3 : 2,
      kind: dimension === "logic" || dimension === "outcome" ? "logic" : "prompt",
      dimension,
      unit: polarity === "review-load" ? "risk_ratio" : "ratio",
      direction: polarity === "review-load" ? "lower_is_better" : "higher_is_better",
      shortLabel: label,
      label: `${label} full metric name`,
      question: `What does the fictional ${label.toLowerCase()} metric inspect?`,
      method: `Synthetic ${label.toLowerCase()} method for visual testing.`,
      limitation: `Synthetic ${label.toLowerCase()} limitation.`,
      polarity,
    },
    state,
    ratio,
    fractionNumerator: numerator,
    fractionDenominator: denominator,
    observed: ratio === null ? 7 : 8,
    eligible: 10,
    notSelectedRuns: 0,
    unknownScopeRuns: 0,
    coverage: ratio === null ? 0.7 : 0.8,
    confidence: null,
    signals: [],
    metricSchemaVersion: 2,
    explanationCode: ratio === null ? "synthetic_unknown" : null,
    algorithmId: "private-algorithm-id-canary",
    algorithmVersion: "1",
    modelId,
    errorCode: ratio === null ? "insufficient-evidence" : null,
    definitionVersion: 2,
    computedAt: "2040-01-01T00:00:00Z",
  };
}

function promptAndCollaborationMetrics(): QualityMetricObservation[] {
  return [
    syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: 0.2,
    }),
    syntheticMetric({
      key: "prompt.problem_evidence_quality",
      label: "Evidence",
      ratio: 0.4,
    }),
    syntheticMetric({
      key: "prompt.context_sufficiency",
      label: "Context",
      ratio: null,
    }),
    syntheticMetric({
      key: "prompt.constraint_precision",
      label: "Constraints",
      ratio: 0,
    }),
    syntheticMetric({
      key: "prompt.acceptance_testability",
      label: "Checkability",
      ratio: 0.8,
    }),
    syntheticMetric({
      key: "prompt.deliverable_contract",
      label: "Deliverable",
      ratio: 1,
    }),
    syntheticMetric({
      dimension: "collaboration",
      key: "collaboration.ambiguity_resolution",
      label: "Ambiguity",
      ratio: 0.3,
    }),
    syntheticMetric({
      dimension: "collaboration",
      key: "collaboration.clarification_yield",
      label: "Clarify",
      ratio: 0.5,
    }),
    syntheticMetric({
      dimension: "collaboration",
      key: "collaboration.exploration_conversion",
      label: "Explore",
      ratio: 0.7,
    }),
    syntheticMetric({
      dimension: "collaboration",
      key: "collaboration.scope_change_discipline",
      label: "Scope",
      ratio: 0.4,
    }),
    syntheticMetric({
      dimension: "collaboration",
      key: "collaboration.rework_candidate_rate",
      label: "Rework",
      polarity: "review-load",
      ratio: 0.6,
    }),
  ];
}

function syntheticReadiness(
  metric: QualityMetricObservation,
  input: Pick<MetricReadiness, "state" | "reason_code" | "next_actions"> &
    Partial<MetricReadiness>,
): MetricReadiness {
  return {
    metric_key: metric.definition.key,
    metric_version: metric.definition.version,
    dimension: metric.definition.dimension,
    display_name: "Fictional readiness display label",
    unit: metric.definition.unit,
    direction: metric.definition.direction,
    radar_policy:
      metric.definition.direction === "lower_is_better"
        ? "exact_value_only_unnormalized_lower_is_better"
        : "direct_bounded_ratio",
    evidence_tier: "redacted_content",
    capability_groups: [["request_text"]],
    available_capabilities: ["request_text"],
    missing_capabilities: [],
    latest_run_id: "a".repeat(64),
    ...input,
  };
}

describe("QualityRadar", () => {
  it.each([3, 4, 6, 8])("builds a closed polygon web for %i fixed-scale axes", (count) => {
    const points = radarRingPoints(count, 1).trim().split(/\s+/);

    expect(points).toHaveLength(count);
    expect(new Set(points).size).toBe(count);
  });

  it("shows only represented versioned lenses and a fixed-scale selected-lens radar", () => {
    const { container } = render(
      <QualityRadar metrics={promptAndCollaborationMetrics()} />,
    );

    const lensGroup = screen.getByRole("group", { name: "Quality lenses" });
    expect(within(lensGroup).getAllByRole("button")).toHaveLength(2);
    expect(within(lensGroup).getByRole("button", { name: /Framing, 6 of 6 metrics/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(lensGroup).getByRole("button", { name: /Collaboration, 5 of 5 metrics/i })).toBeVisible();
    expect(within(lensGroup).queryByText("Trace")).not.toBeInTheDocument();
    expect(within(lensGroup).queryByText("Outcome")).not.toBeInTheDocument();

    const radar = screen.getByRole("img", {
      name: /fixed-scale quality lens radar/i,
    });
    expect(radar.querySelectorAll(".quality-radar__axis-control")).toHaveLength(5);
    expect(radar.querySelectorAll("polygon.quality-radar__ring")).toHaveLength(4);
    expect(radar.querySelectorAll("circle.quality-radar__ring")).toHaveLength(0);
    for (const ring of radar.querySelectorAll("polygon.quality-radar__ring")) {
      expect(ring.getAttribute("points")?.trim().split(/\s+/)).toHaveLength(5);
    }
    expect(radar.querySelector('[data-filled-profile="true"]')).toBeVisible();
    expect(radar.querySelectorAll(".quality-radar__coverage-ring")).toHaveLength(5);
    expect(
      radar.querySelector('.quality-radar__coverage-ring[data-input-coverage="80%"]'),
    ).toBeVisible();
    expect(radar.querySelector(".quality-radar__center")).toBeNull();
    expect(
      radar.querySelector('.quality-radar__point[cx="280"][cy="280"]'),
    ).toHaveAttribute("r", "5");
    expect(within(radar).queryByText("Context")).not.toBeInTheDocument();
    expect(radar.querySelector(".quality-radar__scale--zero")).toHaveTextContent("0%");
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "5 measured",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "5 plottable axes",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 unknown",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 measured zero",
    );
    expect(screen.getByText(/Every axis is fixed at 0-100%/i)).toBeVisible();
    expect(container.querySelector("figcaption")).toHaveTextContent(
      /ring around each point shows usable input coverage/i,
    );
    expect(screen.getByText(/No combined score is calculated/i)).toBeVisible();
    expect(container.querySelector("select")).not.toBeInTheDocument();
  });

  it("switches lenses with native buttons and keeps review load outside the radar", () => {
    render(<QualityRadar metrics={promptAndCollaborationMetrics()} />);

    fireEvent.click(screen.getByRole("button", { name: /Collaboration, 5 of 5 metrics/i }));

    expect(screen.getByRole("heading", { name: "Collaboration flow" })).toBeVisible();
    const radar = screen.getByRole("img");
    expect(radar.querySelectorAll(".quality-radar__axis-control")).toHaveLength(4);
    expect(within(radar).queryByText("Rework")).not.toBeInTheDocument();
    const board = screen.getByRole("region", { name: "Collaboration flow metrics" });
    expect(within(board).getAllByRole("button")).toHaveLength(5);
    const reviewRow = within(board).getByRole("button", {
      name: /Rework full metric name/i,
    });
    expect(reviewRow).toHaveTextContent("Lower is better; raw value");
    expect(reviewRow).toHaveTextContent("60%");
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 review-load in exact board",
    );
  });

  it("previews on hover or focus, pins on click, and clears on Escape", () => {
    render(<QualityRadar metrics={promptAndCollaborationMetrics()} />);
    const board = screen.getByRole("region", { name: "Task framing metrics" });
    const evidence = within(board).getByRole("button", {
      name: /Evidence full metric name/i,
    });
    const task = within(board).getByRole("button", {
      name: /Task full metric name/i,
    });

    expect(screen.getByRole("heading", { name: "Task full metric name" })).toBeVisible();
    expect(screen.getByRole("complementary")).toHaveAttribute("aria-live", "off");
    fireEvent.mouseEnter(evidence);
    expect(screen.getByRole("heading", { name: "Evidence full metric name" })).toBeVisible();
    fireEvent.mouseLeave(evidence);
    expect(screen.getByRole("heading", { name: "Task full metric name" })).toBeVisible();

    fireEvent.click(evidence);
    expect(evidence).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Pinned metric")).toBeVisible();
    expect(screen.getByRole("complementary")).toHaveAttribute("aria-live", "polite");
    const radar = screen.getByRole("img");
    expect(radar.querySelector(".quality-radar__point--active")).toHaveAttribute(
      "r",
      "7",
    );
    expect(radar.querySelector(".quality-radar__axis-control--active")).toBeNull();
    expect(radar.querySelector(".quality-radar__axis-control--pinned")).toBeNull();
    for (const axis of radar.querySelectorAll(".quality-radar__axis")) {
      expect(axis).not.toHaveAttribute("stroke-dasharray");
    }
    fireEvent.mouseEnter(task);
    expect(screen.getByRole("heading", { name: "Evidence full metric name" })).toBeVisible();
    fireEvent.mouseLeave(task);
    expect(screen.getByRole("heading", { name: "Evidence full metric name" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Clear pin" }));

    const constraints = within(board).getByRole("button", {
      name: /Constraints full metric name/i,
    });
    fireEvent.focus(constraints);
    expect(screen.getByRole("heading", { name: "Constraints full metric name" })).toBeVisible();
    fireEvent.click(constraints);
    expect(constraints).toHaveAttribute("aria-pressed", "true");
    expect(
      screen
        .getByRole("img")
        .querySelector('.quality-radar__point--active[cx="280"][cy="280"]'),
    ).toHaveAttribute("r", "7");
    fireEvent.keyDown(constraints, { key: "Escape" });
    expect(constraints).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "Clear pin" })).not.toBeInTheDocument();
  }, 20_000);

  it("shows a content-free inspector with exact semantics and no provenance identifiers", () => {
    const metrics = promptAndCollaborationMetrics();
    metrics[0] = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      modelId: "private-model-id-canary",
      ratio: 0.2,
      state: "partial",
    });
    const { container } = render(<QualityRadar metrics={metrics} />);

    const inspector = screen.getByRole("complementary");
    expect(within(inspector).getByText("Partial input")).toBeVisible();
    expect(within(inspector).getByText("20% candidate ratio")).toBeVisible();
    expect(within(inspector).getByText("2 of 10")).toBeVisible();
    expect(within(inspector).getByText("8/10 usable · 80%")).toBeVisible();
    expect(
      within(inspector).getByRole("region", { name: "Decision guidance" }),
    ).toHaveTextContent("Specification signal");
    expect(within(inspector).getByText("Why it matters")).toBeVisible();
    expect(within(inspector).getByText("Review next")).toBeVisible();
    expect(within(inspector).getByText("Try next")).toBeVisible();
    expect(within(inspector).getByText("Confirm with")).toBeVisible();
    expect(
      within(inspector).getByText(/visible action, target, and intended outcome/i),
    ).toBeVisible();
    expect(
      within(inspector).getByText(/one compact task-contract sentence/i),
    ).toBeVisible();
    const taskMetric = within(
      screen.getByRole("region", { name: "Task framing metrics" }),
    ).getByRole("button", { name: /Task full metric name/i });
    expect(taskMetric).toHaveTextContent("Raw 2/10");
    expect(taskMetric).toHaveTextContent("Input 8/10 usable · 80%");
    expect(within(inspector).getByText(/Synthetic task method/i)).not.toBeVisible();

    fireEvent.click(
      within(inspector).getByText("Method & limits", { selector: "summary" }),
    );

    expect(within(inspector).getByText("Higher is better.")).toBeVisible();
    expect(within(inspector).getByText(/Synthetic task method/i)).toBeVisible();
    expect(within(inspector).getByText("Local model-assisted analysis")).toBeVisible();
    expect(within(inspector).getByText("Definition v2; Method revision 1")).toBeVisible();
    expect(within(inspector).getByText("Not calibrated; confidence unavailable.")).toBeVisible();
    expect(within(inspector).getByText("Synthetic task limitation.")).toBeVisible();
    expect(container).not.toHaveTextContent("private-model-id-canary");
    expect(container).not.toHaveTextContent("private-algorithm-id-canary");

    const longName = within(
      screen.getByRole("region", { name: "Task framing metrics" }),
    ).getByText("Task full metric name");
    expect(getComputedStyle(longName).overflowWrap).toBe("break-word");
    expect(getComputedStyle(longName).wordBreak).toBe("normal");
    expect(
      getComputedStyle(longName.closest(".quality-board__metric-heading")!).display,
    ).toBe("grid");
    expect(longName.closest("button")?.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("drops a same-key pin synchronously when metric provenance and values change", () => {
    const first = promptAndCollaborationMetrics();
    const second = promptAndCollaborationMetrics();
    second[0] = {
      ...second[0],
      ratio: 0.9,
      fractionNumerator: 9,
      algorithmVersion: "synthetic-revision-b",
      computedAt: "2040-01-02T00:00:00Z",
    };
    const { rerender } = render(<QualityRadar metrics={first} />);
    fireEvent.click(screen.getByRole("button", { name: /Evidence full metric name/i }));
    expect(screen.getByRole("button", { name: "Clear pin" })).toBeVisible();

    rerender(<QualityRadar metrics={second} />);

    expect(screen.queryByRole("button", { name: "Clear pin" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Task full metric name/i })).toHaveTextContent("90%");
  });

  it("uses one exact-value control rail without redundant plot controls", () => {
    const { container } = render(
      <QualityRadar metrics={promptAndCollaborationMetrics()} />,
    );

    const rail = container.querySelector(".quality-radar__rail");
    expect(rail).toBeVisible();
    expect(rail?.querySelectorAll(".quality-board")).toHaveLength(0);
    const exactBoard = container.querySelector(".quality-radar__explorer > .quality-board");
    const workspace = container.querySelector(".quality-radar__workspace--secondary");
    expect(exactBoard).toBeVisible();
    expect(workspace).toBeVisible();
    expect(
      exactBoard!.compareDocumentPosition(workspace!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(container.querySelector(".quality-radar__axis-list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /focus plot/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /zoom/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pan/i })).not.toBeInTheDocument();
  });

  it("renders a three-axis triangle at the radar floor", () => {
    const metrics = promptAndCollaborationMetrics().slice(0, 3);
    metrics[2] = syntheticMetric({
      key: "prompt.context_sufficiency",
      label: "Context",
      ratio: 0.6,
    });

    render(<QualityRadar metrics={metrics} />);

    const radar = screen.getByRole("img", { name: /3-axis/i });
    expect(radar.querySelectorAll(".quality-radar__axis-control")).toHaveLength(3);
    expect(radar.querySelector('[data-filled-profile="true"]')).toBeVisible();
    for (const ring of radar.querySelectorAll("polygon.quality-radar__ring")) {
      expect(ring.getAttribute("points")?.trim().split(/\s+/)).toHaveLength(3);
    }
  });

  it("uses aligned exact-value bars for two capability axes and keeps lower-is-better in the board", () => {
    render(
      <QualityRadar
        metrics={[
          syntheticMetric({
            key: "prompt.task_definition_coverage",
            label: "Task",
            ratio: 0.2,
          }),
          syntheticMetric({
            key: "prompt.problem_evidence_quality",
            label: "Evidence",
            ratio: 0.4,
          }),
          syntheticMetric({
            key: "prompt.context_sufficiency",
            label: "Context",
            polarity: "review-load",
            ratio: 0.6,
          }),
        ]}
      />,
    );

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    const fallback = screen.getByLabelText("Exact-value bar fallback");
    expect(within(fallback).getByText(/Radar withheld/i)).toBeVisible();
    expect(within(fallback).getByText(/2 of 3 metrics are compatible/i)).toBeVisible();
    expect(
      within(fallback).getByRole("list", { name: "Compatible exact-value bars" }),
    ).toBeVisible();
    expect(within(fallback).getAllByRole("listitem")).toHaveLength(2);
    expect(within(fallback).queryByText("Context")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "3 measured",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "2 plottable axes",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 review-load in exact board",
    );
    expect(
      within(screen.getByRole("region", { name: "Task framing metrics" })).getByRole(
        "button",
        { name: /Context full metric name/i },
      ),
    ).toHaveTextContent("Lower is better; raw value");
    expect(
      within(screen.getByRole("region", { name: "Task framing metrics" })).getAllByRole(
        "button",
      ),
    ).toHaveLength(3);
  });

  it("caps compatible axes at eight", () => {
    const metrics = Array.from({ length: 10 }, (_, index) =>
      syntheticMetric({
        key: `prompt.synthetic_${index}`,
        label: `Axis ${index + 1}`,
        ratio: (index + 1) / 10,
      }),
    );

    expect(radarMetricsFor(metrics)).toHaveLength(8);
  });

  it("keeps zero plottable and excludes every non-measured state", () => {
    const zero = syntheticMetric({
      key: "prompt.zero",
      label: "Zero",
      ratio: 0,
    });
    const nonMeasuredStates: QualityMetricState[] = [
      "not-selected",
      "incompatible",
      "unavailable",
      "abstained",
      "not-applicable",
      "execution-error",
    ];
    const incompatible = nonMeasuredStates.map((state, index) =>
      syntheticMetric({
        key: `prompt.excluded_${index}`,
        label: state,
        ratio: 0.7,
        state,
      }),
    );
    const lowerIsBetter = syntheticMetric({
      key: "prompt.review_load",
      label: "Review load",
      polarity: "review-load",
      ratio: 0.3,
    });
    const outOfRange = syntheticMetric({
      key: "prompt.out_of_range",
      label: "Out of range",
      ratio: 1.1,
    });

    expect(
      radarMetricsFor([zero, ...incompatible, lowerIsBetter, outOfRange]),
    ).toEqual([zero]);
  });

  it("withholds incompatible provenance while retaining compatible axes", () => {
    const metrics = promptAndCollaborationMetrics();
    metrics[0] = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: null,
      state: "incompatible",
    });

    render(<QualityRadar metrics={metrics} />);

    const board = screen.getByRole("region", { name: "Task framing metrics" });
    const incompatible = within(board).getByRole("button", {
      name: /Task full metric name/i,
    });
    expect(incompatible).toHaveTextContent("Incompatible");
    expect(screen.getByRole("complementary")).toHaveTextContent(
      "No value — Incompatible provenance",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 incompatible",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "4 plottable axes",
    );
    expect(screen.getByRole("img").querySelectorAll(".quality-radar__axis-control")).toHaveLength(4);
  });

  it("hides lens controls when only one lens is represented", () => {
    render(<QualityRadar metrics={promptAndCollaborationMetrics().slice(0, 6)} />);

    expect(screen.queryByRole("group", { name: "Quality lenses" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Task framing" })).toBeVisible();
  });

  it.each([
    {
      metricState: "not-selected" as const,
      readinessState: "unknown" as const,
      reason: "metric_not_selected" as const,
      actions: ["select_metric_for_analysis"] as const,
      valueLabel: "Not selected",
      reasonCopy:
        "The completed run explicitly did not select this metric. It was omitted by scope, not missing or failed.",
      actionCopy: "Select this metric for a new local analysis run",
    },
    {
      metricState: "unavailable" as const,
      readinessState: "unknown" as const,
      reason: "metric_scope_unknown" as const,
      actions: ["select_metric_for_analysis"] as const,
      valueLabel: "Unknown",
      reasonCopy: "This legacy run does not preserve its requested metric set",
      actionCopy: "Select this metric for a new local analysis run",
    },
    {
      metricState: "unavailable" as const,
      readinessState: "unknown" as const,
      reason: "analysis_not_run" as const,
      actions: ["run_local_analysis"] as const,
      valueLabel: "Unknown",
      reasonCopy: "No compatible local analysis has been run for this session.",
      actionCopy: "Run local analysis for this session.",
    },
    {
      metricState: "unavailable" as const,
      readinessState: "unsupported" as const,
      reason: "provider_capability_missing" as const,
      actions: ["collect_objective_verification"] as const,
      valueLabel: "Unknown",
      reasonCopy:
        "The reviewed provider projection does not expose every evidence channel this metric requires.",
      actionCopy: "Provide objective VERIFICATION evidence",
    },
    {
      metricState: "incompatible" as const,
      readinessState: "incompatible" as const,
      reason: "provider_incompatible" as const,
      actions: ["check_provider_compatibility"] as const,
      valueLabel: "Incompatible",
      reasonCopy: "The installed provider schema is incompatible with the reviewed adapter.",
      actionCopy: "Check the installed provider schema",
    },
    {
      metricState: "abstained" as const,
      readinessState: "abstained" as const,
      reason: "result_abstained" as const,
      actions: ["none"] as const,
      valueLabel: "Abstained",
      reasonCopy:
        "The analyzer deliberately declined to estimate this metric from the available evidence.",
      actionCopy: "No user action is requested for this state.",
    },
    {
      metricState: "not-applicable" as const,
      readinessState: "not_applicable" as const,
      reason: "explicitly_not_applicable" as const,
      actions: ["none"] as const,
      valueLabel: "Not applicable",
      reasonCopy:
        "The completed analysis explicitly determined that this metric does not apply to the selected window.",
      actionCopy: "No user action is requested for this state.",
    },
    {
      metricState: "execution-error" as const,
      readinessState: "failed" as const,
      reason: "result_failed" as const,
      actions: ["retry_analysis"] as const,
      valueLabel: "Failed",
      reasonCopy: "This metric failed inside an otherwise persisted analysis run.",
      actionCopy: "Retry local analysis",
    },
  ])(
    "shows $readinessState readiness reasons and actions without fabricating a value",
    ({
      metricState,
      readinessState,
      reason,
      actions,
      valueLabel,
      reasonCopy,
      actionCopy,
    }) => {
      const metric = syntheticMetric({
        key: "prompt.task_definition_coverage",
        label: "Task",
        ratio: null,
        state: metricState,
      });
      const readiness = syntheticReadiness(metric, {
        state: readinessState,
        reason_code: reason,
        next_actions: [...actions],
        missing_capabilities:
          readinessState === "unsupported" ? ["objective_verification"] : [],
      });

      render(<QualityRadar metrics={[metric]} readiness={[readiness]} />);

      const card = within(
        screen.getByRole("region", { name: "Task framing metrics" }),
      ).getByRole("button", { name: /Task full metric name/i });
      expect(card).toHaveTextContent(valueLabel);
      expect(card).not.toHaveTextContent("Not available");
      expect(card).toHaveTextContent("Needed / next:");
      expect(card.querySelector("[data-readiness-state]")).toHaveAttribute(
        "data-readiness-state",
        readinessState,
      );

      const inspector = screen.getByRole("complementary");
      expect(inspector).toHaveTextContent(reasonCopy);
      expect(inspector).toHaveTextContent(actionCopy);
      expect(inspector).toHaveTextContent("No value");
    },
  );

  it("keeps a partial numeric estimate while disclosing excluded scope omissions", () => {
    const metric = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: 0.5,
      state: "partial",
    });
    metric.notSelectedRuns = 1;

    render(<QualityRadar metrics={[metric]} />);

    const card = screen.getByRole("button", { name: /Task full metric name/i });
    expect(card).toHaveTextContent("50%");
    expect(card).toHaveTextContent(
      "1 run omitted by selected scope; not missing or failed",
    );
    expect(screen.getByRole("complementary")).toHaveTextContent(
      "1 completed run; excluded, not failed",
    );
  });

  it("shows legacy unknown-scope counts as unknown rather than failed", () => {
    const metric = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: null,
      state: "unavailable",
    });
    metric.unknownScopeRuns = 2;

    render(<QualityRadar metrics={[metric]} />);

    const card = screen.getByRole("button", { name: /Task full metric name/i });
    expect(card).toHaveTextContent("Unknown");
    expect(card).toHaveTextContent(
      "2 legacy runs without a metric-scope receipt; not classified as failed",
    );
    expect(screen.getByRole("complementary")).toHaveTextContent(
      "2 completed runs; absence is not classified as failed",
    );
    expect(screen.getByLabelText("Selected lens availability")).toHaveTextContent(
      "1 unknown",
    );
    expect(screen.getByLabelText("Selected lens availability")).not.toHaveTextContent(
      "failed",
    );
  });

  it("keeps the persisted value authoritative when readiness metadata conflicts", () => {
    const metric = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: 0.8,
    });
    const readiness = syntheticReadiness(metric, {
      state: "incompatible",
      reason_code: "provider_incompatible",
      next_actions: ["check_provider_compatibility"],
    });

    render(<QualityRadar metrics={[metric]} readiness={[readiness]} />);

    const card = screen.getByRole("button", { name: /Task full metric name/i });
    expect(card).toHaveTextContent("80%");
    expect(card).toHaveTextContent("Readiness metadata mismatch");
    expect(screen.getByLabelText("Compatible exact-value bars")).toHaveTextContent("80%");
  });

  it("shows exact known readiness and its no-action receipt without changing the value", () => {
    const metric = syntheticMetric({
      key: "prompt.task_definition_coverage",
      label: "Task",
      ratio: 0.8,
    });
    const readiness = syntheticReadiness(metric, {
      state: "known",
      reason_code: "measured",
      next_actions: ["none"],
    });

    render(<QualityRadar metrics={[metric]} readiness={[readiness]} />);

    const card = screen.getByRole("button", { name: /Task full metric name/i });
    expect(card).toHaveTextContent("80%");
    expect(card).toHaveTextContent("Stored value is authoritative");
    expect(card).toHaveTextContent("No action needed");
    expect(screen.getByRole("complementary")).toHaveTextContent(
      "No user action is requested for this state",
    );
  });
});
