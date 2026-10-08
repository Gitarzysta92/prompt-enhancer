import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SessionTranscript } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { SessionTranscriptPane, safeTranscript } from "./SessionTranscriptPane";

const SESSION = "a".repeat(64);

function transcript(): SessionTranscript {
  return {
    contract_version: "session-reader.v1",
    provider: "claude_code",
    session_id: SESSION,
    source: "claude_transcript_file",
    provider_version: "2.1.0",
    turns: [
      { role: "user", text: "Please add retries to the demo uploader", at: "2040-01-01T09:00:00Z", tool_name: null, truncated: false },
      { role: "assistant", text: "I will look at the uploader first.", at: "2040-01-01T09:00:03Z", tool_name: null, truncated: false },
      { role: "tool_call", text: '{"file_path": "src/uploader.py"}', at: "2040-01-01T09:00:03Z", tool_name: "Read", truncated: false },
      { role: "assistant", text: "Added a bounded retry with backoff.", at: "2040-01-01T09:00:30Z", tool_name: null, truncated: true },
    ],
    turn_count_total: 4,
    truncated: false,
    persisted: false,
    local_only: true,
    read_at: "2040-01-01T09:01:00Z",
  };
}

describe("SessionTranscriptPane", () => {
  it("fetches nothing until asked, then renders turns and collapses tool calls", async () => {
    const getSessionTranscript = vi.fn(async () => transcript());
    render(<SessionTranscriptPane sessionId={SESSION} transport={{ getSessionTranscript }} />);
    expect(getSessionTranscript).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Read this session" }));
    expect(await screen.findByText("Please add retries to the demo uploader")).toBeInTheDocument();
    expect(getSessionTranscript).toHaveBeenCalledWith(SESSION);
    expect(screen.getByText(/4 of 4 turns/)).toBeInTheDocument();
    expect(screen.getByText(/your Claude Code transcript file/)).toBeInTheDocument();
    expect(screen.getByText("Tool call · Read")).toBeInTheDocument();
    expect(screen.queryByText('{"file_path": "src/uploader.py"}')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show input/ }));
    expect(screen.getByText('{"file_path": "src/uploader.py"}')).toBeInTheDocument();
    expect(screen.getByText(/· truncated$/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close and discard" }));
    expect(screen.queryByText("Please add retries to the demo uploader")).toBeNull();
  });

  it("explains reader-off, consent, missing, and never renders an invalid shape", async () => {
    const off = vi.fn(async () => { throw new TransportError("not found", 404); });
    const { unmount } = render(<SessionTranscriptPane sessionId={SESSION} transport={{ getSessionTranscript: off }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read this session" }));
    expect(await screen.findByText(/PROMPT_ENHANCER_SESSION_READER=enabled/)).toBeInTheDocument();
    unmount();

    const consent = vi.fn(async () => { throw new TransportError("forbidden", 403); });
    const second = render(<SessionTranscriptPane sessionId={SESSION} transport={{ getSessionTranscript: consent }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read this session" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("local-history access");
    second.unmount();

    const odd = vi.fn(async () => ({ ...transcript(), persisted: true, turns: [{ role: "user", text: "CANARY-ODD" }] }) as unknown as SessionTranscript);
    render(<SessionTranscriptPane sessionId={SESSION} transport={{ getSessionTranscript: odd }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read this session" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("could not be read"));
    expect(document.body.textContent).not.toContain("CANARY-ODD");
    expect(safeTranscript(transcript())).toBe(true);
    expect(safeTranscript({ ...transcript(), source: "network" })).toBe(false);
  });
});
