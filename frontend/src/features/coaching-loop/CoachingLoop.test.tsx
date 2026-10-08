import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CoachingLoop } from "./CoachingLoop";
import coachingLoopCss from "./CoachingLoop.css?raw";
import {
  createContentFreeShareSummary,
  type CoachingLoopViewModel,
} from "./coachingLoopModel";

function syntheticModel(): CoachingLoopViewModel {
  return {
    assessment: {
      calibration: "candidate-unvalidated",
      taskType: "implementation",
      evidenceTier: "objective",
      methodCode: "workflow-comparison-v1",
    },
    outcome: {
      status: "verified",
      basis: "objective",
      evidenceCode: "automated-and-acceptance",
    },
    strength: {
      state: "available",
      category: "task-framing",
      basis: "observed-text",
    },
    friction: {
      state: "available",
      category: "acceptance-criteria",
      basis: "mixed",
    },
    nextExperiment: {
      state: "available",
      category: "acceptance-criteria",
    },
    improvedPrompt: {
      state: "available",
      templateCode: "acceptance-first",
    },
    evidence: {
      state: "partial",
      minimumRatio: 2 / 3,
      candidateCount: 2,
    },
    details: {
      limitationCode: "single-task-candidate",
      provenanceCode: "synthetic-local-v1",
    },
    sharing: { status: "blocked", reasonCode: "uncalibrated" },
  };
}

function calibratedModel(): CoachingLoopViewModel {
  const model = syntheticModel();
  model.assessment.calibration = "human-calibrated";
  model.assessment.methodCode = "human-rubric-v1";
  model.sharing = { status: "content-free" };
  return model;
}

describe("CoachingLoop", () => {
  it("presents one compact zero-configuration coaching deck with closed copy", () => {
    const { container } = render(<CoachingLoop model={syntheticModel()} />);

    expect(screen.getByRole("heading", { name: "Make the next task easier" })).toBeVisible();
    expect(screen.getByText("Verification passed")).toBeVisible();
    expect(screen.getByText("Candidate · unvalidated")).toBeVisible();
    expect(screen.getByText("Task: Implementation")).toBeVisible();
    expect(screen.getAllByText("Objective evidence").length).toBeGreaterThan(0);
    expect(screen.getByText("Method: Workflow comparison v1")).toBeVisible();
    const priorities = screen.getByLabelText("Coaching priorities");
    expect(within(priorities).getAllByRole("article")).toHaveLength(3);
    expect(within(priorities).getByText("Task-framing signals were present")).toBeVisible();
    expect(within(priorities).getByText("Acceptance timing needs review")).toBeVisible();
    expect(within(priorities).getByText("Put one acceptance check first")).toBeVisible();
    expect(within(priorities).getByText("Watch for:")).toBeVisible();
    expect(
      within(priorities).getByText(/leaving other accepted requirements uncovered/i),
    ).toBeVisible();
    expect(screen.getByText("Template to try")).toBeVisible();
    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(container.querySelector("select")).not.toBeInTheDocument();
    expect(container.querySelector('input[type="checkbox"]')).not.toBeInTheDocument();
    expect(container.querySelectorAll("details")).toHaveLength(1);
    expect(screen.queryByText(/overall score/i)).not.toBeInTheDocument();
    expect(screen.getByText(/not intelligence, personality, or developer rank/i)).toBeVisible();
  });

  it("makes a blocked-share reason visible and keeps its aria-disabled control focusable", () => {
    render(<CoachingLoop model={syntheticModel()} onShareSummary={vi.fn()} />);

    const share = screen.getByRole("button", { name: "Review safe share" });
    const status = screen.getByText(/sharing is blocked because these coaching candidates are not calibrated/i);
    expect(share).toHaveAttribute("aria-disabled", "true");
    expect(share).toHaveAttribute("aria-describedby", status.id);
    share.focus();
    expect(share).toHaveFocus();
    fireEvent.click(share);
    expect(screen.queryByLabelText("Exact content-free share payload")).not.toBeInTheDocument();
  });

  it("keeps unknown, abstained, and not-applicable distinct with stable headings", () => {
    const model = syntheticModel();
    model.outcome = {
      status: "unknown",
      basis: "none",
      reasonCode: "evidence-missing",
    };
    model.strength = {
      state: "unknown",
      category: null,
      reasonCode: "insufficient-coverage",
    };
    model.friction = {
      state: "abstained",
      category: null,
      reasonCode: "method-abstained",
    };
    model.nextExperiment = {
      state: "not-applicable",
      category: null,
      reasonCode: "not-applicable-task",
    };
    model.improvedPrompt = {
      state: "not-applicable",
      reasonCode: "not-applicable-task",
    };
    model.evidence = {
      state: "abstained",
      reasonCode: "method-abstained",
    };

    const { container } = render(<CoachingLoop model={model} />);

    expect(screen.getByRole("heading", { name: "No practice candidate available" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "No review candidate available" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "No experiment available" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Template to try" })).toBeVisible();
    expect(container.querySelectorAll(".coaching-loop__unavailable--unknown")).toHaveLength(2);
    expect(container.querySelectorAll(".coaching-loop__unavailable--abstained")).toHaveLength(1);
    expect(container.querySelectorAll(".coaching-loop__unavailable--not-applicable")).toHaveLength(2);
    expect(screen.getAllByRole("note").every((note) => note.hasAttribute("aria-label"))).toBe(true);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Evidence & method"));
    expect(screen.getAllByText(/method declined to produce this observation/i).length).toBeGreaterThan(0);
  });

  it("previews the exact closed payload and returns focus after confirmed sharing", async () => {
    const onShare = vi.fn();
    const model = calibratedModel();
    const expected = createContentFreeShareSummary(model);
    render(<CoachingLoop model={model} onShareSummary={onShare} />);

    const share = screen.getByRole("button", { name: "Review safe share" });
    fireEvent.click(share);

    const panel = screen.getByLabelText("Exact content-free share payload").closest("div[id='coaching-share-review']");
    const payload = screen.getByLabelText("Exact content-free share payload");
    expect(panel).toHaveFocus();
    expect(payload.textContent).toBe(JSON.stringify(expected, null, 2));
    expect(screen.getByText(/no prompt text, evidence, counts, IDs, paths, or provenance/i)).toBeVisible();
    expect(onShare).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Share this exact payload" }));
    expect(onShare).toHaveBeenCalledWith(expected);
    await waitFor(() => expect(share).toHaveFocus());
  });

  it("closes a stale share preview and returns focus when the model changes", async () => {
    const onShare = vi.fn();
    const initial = calibratedModel();
    const { rerender } = render(
      <CoachingLoop model={initial} onShareSummary={onShare} />,
    );
    const share = screen.getByRole("button", { name: "Review safe share" });
    fireEvent.click(share);
    expect(screen.getByLabelText("Exact content-free share payload")).toBeVisible();

    const changed = structuredClone(initial);
    changed.assessment.taskType = "review";
    rerender(<CoachingLoop model={changed} onShareSummary={onShare} />);

    await waitFor(() => {
      expect(screen.queryByLabelText("Exact content-free share payload")).not.toBeInTheDocument();
      expect(share).toHaveFocus();
    });
    expect(onShare).not.toHaveBeenCalled();
  });

  it("keeps the static template reachable through a named keyboard action", () => {
    const onCopy = vi.fn();
    render(
      <CoachingLoop
        model={syntheticModel()}
        onCopyImprovedPrompt={onCopy}
      />,
    );

    const template = screen.getByLabelText("Prompt template text");
    const copy = screen.getByRole("button", { name: "Copy template" });
    expect(template).toHaveTextContent("[observable behavior]");
    copy.focus();
    expect(copy).toHaveFocus();
    fireEvent.click(copy);
    expect(onCopy).toHaveBeenCalledWith(template.textContent);
  });

  it("builds only a closed content-free projection and blocks candidate exports", () => {
    const candidate = syntheticModel();
    candidate.sharing = { status: "content-free" };
    expect(createContentFreeShareSummary(candidate)).toBeNull();

    const calibrated = calibratedModel();
    expect(createContentFreeShareSummary(calibrated)).toEqual({
      schema: "coaching-loop-share.v1",
      outcome: "verified",
      outcomeBasis: "objective",
      strengthCategory: "task-framing",
      frictionCategory: "acceptance-criteria",
      experimentCategory: "acceptance-criteria",
      evidenceState: "partial",
      calibration: "human-calibrated",
      boundary: "observed-workflow-signals-not-person-score",
    });
  });

  it("labels human acceptance separately from executable verification", () => {
    const model = syntheticModel();
    model.outcome = {
      status: "verified",
      basis: "human-reviewed",
      evidenceCode: "human-review",
    };

    render(<CoachingLoop model={model} />);

    expect(screen.getByText("Accepted by reviewer")).toBeVisible();
    expect(screen.getByText("Reviewer decision")).toBeVisible();
    expect(screen.queryByText("Verification passed")).not.toBeInTheDocument();
  });

  it("wraps mid-width and mobile layouts without clipping the template", () => {
    expect(coachingLoopCss).toContain("@media (max-width: 960px)");
    expect(coachingLoopCss).toContain("@media (max-width: 720px)");
    expect(coachingLoopCss).toMatch(
      /@media \(max-width: 960px\)[\s\S]*\.coaching-loop__cards[\s\S]*grid-template-columns: repeat\(2/,
    );
    expect(coachingLoopCss).toMatch(
      /@media \(max-width: 720px\)[\s\S]*\.coaching-loop__cards,[\s\S]*grid-template-columns: 1fr/,
    );
    const promptRule = coachingLoopCss.match(/\.coaching-loop__prompt pre \{([^}]*)\}/)?.[1] ?? "";
    expect(promptRule).not.toContain("max-height");
    expect(promptRule).not.toContain("overflow: auto");
    expect(promptRule).toContain("overflow-wrap: anywhere");
    expect(coachingLoopCss).toContain("font-size: 0.76rem");
  });
});
