import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "../../shared/api/contracts";
import { AgentSessionEffects } from "./AgentSessionEffects";
import { exampleAgentTurn, exampleWriteReceipt } from "./agentTurnFixtures.test-support";

const AT = "2040-01-01T00:00:00Z";

function event(seq: number, kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return {
    seq, at: AT, kind, attachments: [], text: null, tool: null, arguments: null, call_id: null,
    approval_id: null, ok: null, preview: null, ...extra,
  };
}

describe("AgentSessionEffects", () => {
  it("groups repeated reviewed receipts without claiming they are a net diff", () => {
    const first = exampleAgentTurn({
      turn_id: "1".repeat(32), turn_number: 1,
      tools_requested: 2, tools_succeeded: 2, untracked_command_calls: 1,
      writes: [exampleWriteReceipt({ path: "example.ts", operation: "modified" })],
    });
    const second = exampleAgentTurn({
      turn_id: "2".repeat(32), turn_number: 2,
      tools_requested: 1, tools_succeeded: 1,
      writes: [exampleWriteReceipt({
        path: "example.ts", operation: "unchanged", before_sha256: "d".repeat(64),
        after_sha256: "d".repeat(64), added_lines: 0, removed_lines: 0,
      })],
    });
    const open = vi.fn();
    render(<AgentSessionEffects
      events={[
        event(1, "done", { turn_id: first.turn_id, turn_summary: first }),
        event(2, "done", { turn_id: second.turn_id, turn_summary: second }),
      ]}
      fileActionsDisabled={false}
      historyGap={false}
      onOpenFile={open}
      running={false}
      turnCount={2}
    />);

    const toggle = screen.getByLabelText("Session activity and write receipts");
    expect(toggle).toHaveTextContent("3 observed actions");
    expect(toggle).toHaveTextContent("2 reviewed writes");
    expect(toggle).toHaveTextContent("1 reviewed path");
    fireEvent.click(toggle);
    expect(screen.getAllByText("Complete retained session history")).toHaveLength(2);
    expect(screen.getByText(/2 reviewed receipts · latest content unchanged/u)).toBeVisible();
    expect(screen.getByText(/1 command attempt may have file effects that are not inventoried/u)).toBeVisible();
    expect(screen.getByText(/historical activity, not current file state/u)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open example.ts from session effects" }));
    expect(open).toHaveBeenCalledExactlyOnceWith("example.ts");
  });

  it("labels expired history and unverified writes as partial instead of complete", () => {
    const summary = exampleAgentTurn({
      turn_id: "3".repeat(32), turn_number: 3,
      tools_requested: 1, tools_succeeded: 0, tools_unverified: 1,
      writes: [exampleWriteReceipt({
        path: "uncertain.ts", state: "unverified", operation: null,
        after_sha256: null, added_lines: null, removed_lines: null, byte_size: null,
      })],
    });
    render(<AgentSessionEffects
      events={[event(10, "done", { turn_id: summary.turn_id, turn_summary: summary })]}
      fileActionsDisabled
      historyGap
      onOpenFile={vi.fn()}
      running={false}
      turnCount={3}
    />);

    fireEvent.click(screen.getByLabelText("Session activity and write receipts"));
    expect(screen.getAllByText("Partial retained history")).toHaveLength(2);
    expect(screen.getByText(/Earlier in-memory events expired/u)).toBeVisible();
    expect(screen.getAllByText(/1 unverified write/u)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Open uncertain.ts from session effects" })).toBeDisabled();
    expect(screen.queryAllByText("Complete retained session history")).toHaveLength(0);
  });

  it("distinguishes an active unsummarized action from a complete zero-write history", () => {
    const { rerender } = render(<AgentSessionEffects
      events={[event(1, "tool_call", { turn_id: "4".repeat(32), tool: "read_file", call_id: "example-read" })]}
      fileActionsDisabled={false}
      historyGap={false}
      running
      turnCount={1}
    />);
    fireEvent.click(screen.getByLabelText("Session activity and write receipts"));
    expect(screen.getAllByText("Current turn not summarized yet")).toHaveLength(2);
    expect(screen.getByLabelText("Session activity and write receipts")).toHaveTextContent("1 observed action");

    const summary = exampleAgentTurn({
      turn_id: "5".repeat(32), turn_number: 1,
      tools_requested: 0, tools_succeeded: 0, writes: [],
    });
    rerender(<AgentSessionEffects
      events={[event(2, "done", { turn_id: summary.turn_id, turn_summary: summary })]}
      fileActionsDisabled={false}
      historyGap={false}
      running={false}
      turnCount={1}
    />);
    expect(screen.getAllByText("Complete retained session history")).toHaveLength(2);
    expect(screen.getByText(/No direct reviewed file writes were recorded/u)).toBeVisible();
  });

  it("rejects conflicting turn numbers and lists a repeated same-turn path once", () => {
    const first = exampleAgentTurn({
      turn_id: "6".repeat(32), turn_number: 1,
      tools_requested: 2, tools_succeeded: 2,
      writes: [
        exampleWriteReceipt({ path: "repeated.ts", operation: "modified" }),
        exampleWriteReceipt({ path: "repeated.ts", operation: "modified" }),
      ],
    });
    const conflicting = exampleAgentTurn({
      turn_id: "7".repeat(32), turn_number: 1,
      tools_requested: 0, tools_succeeded: 0, writes: [],
    });
    render(<AgentSessionEffects
      events={[
        event(1, "done", { turn_id: first.turn_id, turn_summary: first }),
        event(2, "done", { turn_id: conflicting.turn_id, turn_summary: conflicting }),
      ]}
      fileActionsDisabled={false}
      historyGap={false}
      running={false}
      turnCount={2}
    />);

    fireEvent.click(screen.getByLabelText("Session activity and write receipts"));
    expect(screen.getAllByText("Partial retained history")).toHaveLength(2);
    expect(screen.getByText(/Retained turn summaries conflict/u)).toBeVisible();
    expect(screen.getByText("Observed in turn 1")).toBeVisible();
    expect(screen.queryByText("Observed in turns 1, 1")).not.toBeInTheDocument();
  });

  it("does not present a reverted reviewed path as a current file change", () => {
    const changed = exampleAgentTurn({
      turn_id: "8".repeat(32), turn_number: 1,
      tools_requested: 1, tools_succeeded: 1,
      writes: [exampleWriteReceipt({
        path: "reverted.ts", operation: "modified", before_sha256: "c".repeat(64),
        after_sha256: "d".repeat(64),
      })],
    });
    const reverted = exampleAgentTurn({
      turn_id: "9".repeat(32), turn_number: 2,
      tools_requested: 1, tools_succeeded: 1,
      writes: [exampleWriteReceipt({
        path: "reverted.ts", operation: "modified", before_sha256: "d".repeat(64),
        after_sha256: "c".repeat(64),
      })],
    });
    render(<AgentSessionEffects
      events={[
        event(1, "done", { turn_id: changed.turn_id, turn_summary: changed }),
        event(2, "done", { turn_id: reverted.turn_id, turn_summary: reverted }),
      ]}
      fileActionsDisabled={false}
      historyGap={false}
      running={false}
      turnCount={2}
    />);

    const toggle = screen.getByLabelText("Session activity and write receipts");
    expect(toggle).toHaveTextContent("1 reviewed path");
    expect(toggle).not.toHaveTextContent("file changed");
  });

  it("pages a maximum-size reviewed-path summary without losing exact totals", () => {
    const events = Array.from({ length: 120 }, (_, index) => {
      const turn = exampleAgentTurn({
        turn_id: (index + 1).toString(16).padStart(32, "0"),
        turn_number: index + 1,
        tools_requested: 1,
        tools_succeeded: 1,
        writes: [exampleWriteReceipt({ path: `src/example-${index.toString().padStart(3, "0")}.ts` })],
      });
      return event(index + 1, "done", { turn_id: turn.turn_id, turn_summary: turn });
    });
    render(<AgentSessionEffects
      events={events}
      fileActionsDisabled={false}
      historyGap={false}
      running={false}
      scopeKey="synthetic-large-session"
      turnCount={events.length}
    />);

    fireEvent.click(screen.getByLabelText("Session activity and write receipts"));
    expect(screen.getByLabelText("Session activity and write receipts")).toHaveTextContent("120 reviewed paths");
    expect(screen.getAllByRole("listitem")).toHaveLength(50);
    expect(screen.getByText("Showing 1–50 of 120")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.getByText("Showing 51–100 of 120")).toBeVisible();
    expect(screen.queryByText("src/example-000.ts")).not.toBeInTheDocument();
    expect(screen.getByText("src/example-050.ts")).toBeVisible();
  });
});
