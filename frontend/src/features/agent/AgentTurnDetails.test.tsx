import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentTurnDetails } from "./AgentTurnDetails";
import { exampleAgentTurn, exampleTokenUsage, exampleWriteReceipt } from "./agentTurnFixtures.test-support";

describe("AgentTurnDetails", () => {
  it("keeps details compact and expands truthful runtime and write receipts", () => {
    const summary = exampleAgentTurn();
    const open = vi.fn();
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} onOpenFile={open} />);
    const toggle = screen.getByLabelText("Turn 1 details");
    const details = toggle.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveAttribute("id", `agent-turn-${summary.turn_id}`);
    expect(details).toHaveAttribute("tabindex", "-1");
    expect(toggle).toHaveTextContent("Response complete");
    expect(toggle).toHaveTextContent("18 reported tokens · 1 reviewed path");
    fireEvent.click(toggle);
    expect(screen.getByText(/not verification that the task succeeded/u)).toBeVisible();
    const stats = screen.getByLabelText("Turn telemetry");
    expect(within(stats).getByText("18")).toBeVisible();
    expect(within(stats).getByText("200 ms")).toBeVisible();
    expect(screen.getByText(/Complete counters: 1\/1 requests/u)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open example.txt in workspace" }));
    expect(open).toHaveBeenCalledExactlyOnceWith("example.txt");
    expect(screen.getByText(/\+2 \/ −1 lines/u)).toBeVisible();
    expect(screen.getByText(/historical reviewed-write receipt/u)).toBeVisible();
  });

  it.each(["unavailable", "invalid", "partial"] as const)("never presents missing %s counters as zero", (state) => {
    const summary = exampleAgentTurn({ usage: exampleTokenUsage({ state, reported_requests: 0, prompt_tokens: null, completion_tokens: null, total_tokens: null }),
      duration_ms: null, model_wait_ms: null, time_to_first_text_ms: null });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} />);
    fireEvent.click(screen.getByLabelText("Turn 1 details"));
    expect(screen.getAllByText("Not reported")).toHaveLength(5);
    expect(within(screen.getByLabelText("Turn telemetry")).getAllByText("Not measured")).toHaveLength(3);
    expect(screen.queryByText("0 reported tokens")).not.toBeInTheDocument();
    if (state === "invalid") expect(screen.getByText(/No turn token total is available/u)).toBeVisible();
  });

  it("makes the absence of a reviewed file output visible without expanding the receipt", () => {
    const summary = exampleAgentTurn({ writes: [], tools_requested: 0, tools_succeeded: 0 });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} />);

    const toggle = screen.getByLabelText("Turn 1 details");
    expect(toggle).toHaveTextContent("no reviewed file writes");
    fireEvent.click(toggle);
    expect(screen.getByText(/Model text alone is not evidence that a file or document was created/u)).toBeVisible();
  });

  it("displays genuine zero counts and unchanged file receipts", () => {
    const summary = exampleAgentTurn({ usage: exampleTokenUsage({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }),
      writes: [exampleWriteReceipt({ operation: "unchanged", after_sha256: "c".repeat(64), added_lines: 0, removed_lines: 0 })] });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} />);
    expect(screen.getByLabelText("Turn 1 details")).toHaveTextContent("no file content changes");
    fireEvent.click(screen.getByLabelText("Turn 1 details"));
    expect(screen.getByText(/0 reported tokens/u)).toBeVisible();
    expect(screen.getByText("Content unchanged")).toBeVisible();
    expect(screen.getByText(/\+0 \/ −0 lines/u)).toBeVisible();
    expect(screen.queryByText(/file written/u)).not.toBeInTheDocument();
  });

  it("separates unverified writes and untracked command effects from success", () => {
    const summary = exampleAgentTurn({ status: "stopped", reason: "stop_requested", tools_requested: 2, tools_succeeded: 0, tools_unverified: 1, tools_cancelled: 1, untracked_command_calls: 1,
      writes: [exampleWriteReceipt({ state: "unverified", operation: null, after_sha256: null, added_lines: null, removed_lines: null, byte_size: null })] });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} onOpenFile={vi.fn()} fileActionsDisabled />);
    fireEvent.click(screen.getByLabelText("Turn 1 details"));
    expect(screen.getByText("Effect unverified")).toBeVisible();
    expect(screen.getByText(/Inspect the current file before retrying/u)).toBeVisible();
    expect(screen.getByText("1 command attempt: file effects are not inventoried.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open example.txt in workspace" })).toBeDisabled();
    expect(screen.getByLabelText("Turn 1 details")).toHaveTextContent("1 unverified write");
    expect(screen.queryByText(/file changed/u)).not.toBeInTheDocument();
  });

  it("does not render a receipt for another turn", () => {
    render(<AgentTurnDetails summary={exampleAgentTurn()} turnId={"f".repeat(32)} />);
    expect(screen.getByRole("status")).toHaveTextContent("Turn details could not be verified.");
    expect(screen.queryByLabelText("Turn telemetry")).not.toBeInTheDocument();
  });

  it.each([
    ["completed", "answer_complete", "Regenerate in branch", "regenerate"],
    ["failed", "turn_failed", "Retry in branch", "retry"],
  ] as const)("offers history-preserving edit and %s revision actions", (status, reason, automaticLabel, automaticMode) => {
    const revise = vi.fn();
    const summary = exampleAgentTurn({ status, reason });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} onRevise={revise} />);

    fireEvent.click(screen.getByLabelText("Turn 1 details"));
    const actions = screen.getByLabelText("Turn 1 revision actions");
    expect(actions).toHaveTextContent(/source chat and existing workspace effects are not rewritten or rolled back/u);
    fireEvent.click(within(actions).getByRole("button", { name: "Edit in branch" }));
    fireEvent.click(within(actions).getByRole("button", { name: automaticLabel }));
    expect(revise.mock.calls).toEqual([["edit"], [automaticMode]]);
  });

  it("never offers an automatic retry that would silently drop attachments", () => {
    const revise = vi.fn();
    const summary = exampleAgentTurn({ status: "failed", reason: "turn_failed" });
    render(<AgentTurnDetails summary={summary} turnId={summary.turn_id} onRevise={revise} sourceHasAttachments />);

    fireEvent.click(screen.getByLabelText("Turn 1 details"));
    const actions = screen.getByLabelText("Turn 1 revision actions");
    expect(within(actions).getByRole("button", { name: "Retry in branch" })).toBeDisabled();
    expect(actions).toHaveTextContent(/attachments are never copied into a branch/u);
    fireEvent.click(within(actions).getByRole("button", { name: "Edit in branch" }));
    expect(revise).toHaveBeenCalledExactlyOnceWith("edit");
  });
});
