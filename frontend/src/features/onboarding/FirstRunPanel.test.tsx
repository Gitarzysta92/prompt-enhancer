import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TransportError } from "../../shared/api/httpTransport";
import {
  FirstRunPanel,
  safeOnboardingResult,
  safeOnboardingStatus,
  type TruthfulOnboardingStatus,
} from "./FirstRunPanel";

function status(overrides: Partial<TruthfulOnboardingStatus> = {}): TruthfulOnboardingStatus {
  return {
    contract_version: "onboarding.v1",
    providers: [
      { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: false, indexed_sessions: 0, transcript_files: null },
      { provider: "claude_code", installed: true, signal: "claude_transcript_root", consent_active: false, indexed_sessions: 0, transcript_files: 52 },
    ],
    any_installed: true,
    needs_onboarding: true,
    refresh_interval_seconds: 600,
    last_refresh_at: null,
    last_refresh_error: false,
    claude_home_override_supported: true,
    ...overrides,
  };
}

function completedStatus(): TruthfulOnboardingStatus {
  return status({
    providers: [
      { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: true, indexed_sessions: 8, transcript_files: null },
      { provider: "claude_code", installed: true, signal: "claude_transcript_root", consent_active: true, indexed_sessions: 13, transcript_files: 13 },
    ],
    needs_onboarding: false,
  });
}

describe("FirstRunPanel", () => {
  it("accepts only safe integer or null discovery counts", () => {
    expect(safeOnboardingStatus(status())).toBe(true);
    expect(safeOnboardingStatus(status({
      providers: [
        { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: true, indexed_sessions: null, transcript_files: null },
        { provider: "claude_code", installed: true, signal: "claude_transcript_enumeration_unavailable", consent_active: false, indexed_sessions: 0, transcript_files: null },
      ],
    }))).toBe(true);

    for (const invalid of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1]) {
      const invalidIndexed = status();
      invalidIndexed.providers[0].indexed_sessions = invalid;
      expect(safeOnboardingStatus(invalidIndexed)).toBe(false);

      const invalidTranscript = status();
      invalidTranscript.providers[1].transcript_files = invalid;
      expect(safeOnboardingStatus(invalidTranscript)).toBe(false);
    }

    const duplicate = status();
    duplicate.providers[1] = { ...duplicate.providers[0] };
    expect(safeOnboardingStatus(duplicate)).toBe(false);
  });

  it("rejects contradictory providers, summaries, and malformed refresh metadata", () => {
    expect(safeOnboardingStatus({ ...status(), any_installed: false })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), needs_onboarding: false })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), refresh_interval_seconds: 59 })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), refresh_interval_seconds: Number.MAX_SAFE_INTEGER + 1 })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), last_refresh_at: "not-a-date" })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), last_refresh_at: "0" })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), last_refresh_at: "2026-02-30T00:00:00Z" })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), last_refresh_error: "false" })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), claude_home_override_supported: 1 })).toBe(false);
    expect(safeOnboardingStatus({ ...status(), unexpected: true })).toBe(false);

    const installedSignalMismatch = status();
    installedSignalMismatch.providers[0] = {
      ...installedSignalMismatch.providers[0],
      installed: false,
    };
    expect(safeOnboardingStatus(installedSignalMismatch)).toBe(false);

    for (const signal of [
      "claude_transcript_enumeration_unavailable",
      "claude_transcript_count_capped",
    ] as const) {
      const unavailableWithExactCount = status();
      unavailableWithExactCount.providers[1] = {
        ...unavailableWithExactCount.providers[1],
        signal,
      };
      expect(safeOnboardingStatus(unavailableWithExactCount)).toBe(false);
    }

    const rootWithoutExactCount = status();
    rootWithoutExactCount.providers[1] = {
      ...rootWithoutExactCount.providers[1],
      transcript_files: null,
    };
    expect(safeOnboardingStatus(rootWithoutExactCount)).toBe(false);
  });

  it("requires an accept response to grant exactly the requested consented providers", () => {
    expect(safeOnboardingResult({
      granted: ["codex"],
      indexed_sessions: 1,
      status: completedStatus(),
    }, ["codex", "claude_code"])).toBe(false);
    expect(safeOnboardingResult({
      granted: ["codex", "claude_code"],
      indexed_sessions: 1,
      status: status(),
    }, ["codex", "claude_code"])).toBe(false);
    expect(safeOnboardingResult({
      granted: ["claude_code", "codex"],
      indexed_sessions: 0,
      status: completedStatus(),
    }, ["codex", "claude_code"])).toBe(true);
  });

  it("accepts provider order independently and looks Claude up by identity", async () => {
    sessionStorage.clear();
    const reversed = status({
      providers: [
        { provider: "claude_code", installed: true, signal: "claude_transcript_root", consent_active: false, indexed_sessions: 0, transcript_files: 1 },
        { provider: "codex", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
      ],
    });
    expect(safeOnboardingStatus(reversed)).toBe(true);
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => reversed),
      acceptOnboarding: vi.fn(),
    }} />);
    expect(await screen.findByText("1 session on disk")).toBeInTheDocument();
    expect(screen.queryByLabelText("Claude Code folder")).toBeNull();
  });

  it("renders unknown discovery counts without inventing zero", async () => {
    sessionStorage.clear();
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({
        providers: [
          { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: true, indexed_sessions: null, transcript_files: null },
          { provider: "claude_code", installed: true, signal: "claude_transcript_enumeration_unavailable", consent_active: false, indexed_sessions: 0, transcript_files: null },
        ],
      })),
      acceptOnboarding: vi.fn(),
    }} />);
    expect(await screen.findByText("CLI found · loaded count unavailable")).toBeInTheDocument();
    expect(screen.getByText("Transcript folder found · session count unavailable")).toBeInTheDocument();
    expect(screen.queryByText("0 sessions on disk")).toBeNull();
  });

  it("keeps a known zero as an exact loaded count", async () => {
    sessionStorage.clear();
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({
        providers: [
          { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: true, indexed_sessions: 0, transcript_files: null },
          { provider: "claude_code", installed: true, signal: "claude_transcript_root", consent_active: false, indexed_sessions: 0, transcript_files: 0 },
        ],
      })),
      acceptOnboarding: vi.fn(),
    }} />);
    expect(await screen.findByText("CLI found · 0 sessions loaded")).toBeInTheDocument();
    expect(screen.getByText("0 sessions on disk")).toBeInTheDocument();
  });

  it("renders a bounded transcript scan without presenting the bound as exact", async () => {
    sessionStorage.clear();
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({
        providers: [
          { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: false, indexed_sessions: 0, transcript_files: null },
          { provider: "claude_code", installed: true, signal: "claude_transcript_count_capped", consent_active: false, indexed_sessions: 0, transcript_files: null },
        ],
      })),
      acceptOnboarding: vi.fn(),
    }} />);
    expect(await screen.findByText(/session count exceeds the local scan limit/)).toBeInTheDocument();
    expect(screen.queryByText(/20000 sessions on disk/)).toBeNull();
  });

  it("shows both detections and loads everything with one yes", async () => {
    sessionStorage.clear();
    const navigate = vi.fn();
    const acceptOnboarding = vi.fn(async () => ({ granted: ["codex", "claude_code"] as ("codex" | "claude_code")[], indexed_sessions: 60, status: completedStatus() }));
    render(<FirstRunPanel navigate={navigate} transport={{ getOnboardingStatus: vi.fn(async () => status()), acceptOnboarding }} />);
    expect(await screen.findByRole("heading", { name: "Load your projects and sessions" })).toBeInTheDocument();
    expect(screen.getByText("52 sessions on disk")).toBeInTheDocument();
    expect(screen.getByText("CLI found")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yes, load everything" }));
    await waitFor(() => expect(acceptOnboarding).toHaveBeenCalledWith(
      { providers: ["codex", "claude_code"], claude_home: null },
      expect.any(AbortSignal),
    ));
    expect(navigate).toHaveBeenCalledWith({ name: "sessions" });
  });

  it("keeps a nullable first-index result explicit and does not navigate as completed", async () => {
    sessionStorage.clear();
    const navigate = vi.fn();
    const acceptOnboarding = vi.fn(async () => ({
      granted: ["codex", "claude_code"] as ("codex" | "claude_code")[],
      indexed_sessions: null,
      status: completedStatus(),
    }));
    render(<FirstRunPanel navigate={navigate} transport={{
      getOnboardingStatus: vi.fn(async () => status()),
      acceptOnboarding,
    }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Yes, load everything" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("first index result could not be confirmed");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("includes a manual Claude folder alongside an already detected Codex source", async () => {
    sessionStorage.clear();
    const acceptOnboarding = vi.fn(async () => ({
      granted: ["codex", "claude_code"] as ("codex" | "claude_code")[],
      indexed_sessions: 0,
      status: completedStatus(),
    }));
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({
        providers: [
          { provider: "codex", installed: true, signal: "codex_cli_on_path", consent_active: false, indexed_sessions: 0, transcript_files: null },
          { provider: "claude_code", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
        ],
      })),
      acceptOnboarding,
    }} />);
    fireEvent.change(await screen.findByLabelText("Claude Code folder"), {
      target: { value: "D:/example/claude-home" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Yes, load everything" }));
    await waitFor(() => expect(acceptOnboarding).toHaveBeenCalledWith(
      {
        providers: ["codex", "claude_code"],
        claude_home: "D:/example/claude-home",
      },
      expect.any(AbortSignal),
    ));
  });

  it("asks for a folder when nothing is found and explains a bad one", async () => {
    sessionStorage.clear();
    const acceptOnboarding = vi.fn(async () => {
      throw new TransportError("Local API request failed (422)", 422, "claude_home_invalid");
    });
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({ any_installed: false, providers: [
        { provider: "codex", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
        { provider: "claude_code", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
      ] })),
      acceptOnboarding,
    }} />);
    expect(await screen.findByRole("heading", { name: /could not find Codex or Claude Code/ })).toBeInTheDocument();
    const loadButton = screen.getByRole("button", { name: "Yes, load everything" });
    expect(loadButton).toBeDisabled();
    expect(screen.getByText(/enter a Claude Code folder above, before loading/)).toBeVisible();
    expect(acceptOnboarding).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Claude Code folder"), { target: { value: "D:/not-a-home" } });
    await waitFor(() => expect((screen.getByLabelText("Claude Code folder") as HTMLInputElement).value).toBe("D:/not-a-home"));
    expect(loadButton).toBeEnabled();
    fireEvent.click(loadButton);
    await waitFor(() => expect(acceptOnboarding).toHaveBeenCalledWith(
      { providers: ["claude_code"], claude_home: "D:/not-a-home" },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent("does not look like a Claude Code home");
  });

  it("aborts an in-flight accept and ignores its late success after unmount", async () => {
    sessionStorage.clear();
    const navigate = vi.fn();
    let resolveAccept: ((value: unknown) => void) | undefined;
    const acceptOnboarding = vi.fn((_request: unknown, _signal?: AbortSignal) => new Promise<unknown>((resolve) => {
      resolveAccept = resolve;
    }));
    const view = render(<FirstRunPanel navigate={navigate} transport={{
      getOnboardingStatus: vi.fn(async () => status()),
      acceptOnboarding,
    }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Yes, load everything" }));
    await waitFor(() => expect(acceptOnboarding).toHaveBeenCalledTimes(1));
    const signal = acceptOnboarding.mock.calls[0][1];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      resolveAccept?.({
        granted: ["codex", "claude_code"],
        indexed_sessions: 21,
        status: completedStatus(),
      });
      await Promise.resolve();
    });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does not offer an unsupported Claude folder override", async () => {
    sessionStorage.clear();
    render(<FirstRunPanel navigate={vi.fn()} transport={{
      getOnboardingStatus: vi.fn(async () => status({
        any_installed: false,
        claude_home_override_supported: false,
        providers: [
          { provider: "codex", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
          { provider: "claude_code", installed: false, signal: "not_found", consent_active: false, indexed_sessions: 0, transcript_files: null },
        ],
      })),
      acceptOnboarding: vi.fn(),
    }} />);
    expect(await screen.findByRole("heading", { name: /could not find Codex or Claude Code/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Claude Code folder")).toBeNull();
    expect(screen.queryByText(/point at a Claude Code folder below/)).toBeNull();
  });

  it("renders nothing once onboarding is done or dismissed, or when the runtime lacks it", async () => {
    sessionStorage.clear();
    const done = render(<FirstRunPanel navigate={vi.fn()} transport={{ getOnboardingStatus: vi.fn(async () => completedStatus()), acceptOnboarding: vi.fn() }} />);
    await waitFor(() => expect(done.container).toBeEmptyDOMElement());
    done.unmount();
    const absent = render(<FirstRunPanel navigate={vi.fn()} transport={{ getOnboardingStatus: vi.fn(async () => { throw new TransportError("missing", 404); }), acceptOnboarding: vi.fn() }} />);
    await waitFor(() => expect(absent.container).toBeEmptyDOMElement());
    absent.unmount();
    render(<FirstRunPanel navigate={vi.fn()} transport={{ getOnboardingStatus: vi.fn(async () => status()), acceptOnboarding: vi.fn() }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("heading", { name: "Load your projects and sessions" })).toBeNull();
    expect(sessionStorage.getItem("prompt-enhancer.first-run.dismissed")).toBe("1");
  });
});
