import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SYNTHETIC_CANDIDATES } from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { CandidateReviewPanel } from "./CandidateReviewPanel";

describe("CandidateReviewPanel", () => {
  it("exposes evidence, content protection, and an accessible accept action", async () => {
    const onReviewed = vi.fn();
    render(
      <CandidateReviewPanel
        item={SYNTHETIC_CANDIDATES[0]}
        onReviewed={onReviewed}
        transport={createSyntheticTransport()}
      />,
    );

    expect(screen.getByRole("heading", { name: /Candidate aaaaaa/ })).toBeVisible();
    expect(screen.getByText("Content hidden")).toBeVisible();
    expect(screen.getAllByText("Supports grouping")).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("Task category"), {
      target: { value: "feature_implementation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Accept as one task" }));

    await waitFor(() => expect(onReviewed).toHaveBeenCalledOnce());
    expect(onReviewed.mock.calls[0][0]).toMatchObject({
      action: "accept",
      applied: true,
    });
  });

  it("keeps missing signal evidence explicitly unknown", () => {
    render(
      <CandidateReviewPanel
        item={SYNTHETIC_CANDIDATES[1]}
        onReviewed={vi.fn()}
        transport={createSyntheticTransport()}
      />,
    );

    expect(screen.getByText("Unknown evidence")).toBeVisible();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("meter", { name: "0 of 2 observations (0%)" }),
    ).toHaveLength(2);
  });
});
