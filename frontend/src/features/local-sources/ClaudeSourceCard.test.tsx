import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ClaudeCodeLocalSourceStatus, IngestionReport } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { ClaudeSourceCard, safeClaudeStatus } from "./ClaudeSourceCard";

const CANARY_PROMPT = "CANARY-PROMPT-fix the acme billing job";

function status(overrides: Partial<ClaudeCodeLocalSourceStatus> = {}): ClaudeCodeLocalSourceStatus {
  return {
    consent_active: false,
    captured_sessions: 0,
    captured_events: 0,
    captured_requests: 0,
    telemetry_sessions: 0,
    indexed_sessions: 0,
    indexed_projects: 0,
    verification_capability: {
      state: "validation_only",
      live_classification_enabled: false,
      supported_kinds: ["test", "build", "type_check"],
      reason_code: "synthetic_validation_only",
      candidate_schema_version: "synthetic-verification-1",
      classifier_version: "synthetic-classifier-1",
      normalizer_version: "synthetic-normalizer-1",
    },
    capture_channel: "claude_code_hooks",
    telemetry_channel: "claude_code_otlp",
    reads_transcripts: false,
    persists_content: false,
    ...overrides,
  };
}

function report(): IngestionReport {
  return {
    provider: "claude_code",
    sessions_seen: 3,
    sessions_selected: 3,
    sessions_inserted: 3,
    sessions_updated: 0,
    events_seen: 41,
    events_inserted: 41,
    events_updated: 0,
    metrics_written: 12,
    truncated: false,
  } as IngestionReport;
}

describe("ClaudeSourceCard", () => {
  it("shows captured and indexed counts as separate facts and never claims completeness", async () => {
    const transport = {
      getClaudeLocalSourceStatus: vi.fn(async () => status({ consent_active: true, captured_sessions: 2, captured_events: 17, indexed_sessions: 1, indexed_projects: 1 })),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(),
    };
    render(<ClaudeSourceCard transport={transport} />);
    expect(await screen.findByRole("heading", { name: "Claude Code sessions" })).toBeInTheDocument();
    expect(screen.getByText("Capture permitted")).toBeInTheDocument();
    expect(screen.getByText("Captured sessions").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Captured events").nextSibling).toHaveTextContent("17");
    expect(screen.getByText("Indexed sessions").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Transcripts read").nextSibling).toHaveTextContent("Never");
    expect(safeClaudeStatus({ ...status(), reads_transcripts: true })).toBe(false);
    expect(screen.getByText("Content stored").nextSibling).toHaveTextContent("Never");
    expect(screen.getByText(/Neither claims that every provider event was captured/)).toBeInTheDocument();
    expect(screen.getByLabelText("Source: Claude Code")).toBeInTheDocument();
    expect(screen.queryByText(/complete/i)).toBeNull();
  });

  it("grants, indexes, and revokes through the transport with truthful notices", async () => {
    let current = status();
    const transport = {
      getClaudeLocalSourceStatus: vi.fn(async () => current),
      grantClaudeLocalHistoryConsent: vi.fn(async () => { current = status({ consent_active: true, captured_sessions: 3, captured_events: 41 }); return current; }),
      revokeClaudeLocalHistoryConsent: vi.fn(async () => { current = status({ consent_active: false, captured_sessions: 3, captured_events: 41, indexed_sessions: 3, indexed_projects: 1 }); return current; }),
      indexClaudeLocalSessions: vi.fn(async () => { current = status({ consent_active: true, captured_sessions: 3, captured_events: 41, indexed_sessions: 3, indexed_projects: 1 }); return report(); }),
    };
    render(<ClaudeSourceCard transport={transport} />);
    const permit = await screen.findByRole("button", { name: "Permit hook capture" });
    const blockedIndex = screen.getByRole("button", { name: /Index captured sessions/ });
    expect(blockedIndex).toBeDisabled();
    expect(blockedIndex).toHaveAccessibleDescription(/permit hook capture/i);
    fireEvent.click(permit);
    await screen.findByText(/Install the hooks fragment in Claude Code/);
    expect(transport.grantClaudeLocalHistoryConsent).toHaveBeenCalledTimes(1);

    const index = screen.getByRole("button", { name: "Index captured sessions" });
    expect(index).toBeEnabled();
    expect(index).not.toHaveAttribute("aria-describedby");
    fireEvent.click(index);
    await screen.findByText("Indexed 3 captured Claude Code sessions and 41 events.");
    expect(transport.indexClaudeLocalSessions).toHaveBeenCalledWith(500);
    await waitFor(() => expect(screen.getByText("Indexed sessions").nextSibling).toHaveTextContent("3"));

    fireEvent.click(screen.getByRole("button", { name: "Stop hook capture" }));
    await screen.findByText(/already-captured events remain until you delete them/);
    expect(transport.revokeClaudeLocalHistoryConsent).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Capture not permitted")).toBeInTheDocument();
  });

  it("does not claim a grant succeeded when the local response cannot be verified", async () => {
    const current = status({ consent_active: false });
    const transport = {
      getClaudeLocalSourceStatus: vi.fn(async () => current),
      grantClaudeLocalHistoryConsent: vi.fn(async () => ({
        ...current,
        consent_active: "yes" as unknown as boolean,
      })),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(),
    };

    render(<ClaudeSourceCard transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Permit hook capture" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed");
    expect(screen.queryByText(/Hook capture is now permitted/)).toBeNull();
    expect(screen.getByText("Capture not permitted")).toBeVisible();
    expect(transport.getClaudeLocalSourceStatus).toHaveBeenCalledTimes(2);
  });

  it("does not claim a revoke succeeded when the local response cannot be verified", async () => {
    const current = status({ consent_active: true });
    const transport = {
      getClaudeLocalSourceStatus: vi.fn(async () => current),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(async () => ({
        ...current,
        consent_active: null as unknown as boolean,
      })),
      indexClaudeLocalSessions: vi.fn(),
    };

    render(<ClaudeSourceCard transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop hook capture" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed");
    expect(screen.queryByText(/Hook capture is now off/)).toBeNull();
    expect(screen.getByText("Capture permitted")).toBeVisible();
    expect(transport.getClaudeLocalSourceStatus).toHaveBeenCalledTimes(2);
  });

  it("requires the requested consent state before announcing success", async () => {
    const grantStatus = status({ consent_active: false });
    const grantTransport = {
      getClaudeLocalSourceStatus: vi.fn(async () => grantStatus),
      grantClaudeLocalHistoryConsent: vi.fn(async () => grantStatus),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(),
    };

    const grantView = render(<ClaudeSourceCard transport={grantTransport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Permit hook capture" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed");
    expect(screen.queryByText(/Hook capture is now permitted/)).toBeNull();
    expect(screen.getByText("Capture not permitted")).toBeVisible();
    grantView.unmount();

    const revokeStatus = status({ consent_active: true });
    const revokeTransport = {
      getClaudeLocalSourceStatus: vi.fn(async () => revokeStatus),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(async () => revokeStatus),
      indexClaudeLocalSessions: vi.fn(),
    };
    render(<ClaudeSourceCard transport={revokeTransport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop hook capture" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed");
    expect(screen.queryByText(/Hook capture is now off/)).toBeNull();
    expect(screen.getByText("Capture permitted")).toBeVisible();
  });

  it("explains a 403 on index as missing consent, and shows setup on demand", async () => {
    const transport = {
      getClaudeLocalSourceStatus: vi.fn(async () => status({ consent_active: true, captured_sessions: 1, captured_events: 4 })),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(async () => { throw new TransportError("forbidden", 403); }),
    };
    render(<ClaudeSourceCard transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Index captured sessions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Grant hook-capture consent before indexing.");
    fireEvent.click(screen.getByRole("button", { name: "How to install the hook" }));
    const setup = screen.getByRole("region", { name: "Claude Code hook setup" });
    expect(setup).toHaveTextContent("python -m prompt_enhancer claude-hooks-config");
    expect(setup).toHaveTextContent("never writes to that file");
  });

  it("renders nothing when the runtime does not expose the source, and fails closed on odd shapes", async () => {
    const absent = {
      getClaudeLocalSourceStatus: vi.fn(async () => { throw new TransportError("missing", 404); }),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(),
    };
    const { container, unmount } = render(<ClaudeSourceCard transport={absent} />);
    await waitFor(() => expect(absent.getClaudeLocalSourceStatus).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    unmount();

    const odd = {
      getClaudeLocalSourceStatus: vi.fn(async () => ({ ...status(), last_prompt: CANARY_PROMPT, persists_content: true })),
      grantClaudeLocalHistoryConsent: vi.fn(),
      revokeClaudeLocalHistoryConsent: vi.fn(),
      indexClaudeLocalSessions: vi.fn(),
    };
    render(<ClaudeSourceCard transport={odd} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected shape");
    expect(document.body.textContent).not.toContain(CANARY_PROMPT);
    expect(document.body.textContent).not.toContain("acme");
  });

  it("safeClaudeStatus refuses anything that is not the content-free shape", () => {
    expect(safeClaudeStatus(status())).toBe(true);
    expect(safeClaudeStatus({ ...status(), capture_channel: "jsonl" })).toBe(false);
    expect(safeClaudeStatus({ ...status(), captured_events: -1 })).toBe(false);
    expect(safeClaudeStatus({ ...status(), captured_requests: "private text" })).toBe(false);
    expect(safeClaudeStatus({ ...status(), telemetry_sessions: Number.MAX_SAFE_INTEGER + 1 })).toBe(false);
    expect(safeClaudeStatus({ ...status(), telemetry_channel: "unexpected" })).toBe(false);
    expect(safeClaudeStatus({ ...status(), unexpected_content: "must not cross the boundary" })).toBe(false);
    expect(safeClaudeStatus({
      ...status(),
      verification_capability: {
        ...status().verification_capability,
        supported_kinds: ["unknown_kind"],
      },
    })).toBe(false);
    expect(safeClaudeStatus({
      ...status(),
      verification_capability: {
        ...status().verification_capability,
        live_classification_enabled: true,
      },
    })).toBe(false);
    expect(safeClaudeStatus(null)).toBe(false);
  });
});
