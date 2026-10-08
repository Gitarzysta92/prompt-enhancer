import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  SessionQualityAnalysisPreview,
  SessionQualityAnalysisPreviewApprovalRequest,
  SessionQualityAnalysisPreviewRequest,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { SYNTHETIC_SESSION_METRIC_READINESS } from "../../shared/api/syntheticFixtures";
import { AnalyzeLocallyDialog } from "./AnalyzeLocallyDialog";
import { COACHING_ANALYSIS_PREVIEW_REQUEST } from "./standardEngineeringAnalysisPreset";

const SESSION_ID = "b".repeat(64);
const SECOND_SESSION_ID = "c".repeat(64);
const PREVIEW_TEXT = "Synthetic redacted preview for the example workflow.";

function preview(overrides: Partial<SessionQualityAnalysisPreview> = {}) {
  const created = new Date(Date.now() + 60_000);
  const expires = new Date(created.getTime() + 600_000);
  const value: SessionQualityAnalysisPreview = {
    preview_id: "e".repeat(64),
    created_at: created.toISOString(),
    expires_at: expires.toISOString(),
    binding: {
      provider: "codex",
      session_id: SESSION_ID,
      analysis_window_fingerprint: "a".repeat(64),
      metric_keys: SYNTHETIC_SESSION_METRIC_READINESS.metrics.map(
        (metric) => metric.metric_key,
      ),
      destination: "local",
      exact_model: "none",
      estimator_plan_version: "example-plan-1",
      redactor_version: "example-redactor-1",
      retention_class: "local_ephemeral",
      message_count: 1,
      character_count: Array.from(PREVIEW_TEXT).length,
      cost_state: "not_applicable",
      estimated_cost_microunits: null,
      cost_currency: null,
    },
    messages: [{
      role: "user",
      kind: "request",
      language: "en",
      text: PREVIEW_TEXT,
    }],
    ...overrides,
  };
  return value;
}

type DialogProps = ComponentProps<typeof AnalyzeLocallyDialog>;

function dialogProps(overrides: Partial<DialogProps> = {}): DialogProps {
  return {
    exactSessionId: SESSION_ID,
    onPreparePreview: vi.fn(async (
      _sessionId: string,
      _request: SessionQualityAnalysisPreviewRequest,
      _signal: AbortSignal,
    ) => preview()),
    onApprovePreview: vi.fn(async (
      _sessionId: string,
      _previewId: string,
      _request: SessionQualityAnalysisPreviewApprovalRequest,
      _idempotencyKey: string,
      _signal: AbortSignal,
    ) => undefined),
    onClose: vi.fn(),
    sessionDescriptor: "Example review · 12 Aug 2026 · bbbbbbbb",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AnalyzeLocallyDialog", () => {
  it("labels a missing compatibility recheck action as Close instead of promising a no-op", async () => {
    const props = dialogProps({
      onPreparePreview: vi.fn().mockRejectedValue(new TransportError("example-blocked", 409, "provider_compatibility_blocked")),
      onCheckCompatibility: undefined,
    });
    render(<AnalyzeLocallyDialog {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Recheck compatibility" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onApprovePreview).not.toHaveBeenCalled();
  });

  it("fails closed when transport callbacks swap and a detached approval is clicked", async () => {
    const first = dialogProps();
    const second = dialogProps({
      onPreparePreview: vi.fn(async () => preview()),
      onApprovePreview: vi.fn(async () => undefined),
      onClose: first.onClose,
    });
    const { rerender } = render(
      <div className="app-shell"><AnalyzeLocallyDialog {...first} /></div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    const detachedApproval = await screen.findByRole("button", {
      name: "Approve once and analyze",
    });

    rerender(
      <div className="app-shell"><AnalyzeLocallyDialog {...second} /></div>,
    );
    fireEvent.click(detachedApproval);

    await waitFor(() => expect(first.onClose).toHaveBeenCalledTimes(1));
    expect(first.onApprovePreview).not.toHaveBeenCalled();
    expect(second.onApprovePreview).not.toHaveBeenCalled();
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
  });

  it("ignores a delayed preparation completion after close and revokes its actionable state", async () => {
    let resolvePreview!: (value: SessionQualityAnalysisPreview) => void;
    const props = dialogProps({
      onPreparePreview: vi.fn(() => new Promise<SessionQualityAnalysisPreview>((resolve) => {
        resolvePreview = resolve;
      })),
    });
    const { unmount } = render(
      <div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    unmount();
    resolvePreview(preview());
    await Promise.resolve();

    expect(props.onApprovePreview).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent(PREVIEW_TEXT);
  });

  it("rejects a preview whose local no-cost ephemeral binding is contradictory", async () => {
    const malformed = preview();
    malformed.binding.destination = "remote";
    const props = dialogProps({ onPreparePreview: vi.fn(async () => malformed) });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/binding could not be verified/i);
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(props.onApprovePreview).not.toHaveBeenCalled();
  });

  it("renders long escaped synthetic preview text as text and keeps it wrap-safe", async () => {
    const longText = `<script>fictional-example-only</script>${" bounded-redacted-example".repeat(120)}`;
    const prepared = preview();
    prepared.messages = [{
      role: "user",
      kind: "request",
      language: "en",
      text: longText,
    }];
    prepared.binding.character_count = Array.from(longText).length;
    const props = dialogProps({ onPreparePreview: vi.fn(async () => prepared) });
    const { container } = render(
      <div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));

    const text = await screen.findByText(longText);
    expect(text).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(getComputedStyle(text).overflowWrap).toBe("anywhere");
  });

  it("ignores a delayed approval completion after the dialog closes", async () => {
    let resolveApproval!: () => void;
    const approve = vi.fn(() => new Promise<void>((resolve) => {
      resolveApproval = resolve;
    }));
    function Harness() {
      const [open, setOpen] = useState(true);
      const props = dialogProps({
        onApprovePreview: approve,
        onClose: () => setOpen(false),
      });
      return (
        <div className="app-shell">
          {open && <AnalyzeLocallyDialog {...props} />}
        </div>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve once and analyze" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel request" }));
    resolveApproval();
    await Promise.resolve();

   expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
   expect(screen.queryByText(/Analysis completed and stored locally/i)).not.toBeInTheDocument();
   expect(approve).toHaveBeenCalledTimes(1);
 });

  it("erases an expired preview but still accepts the already-dispatched approval receipt", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let resolveApproval!: () => void;
      const approve = vi.fn(() => new Promise<void>((resolve) => {
        resolveApproval = resolve;
      }));
      const props = dialogProps({ onApprovePreview: approve });
      render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
      fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
      fireEvent.click(await screen.findByRole("button", { name: "Approve once and analyze" }));
      expect(approve).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(661_000); });

      expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Approve once and analyze" })).not.toBeInTheDocument();

      await act(async () => resolveApproval());

      expect(await screen.findByRole("dialog", { name: "Analysis completed" })).toBeVisible();
      expect(approve).toHaveBeenCalledTimes(1);
      expect(props.onClose).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("prepares first, then shows the exact local binding, metric set, and redacted text", async () => {
    const props = dialogProps();
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);

    const dialog = screen.getByRole("dialog", { name: "Ready to analyze" });
    const prepare = within(dialog).getByRole("button", {
      name: "Prepare redacted preview",
    });
    expect(prepare).toHaveFocus();
    expect(within(dialog).getByText(SESSION_ID)).toBeVisible();
    expect(within(dialog).queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(props.onApprovePreview).not.toHaveBeenCalled();

    fireEvent.click(prepare);

    await waitFor(() => expect(props.onPreparePreview).toHaveBeenCalledTimes(1));
    expect(props.onPreparePreview).toHaveBeenCalledWith(
      SESSION_ID,
      COACHING_ANALYSIS_PREVIEW_REQUEST,
      expect.any(AbortSignal),
    );
    expect(await within(dialog).findByText(PREVIEW_TEXT)).toBeVisible();
    expect(within(dialog).getByText("Destination").parentElement).toHaveTextContent(
      "local · this device only",
    );
    expect(within(dialog).getByText("Provider").parentElement).toHaveTextContent(
      "codex · local adapter",
    );
    expect(within(dialog).getByText(/deterministic rules/i)).toBeVisible();
    expect(within(dialog).getByText("Retention").parentElement).toHaveTextContent(
      "local_ephemeral · service memory",
    );
    expect(within(dialog).getByText("API cost").parentElement).toHaveTextContent(
      "not_applicable · no remote call",
    );
    expect(within(dialog).getByText("20 version-bound checks")).toBeVisible();
    expect(within(dialog).getByText(/16 supported measurement paths · 4 need source evidence/i)).toBeVisible();
    expect(within(dialog).getAllByText(/needs source evidence: unavailable without typed, reviewed provider evidence/i)).toHaveLength(4);
    expect(within(dialog).getByText(/a future analysis can resolve one only after a compatible typed-evidence adapter/i)).toBeVisible();
    expect(within(dialog).getByText("a".repeat(64))).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: "Approve once and analyze" }),
    ).toHaveFocus();
  });

  it("sends the exact binding once, then proves the stored result before closing", async () => {
    const props = dialogProps();
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    const approve = await screen.findByRole("button", {
      name: "Approve once and analyze",
    });

    fireEvent.click(approve);

    await waitFor(() => expect(props.onApprovePreview).toHaveBeenCalledTimes(1));
    const [sessionId, previewId, request, key, signal] =
      vi.mocked(props.onApprovePreview).mock.calls[0];
    expect(sessionId).toBe(SESSION_ID);
    expect(previewId).toBe("e".repeat(64));
    expect(request).toEqual({
      confirmation: "approve_exact_redacted_preview",
      expected_binding: preview().binding,
    });
    expect(key).toMatch(/^dashboard-quality-preview-approval-/);
    expect(signal).toBeInstanceOf(AbortSignal);
    const completedDialog = await screen.findByRole("dialog", {
      name: "Analysis completed",
    });
    expect(within(completedDialog).getByRole("status", {
      name: "Analysis completed and stored locally",
    })).toHaveTextContent(/Unknown or Abstained/i);
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(props.onClose).not.toHaveBeenCalled();

    const viewResults = within(completedDialog).getByRole("button", {
      name: "View stored results",
    });
    expect(viewResults).toHaveFocus();
    fireEvent.click(viewResults);
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("aborts preparation on cancel and never exposes an approval control", async () => {
    let capturedSignal: AbortSignal | undefined;
    const props = dialogProps({
      onPreparePreview: vi.fn((
        _sessionId: string,
        _request: SessionQualityAnalysisPreviewRequest,
        signal: AbortSignal,
      ) => {
        capturedSignal = signal;
        return new Promise<SessionQualityAnalysisPreview>(() => undefined);
      }),
    });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    await waitFor(() => expect(capturedSignal).toBeDefined());

    expect(screen.getByRole("button", { name: "Preparing private preview…" })).toBeDisabled();
    const cancel = screen.getByRole("button", { name: "Cancel request" });
    expect(cancel).toHaveFocus();
    fireEvent.click(cancel);

    expect(capturedSignal?.aborted).toBe(true);
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onApprovePreview).not.toHaveBeenCalled();
  });

  it("refuses a client-expired preview without calling approval", async () => {
    const prepared = preview();
    const props = dialogProps({ onPreparePreview: vi.fn(async () => prepared) });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    const approve = await screen.findByRole("button", {
      name: "Approve once and analyze",
    });
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(prepared.expires_at));

    fireEvent.click(approve);

    expect(props.onApprovePreview).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/expired/i);
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare fresh preview" })).toBeVisible();
  });

  it("clears a mismatched one-shot preview, suppresses server content, and requires preparation again", async () => {
    const approve = vi.fn(async () => {
      throw new TransportError(
        "PRIVATE-PROVIDER-ERROR-CANARY",
        409,
        "redaction_preview_binding_mismatch",
      );
    });
    const props = dialogProps({ onApprovePreview: approve });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve once and analyze" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/exact preview binding changed/i);
    expect(document.body.textContent).not.toContain("PRIVATE-PROVIDER-ERROR-CANARY");
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve once and analyze" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare fresh preview" }));
    await waitFor(() => expect(props.onPreparePreview).toHaveBeenCalledTimes(2));
  });

  it("requires a stored-result refresh after an already-consumed or ambiguous approval", async () => {
    const props = dialogProps({
      onApprovePreview: vi.fn(async () => {
        throw new TransportError(
          "PRIVATE-CONSUMED-CANARY",
          409,
          "redaction_preview_consumed",
        );
      }),
    });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve once and analyze" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already consumed/i);
    expect(document.body.textContent).not.toContain("PRIVATE-CONSUMED-CANARY");
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /prepare fresh preview/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close and refresh session" }));
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onPreparePreview).toHaveBeenCalledTimes(1);
  });

  it("sanitizes a preparation failure and retries without approving", async () => {
    const prepare = vi.fn()
      .mockRejectedValueOnce(new TransportError("PRIVATE-CANARY", 503, "provider_unavailable"))
      .mockResolvedValueOnce(preview());
    const props = dialogProps({ onPreparePreview: prepare });
    render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
    expect(document.body.textContent).not.toContain("PRIVATE-CANARY");
    expect(props.onApprovePreview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Prepare fresh preview" }));
    expect(await screen.findByText(PREVIEW_TEXT)).toBeVisible();
    expect(prepare).toHaveBeenCalledTimes(2);
  });

  it.each([
    [
      "source_selection_limit",
      /session catalog exceeds the local selection-scan limit/i,
    ],
    [
      "source_provider_response_limit",
      /local Codex response exceeded the transport limit/i,
    ],
    [
      "source_thread_structure_limit",
      /full local thread structure exceeds/i,
    ],
    [
      "source_preview_window_limit",
      /focus message cannot fit/i,
    ],
    [
      "source_resource_limit",
      /unclassified safety limit/i,
    ],
  ] as const)(
    "makes terminal source failure %s truthful and non-retryable",
    async (reasonCode, expectedCopy) => {
      const prepare = vi.fn(async () => {
        throw new TransportError("PRIVATE-LIMIT-CANARY", 413, reasonCode);
      });
      const props = dialogProps({ onPreparePreview: prepare });
      render(<div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>);

      fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(expectedCopy);
      expect(document.body.textContent).not.toContain("PRIVATE-LIMIT-CANARY");
      expect(screen.queryByRole("button", { name: /prepare fresh preview/i })).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(/same session, adapter, and limits/i);
      const close = screen.getByRole("button", { name: /^Close$/ });
      expect(close).toHaveFocus();
      fireEvent.click(close);

      expect(props.onClose).toHaveBeenCalledTimes(1);
      expect(prepare).toHaveBeenCalledTimes(1);
      expect(props.onApprovePreview).not.toHaveBeenCalled();
    },
  );

  it("closes and clears the preview if the selected safe session identity drifts", async () => {
    const props = dialogProps();
    const { rerender } = render(
      <div className="app-shell"><AnalyzeLocallyDialog {...props} /></div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Prepare redacted preview" }));
    expect(await screen.findByText(PREVIEW_TEXT)).toBeVisible();

    rerender(
      <div className="app-shell">
        <AnalyzeLocallyDialog {...props} exactSessionId={SECOND_SESSION_ID} />
      </div>,
    );

    await waitFor(() => expect(props.onClose).toHaveBeenCalledTimes(1));
    expect(props.onApprovePreview).not.toHaveBeenCalled();
    expect(screen.queryByText(PREVIEW_TEXT)).not.toBeInTheDocument();
  });

  it("traps focus, closes with Escape, and restores focus to the opener", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      const props = dialogProps({ onClose: () => setOpen(false) });
      return (
        <div className="app-shell">
          <button onClick={() => setOpen(true)} type="button">Open analysis review</button>
          {open && <AnalyzeLocallyDialog {...props} />}
        </div>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open analysis review" });
    opener.focus();
    fireEvent.click(opener);
    const primary = screen.getByRole("button", { name: "Prepare redacted preview" });
    const close = screen.getByRole("button", { name: "Close analysis review" });
    expect(primary).toHaveFocus();

    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(primary).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });
});
