import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CalibrationCasePane, safeCalibrationReview } from "./CalibrationCasePane";
import { exampleCalibrationReview } from "./calibrationFixtures.test-support";
import type { CalibrationReview } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";

const SESSION = "a".repeat(64);
const OTHER = "b".repeat(64);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("reviewed calibration evidence", () => {
  afterEach(() => vi.useRealTimers());

  it.each([
    { session_id: OTHER }, { provider: "codex" }, { case_version: "example-unknown" },
    { case_fingerprint: "0".repeat(64) }, { window_fingerprint: "unknown" },
    { review_id: "bad" }, { persisted: true }, { local_only: false }, { expires_at: "not-a-date" },
    { records: [] }, { records: [{ sequence: false, role: "user", content: "example" }] },
    { records: [{ sequence: 0, role: "system", content: "example" }] },
    { records: [{ sequence: 0, role: "user", content: " " }] },
  ])("rejects a malformed or foreign case %#", (changes) => {
    expect(safeCalibrationReview({ ...exampleCalibrationReview(), ...changes }, SESSION, "claude_code")).toBe(false);
  });

  it("loads exactly the authorized case and treats displayed text as text", async () => {
    const value = exampleCalibrationReview(SESSION, { records: [{ sequence: 0, role: "user", content: "<img src=x onerror=alert('example')>" }] });
    const transport = { reviewCalibrationCase: vi.fn(async () => value) };
    const onReviewChange = vi.fn();
    const view = render(<CalibrationCasePane sessionId={SESSION} provider="claude_code" transport={transport} disabled={false} onReviewChange={onReviewChange} />);
    expect(await screen.findByText(value.records[0].content)).toBeVisible();
    expect(view.container.querySelector("img")).toBeNull();
    expect(onReviewChange).toHaveBeenLastCalledWith(value);
    expect(transport.reviewCalibrationCase).toHaveBeenCalledOnce();
  });

  it.each(["session", "connection"])("ignores a delayed response after %s replacement", async (change) => {
    const pending = deferred<CalibrationReview>();
    const first = { reviewCalibrationCase: vi.fn((_sid: string, _size: number, _signal?: AbortSignal) => pending.promise) };
    const nextId = change === "session" ? OTHER : SESSION;
    const next = exampleCalibrationReview(nextId, { records: [{ sequence: 0, role: "user", content: "Fresh example evidence." }] });
    const second = { reviewCalibrationCase: vi.fn(async () => next) };
    const onReviewChange = vi.fn();
    const view = render(<CalibrationCasePane sessionId={SESSION} provider="claude_code" transport={first} disabled={false} onReviewChange={onReviewChange} />);
    view.rerender(<CalibrationCasePane sessionId={nextId} provider={next.provider} transport={second} disabled={false} onReviewChange={onReviewChange} />);
    await screen.findByText("Fresh example evidence.");
    await act(async () => { pending.resolve(exampleCalibrationReview()); await pending.promise; });
    expect(first.reviewCalibrationCase.mock.calls[0][2]?.aborted).toBe(true);
    expect(onReviewChange).toHaveBeenLastCalledWith(next);
    expect(screen.queryByText(/Review the example module/)).toBeNull();
  });

  it("expires a receipt and can refresh it without retaining an old approval", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2040-01-01T00:00:00Z"));
    const transport = { reviewCalibrationCase: vi.fn(async () => exampleCalibrationReview()) };
    const onReviewChange = vi.fn();
    await act(async () => { render(<CalibrationCasePane sessionId={SESSION} provider="claude_code" transport={transport} disabled={false} onReviewChange={onReviewChange} />); });
    expect(onReviewChange.mock.lastCall?.[0]?.review_id).toBe("f".repeat(32));
    await act(async () => { vi.advanceTimersByTime(15 * 60 * 1000); });
    expect(onReviewChange).toHaveBeenLastCalledWith(null);
    expect(screen.getByText(/receipt expired/)).toBeVisible();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Refresh case" })); });
    expect(transport.reviewCalibrationCase).toHaveBeenCalledTimes(2);
    expect(onReviewChange.mock.lastCall?.[0]?.expires_at).toBe("2040-01-01T00:30:00.000Z");
  });

  it("asks for a new review when the evidence-window size changes", async () => {
    const transport = { reviewCalibrationCase: vi.fn(async (_sid: string, _size: number, _signal?: AbortSignal) => exampleCalibrationReview()) };
    const onReviewChange = vi.fn();
    render(<CalibrationCasePane sessionId={SESSION} provider="claude_code" transport={transport} disabled={false} onReviewChange={onReviewChange} />);
    await screen.findByText(/Review the example module/);
    fireEvent.change(screen.getByRole("combobox", { name: "Evidence window" }), { target: { value: "6000" } });
    await waitFor(() => expect(transport.reviewCalibrationCase).toHaveBeenLastCalledWith(SESSION, 6000, expect.any(AbortSignal)));
    expect(onReviewChange.mock.calls.filter(([value]) => value === null)).toHaveLength(2);
  });

  it.each(["calibration_review_disabled", "calibration_review_consent_required"] as const)("explains %s without exposing provider errors", async (code) => {
    const transport = { reviewCalibrationCase: vi.fn(async () => { throw new TransportError("SYNTHETIC_PRIVATE_CANARY", 403, code); }) };
    const onReviewChange = vi.fn();
    render(<CalibrationCasePane sessionId={SESSION} provider="claude_code" transport={transport} disabled={false} onReviewChange={onReviewChange} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(code.endsWith("disabled") ? "PROMPT_ENHANCER_SESSION_READER=enabled" : "Redacted-content consent");
    expect(screen.queryByText("SYNTHETIC_PRIVATE_CANARY")).toBeNull();
    expect(onReviewChange).toHaveBeenLastCalledWith(null);
  });
});
