import { describe, expect, it } from "vitest";
import type { AgentEvent } from "../../shared/api/contracts";
import { agentPromptContext } from "./AgentPromptCheck";

function event(seq: number, kind: AgentEvent["kind"], text: string): AgentEvent {
  return { seq, at: "2026-08-20T01:00:00Z", kind, attachments: [], text, tool: null, arguments: null, call_id: null, approval_id: null, ok: null, preview: null };
}

describe("agentPromptContext", () => {
  it("keeps only the newest bounded conversational messages", () => {
    const events = Array.from({ length: 30 }, (_, index) => event(index + 1, index % 2 === 0 ? "user" : "assistant", `turn-${index + 1}`));
    events.splice(27, 0, event(100, "tool_result", "tool output"));
    const context = agentPromptContext(events);
    expect(context).toHaveLength(24);
    expect(context[0].content).toBe("turn-7");
    expect(context.at(-1)?.content).toBe("turn-30");
    expect(context.some((message) => message.content.includes("tool output"))).toBe(false);
  });

  it("caps each message and the complete context without manufacturing empty turns", () => {
    const events = Array.from({ length: 8 }, (_, index) => event(index + 1, "user", String(index).repeat(9_000)));
    const context = agentPromptContext(events);
    expect(context.every((message) => message.content.length <= 8_000)).toBe(true);
    expect(context.reduce((total, message) => total + message.content.length, 0)).toBeLessThanOrEqual(40_000);
    expect(context.every((message) => message.content.length > 0)).toBe(true);
  });
});
