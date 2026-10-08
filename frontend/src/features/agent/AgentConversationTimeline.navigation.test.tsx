import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { AgentEvent } from "../../shared/api/contracts";
import { TranscriptEventRows } from "./AgentConversationTimeline";
import { exampleAgentTurn } from "./agentTurnFixtures.test-support";
import "../../styles.css";

function event(seq: number, kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return {
    at: "2040-01-01T00:00:00Z",
    attachments: [],
    kind,
    seq,
    text: null,
    ...extra,
  };
}

function renderTimeline(events: AgentEvent[], props: Partial<ComponentProps<typeof TranscriptEventRows>> = {}) {
  return render(<TranscriptEventRows
    events={events}
    fileActionsDisabled={false}
    onOpenFile={vi.fn()}
    reasoningEnabled={false}
    {...props}
  />);
}

function openFind(): HTMLInputElement {
  fireEvent.click(screen.getByText("Find in conversation", { exact: true, selector: "summary" }));
  return screen.getByRole("searchbox", { name: "Find in conversation" });
}

function pagedEventsWithOneSearchableMessage(count = 401): AgentEvent[] {
  return Array.from({ length: count }, (_, index) => event(index + 1, index === 1 ? "user" : "status", {
    text: `Synthetic activity ${index + 1}`,
  }));
}

async function nextFrame(): Promise<void> {
  await new Promise((resolve) => requestAnimationFrame(resolve));
}

describe("TranscriptEventRows local conversation navigation", () => {
  it("offers a revision action for an attachment-only source turn", async () => {
    const turnId = "a".repeat(32);
    const onReviseTurn = vi.fn();
    const attachment = {
      contract_version: "agent-attachment.v2" as const,
      attachment_id: "d".repeat(32),
      display_name: "example-diagram.png",
      kind: "image" as const,
      media_type: "image/png" as const,
      byte_size: 68,
      sha256: "e".repeat(64),
      width: 1,
      height: 1,
      duration_ms: null,
      sample_rate_hz: null,
      channels: null,
      routing: "native_multimodal" as const,
      document_format: null,
      projected_characters: null,
      projection_truncated: null,
      omitted_features: [],
      context_tokens: null,
      context_cost_source: "runtime_unreported" as const,
    };
    renderTimeline([
      event(1, "user", { text: null, attachments: [attachment], turn_id: turnId }),
      event(2, "done", { turn_id: turnId, turn_summary: exampleAgentTurn({ turn_id: turnId }) }),
    ], { onReviseTurn });

    fireEvent.click(await screen.findByLabelText("Turn 1 details"));
    fireEvent.click(screen.getByRole("button", { name: "Prepare regeneration with attachments" }));
    expect(onReviseTurn).toHaveBeenCalledExactlyOnceWith(turnId, "regenerate");
  });

  it("finds literal Unicode text in loaded user and stopped assistant messages, excluding other activity", async () => {
    renderTimeline([
      event(1, "user", { text: "İx [a-z]+ request" }),
      event(2, "assistant", { stream_status: "stopped", text: "Stopped [a-z]+ reply" }),
      event(3, "tool_result", { text: "[a-z]+ tool output", tool: "read_file", ok: true }),
      event(4, "status", { text: "[a-z]+ status" }),
      event(5, "assistant_delta", { stream_id: "d".repeat(32), text: "[a-z]+ stream delta" }),
      event(6, "assistant", { reasoning: "[a-z]+ reasoning", text: "No matching assistant words" }),
    ]);
    const find = openFind();
    expect(screen.getByText("Searches loaded user and assistant message text only; tool output and reasoning are excluded.")).toBeVisible();
    fireEvent.change(find, { target: { value: "[a-z]+" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Message 1 of 2 selected."));
    fireEvent.keyDown(find, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Message 2 of 2 selected."));
    fireEvent.keyDown(find, { key: "Enter", shiftKey: true });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Message 1 of 2 selected."));

    fireEvent.change(find, { target: { value: "İx" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Message 1 of 1 selected."));
  });

  it("reports empty and no-match searches and clears the local query", async () => {
    renderTimeline([event(1, "user", { text: "Synthetic loaded message" })]);
    const find = openFind();
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Enter text to find in the loaded messages.");
    fireEvent.change(find, { target: { value: "no-such-synthetic-message" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    expect(await screen.findByRole("status")).toHaveTextContent("No loaded user or assistant messages match this text.");
    fireEvent.click(screen.getByRole("button", { name: "Clear find" }));
    expect(find).toHaveValue("");
  });

  it("clears a stale selection when loaded text changes and does not focus steal across a chat-key reset", async () => {
    const first = [event(1, "user", { text: "Synthetic selected message" })];
    const second = [event(1, "user", { text: "Replacement loaded message" })];
    const { rerender } = render(<>
      <button type="button">Outside focus</button>
      <TranscriptEventRows events={first} fileActionsDisabled={false} onOpenFile={vi.fn()} reasoningEnabled={false} />
    </>);
    const outside = screen.getByRole("button", { name: "Outside focus" });
    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Message 1 of 1 selected.");

    rerender(<>
      <button type="button">Outside focus</button>
      <TranscriptEventRows events={second} fileActionsDisabled={false} onOpenFile={vi.fn()} reasoningEnabled={false} />
    </>);
    expect(screen.getByRole("status")).not.toHaveTextContent("Message 1 of 1 selected.");
    outside.focus();
    rerender(<>
      <button type="button">Outside focus</button>
      <TranscriptEventRows key="replacement-chat" events={second} fileActionsDisabled={false} onOpenFile={vi.fn()} reasoningEnabled={false} />
    </>);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(outside).toHaveFocus();
    expect(screen.getByText("Find in conversation", { exact: true, selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  });

  it("restores the latest transcript window and reports it only after the latest page is mounted", async () => {
    const events = Array.from({ length: 401 }, (_, index) => event(index + 1, "status", { text: `Synthetic activity ${index + 1}` }));
    const onLatestRendered = vi.fn();
    const onPageStateChange = vi.fn();
    const { rerender } = renderTimeline(events, { latestRequest: 0, onLatestRendered, onPageStateChange });
    await screen.findByText("Synthetic activity 401");
    fireEvent.click(screen.getByRole("button", { name: "Earlier 200" }));
    expect(await screen.findByText("Synthetic activity 201")).toBeVisible();
    expect(screen.queryByText("Synthetic activity 401")).not.toBeInTheDocument();

    rerender(<TranscriptEventRows
      events={events}
      fileActionsDisabled={false}
      latestRequest={1}
      onLatestRendered={onLatestRendered}
      onOpenFile={vi.fn()}
      onPageStateChange={onPageStateChange}
      reasoningEnabled={false}
    />);
    expect(await screen.findByText("Synthetic activity 401")).toBeVisible();
    await waitFor(() => expect(onLatestRendered).toHaveBeenCalledExactlyOnceWith(1));
    expect(onPageStateChange).toHaveBeenLastCalledWith({ atLatest: true, browsingOlder: false });
  });

  it("lets an explicit latest request win over a queued local-find focus", async () => {
    const events = pagedEventsWithOneSearchableMessage();
    const { rerender } = renderTimeline(events, { latestRequest: 0 });
    await screen.findByText("Synthetic activity 401");
    fireEvent.click(screen.getByRole("button", { name: "Earlier 200" }));
    const oldMatchRow = screen.getByText("Synthetic activity 2").closest('[tabindex="-1"]') as HTMLDivElement;
    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic activity 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    rerender(<TranscriptEventRows
      events={events}
      fileActionsDisabled={false}
      latestRequest={1}
      onOpenFile={vi.fn()}
      reasoningEnabled={false}
    />);

    expect(await screen.findByText("Synthetic activity 401")).toBeVisible();
    await nextFrame();
    expect(oldMatchRow).not.toHaveFocus();
  });

  it("does not restore a local-find focus after manual Earlier or Later navigation", async () => {
    const events = pagedEventsWithOneSearchableMessage();
    renderTimeline(events);
    await screen.findByText("Synthetic activity 401");
    fireEvent.click(screen.getByRole("button", { name: "Earlier 200" }));
    const oldMatchRow = screen.getByText("Synthetic activity 2").closest('[tabindex="-1"]') as HTMLDivElement;
    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic activity 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    fireEvent.click(screen.getByRole("button", { name: "Later" }));

    expect(await screen.findByText("Synthetic activity 202")).toBeVisible();
    await nextFrame();
    expect(oldMatchRow).not.toHaveFocus();
  });

  it("honors a new external event-focus request even when its request id matches local navigation", async () => {
    const events = [
      event(1, "user", { text: "Synthetic local message" }),
      event(2, "assistant", { text: "Synthetic externally focused reply" }),
    ];
    const { rerender } = renderTimeline(events);
    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic local" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Synthetic local message"));

    rerender(<TranscriptEventRows
      events={events}
      fileActionsDisabled={false}
      focusEventRequest={{ requestId: 1, eventSeq: 2 }}
      onOpenFile={vi.fn()}
      reasoningEnabled={false}
    />);
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Synthetic externally focused reply"));
  });

  it("does not repeat a prior local-find focus when new events keep the current page selected", async () => {
    const first = [event(1, "user", { text: "Synthetic retained message" })];
    const { rerender } = render(<>
      <button type="button">Synthetic outside focus</button>
      <TranscriptEventRows events={first} fileActionsDisabled={false} onOpenFile={vi.fn()} reasoningEnabled={false} />
    </>);
    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic retained" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Synthetic retained message"));
    const outside = screen.getByRole("button", { name: "Synthetic outside focus" });
    outside.focus();

    rerender(<>
      <button type="button">Synthetic outside focus</button>
      <TranscriptEventRows
        events={[...first, event(2, "assistant", { text: "Synthetic appended reply" })]}
        fileActionsDisabled={false}
        onOpenFile={vi.fn()}
        reasoningEnabled={false}
      />
    </>);
    await nextFrame();
    expect(outside).toHaveFocus();
  });

  it("does not let a persistent artifact turn focus recapture focus after a local find", async () => {
    const summary = exampleAgentTurn({ turn_id: "e".repeat(32) });
    const events = [
      event(1, "user", { text: "Synthetic local focus target" }),
      event(2, "done", { turn_id: summary.turn_id, turn_summary: summary }),
    ];
    renderTimeline(events, { focusTurnRequest: { requestId: 1, turnId: summary.turn_id } });
    const turn = (await screen.findByLabelText("Turn 1 details")).closest("details") as HTMLDetailsElement;
    await waitFor(() => expect(turn).toHaveFocus());

    const find = openFind();
    fireEvent.change(find, { target: { value: "Synthetic local focus target" } });
    fireEvent.click(screen.getByRole("button", { name: "Find next" }));
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Synthetic local focus target"));
    await nextFrame();
    expect(turn).not.toHaveFocus();
    expect(document.activeElement?.textContent).toContain("Synthetic local focus target");
  });
});
