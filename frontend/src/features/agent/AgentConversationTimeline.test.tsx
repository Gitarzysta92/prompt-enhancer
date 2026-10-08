import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../../shared/api/contracts";
import { TranscriptEventRows } from "./AgentConversationTimeline";

const events: AgentEvent[] = [
  { at: "2026-01-01T00:00:00Z", attachments: [], kind: "user", seq: 1, text: "Synthetic earlier message" },
  { at: "2026-01-01T00:00:01Z", attachments: [], kind: "assistant", seq: 9, text: "Synthetic exact message" },
];

describe("TranscriptEventRows", () => {
  it("expands and focuses the exact sparse retained event without global DOM ids", async () => {
    const { container } = render(
      <TranscriptEventRows
        events={events}
        fileActionsDisabled={false}
        focusEventRequest={{ requestId: 1, eventSeq: 9 }}
        focusTurnRequest={null}
        onOpenFile={() => undefined}
        reasoningEnabled={false}
      />,
    );
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Synthetic exact message"));
    expect(container.querySelector("#agent-event-9")).toBeNull();
  });
});
