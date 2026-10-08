import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CalibrationProgress,
  CalibrationRating,
  CalibrationSample,
  JudgeAgreementReport,
  JudgeSweepStatus,
  RatingSubmission,
  RemoteAnnotationDisclosure,
  RemoteAnnotationResult,
  SessionTranscript,
} from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { CalibrationPage, safeCalibrationSample } from "./CalibrationPage";
import { exampleCalibrationReview } from "./calibrationFixtures.test-support";

const SESSION_A = "a".repeat(64);
const SESSION_B = "b".repeat(64);
const PROJECT = "c".repeat(64);
const METRICS = ["prompt.task_definition_coverage", "prompt.context_sufficiency", "outcome.verification_strategy_adequacy"];

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function sample(rated: Record<string, string[]> = {}): CalibrationSample {
  return {
    contract_version: "calibration-ratings.v1" as const,
    sample_id: "d".repeat(64),
    sample_version: "calibration-sample-v1",
    created_at: "2026-03-01T09:00:00Z",
    target_size: 96,
    metric_keys: METRICS,
    members: [
      { position: 0, session_id: SESSION_A, provider: "claude_code", project_id: PROJECT, project_display_name: "example-app", session_display_name: "Add retries to the uploader", started_at: "2026-03-01T09:00:00Z", rated_metric_keys: rated[SESSION_A] ?? [] },
      { position: 1, session_id: SESSION_B, provider: "codex", project_id: PROJECT, project_display_name: "example-app", session_display_name: null, started_at: null, rated_metric_keys: rated[SESSION_B] ?? [] },
    ],
  };
}

function progress(rated: number): CalibrationProgress {
  return {
    contract_version: "calibration-ratings.v1" as const,
    sample_id: "d".repeat(64),
    sample_size: 2,
    rated_sessions: rated,
    rater_count: rated > 0 ? 1 : 0,
    metrics: METRICS.map((metric_key) => ({ metric_key, rated_sessions: rated, low: 0, medium: rated, high: 0, cannot_judge: 0 })),
  };
}

const transcript: SessionTranscript = {
  contract_version: "session-transcript.v1",
  provider: "claude_code",
  session_id: SESSION_A,
  title: "Add retries to the uploader",
  turns: [{ role: "user", text: "Please add a retry", at: "2026-03-01T09:00:00Z", tool_name: null, truncated: false }],
  truncated: false,
  turn_count: 1,
} as unknown as SessionTranscript;

function agreement(overrides: Partial<JudgeAgreementReport> = {}): JudgeAgreementReport {
  return {
    contract_version: "model-judge.v1",
    model_alias: "example-local-model",
    judged_sessions: 0,
    excluded_judgments: 0,
    model_identity_ambiguous: false,
    accepted_prompt_versions: ["judge-v4-complete-json-anchor-15k"],
    metrics: [],
    caveat: "Judgments are opinions, never product metrics.",
    ...overrides,
  };
}

function sweep(overrides: Partial<JudgeSweepStatus> = {}): JudgeSweepStatus {
  return {
    contract_version: "model-judge.v1",
    running: false,
    total: 0,
    done: 0,
    failed: 0,
    ...overrides,
  };
}

function remoteDisclosure(overrides: Partial<RemoteAnnotationDisclosure> = {}): RemoteAnnotationDisclosure {
  return {
    contract_version: "annotation.v1",
    destination: "embedded central server (this machine)",
    redacted_windows_retained: true,
    pseudonymous_session_ids_retained: true,
    pseudonymous_project_ids_retained: true,
    raw_transcripts_sent: false,
    model_policy: "configured_active_model_at_submission",
    active_model_alias: "synthetic-central-model",
    ...overrides,
  };
}

function baseTransport(sampleValue: unknown = sample()) {
  return {
    getCalibrationSample: vi.fn(async () => sampleValue as CalibrationSample),
    submitCalibrationRatings: vi.fn(),
    getCalibrationRatings: vi.fn(async () => [] as CalibrationRating[]),
    getCalibrationProgress: vi.fn(async () => progress(0)),
    getCalibrationExport: vi.fn(),
    getSessionTranscript: vi.fn(async () => transcript),
    reviewCalibrationCase: vi.fn(async (sid: string, _budget?: number, _signal?: AbortSignal) => exampleCalibrationReview(sid)),
  };
}

async function acknowledgeReview() {
  const checkbox = await screen.findByRole("checkbox", { name: /I reviewed this case/ });
  await waitFor(() => expect(checkbox).toBeEnabled());
  fireEvent.click(checkbox);
}

function annotationTransport(
  annotateRemotely: (limit: number, signal?: AbortSignal) => Promise<RemoteAnnotationResult>,
) {
  return {
    ...baseTransport(),
    getModelJudgeAgreement: vi.fn(async () => agreement({ model_alias: null })),
    getModelJudgeSweep: vi.fn(async () => sweep()),
    getAnnotationAllowance: vi.fn(async () => ({
      contract_version: "annotation.v1" as const,
      agent_allowed: false,
      note: "Whatever model the agent runs on will see that content.",
    })),
    getRemoteAnnotationDisclosure: vi.fn(async () => remoteDisclosure()),
    annotateRemotely,
  };
}

describe("CalibrationPage", () => {
  it("explains excluded historical judgments without inventing agreement", async () => {
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement({
        excluded_judgments: 3,
        accepted_prompt_versions: ["example-current-protocol"],
        metrics: [{ metric_key: METRICS[0], pairs: 0, agreement_rate: null, cohen_kappa: null, state: "insufficient_data", reason: "no_comparable_reviewed_cases", unmatched_ratings: 1, abstained_pairs: 0 }],
      })),
      getModelJudgeSweep: vi.fn(async () => sweep()),
    };
    render(<CalibrationPage transport={transport} />);
    expect(await screen.findByText(/3 stored judgments excluded from current agreement/)).toBeVisible();
    const table = screen.getByRole("table");
    expect(within(table).queryByText("0%")).toBeNull();
    expect(within(table).getByText(/insufficient data/)).toBeVisible();
  });

  it("reports an invalid model completion with a retry and preserves blind ratings", async () => {
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement()),
      getModelJudgeSweep: vi.fn(async () => sweep()),
      judgeSessionWithModel: vi.fn().mockRejectedValue(new TransportError("SYNTHETIC_PRIVATE_CANARY", 502, "model_reply_invalid")),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(screen.getByRole("button", { name: "Judge this session" }));
    expect(await screen.findByText(/incomplete or invalid reply.*Existing judgments were kept/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Judge this session" })).toBeEnabled();
    expect(transport.submitCalibrationRatings).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it.each(["Judge this session", "Judge the whole sample", "Judge every session"])("uses the safe model-state reason for %s, not the private error message", async (action) => {
    const noModel = new TransportError("SYNTHETIC_PRIVATE_CANARY", 409, "no_active_model");
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement()),
      getModelJudgeSweep: vi.fn(async () => sweep()),
      judgeSessionWithModel: vi.fn().mockRejectedValue(noModel),
      startModelJudgeSweep: vi.fn().mockRejectedValue(noModel),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(await screen.findByRole("button", { name: action }));
    expect(await screen.findByText(/No local model is active - activate one/)).toBeVisible();
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it("shows an uncertain remote submission inside its dialog and blocks a blind duplicate", async () => {
    const remote = vi.fn().mockRejectedValue(new Error("SYNTHETIC_PRIVATE_CANARY"));
    render(<CalibrationPage transport={annotationTransport(remote)} />);
    fireEvent.click(await screen.findByRole("button", { name: /Annotate remotely/ }));
    const dialog = await screen.findByRole("dialog", { name: "Send sessions for remote annotation?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("could not be confirmed");
    expect(within(dialog).getByRole("button", { name: "Send" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeDisabled();
    expect(remote).toHaveBeenCalledOnce();
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps a save acknowledgment visible after the refreshed sample and ratings arrive", async () => {
    localStorage.setItem("prompt-enhancer.calibration.rater", "Example rater");
    const transport = {
      ...baseTransport(),
      submitCalibrationRatings: vi.fn(async () => progress(1)),
      getCalibrationSample: vi.fn(async () => sample()),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement);
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeVisible();
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Saved.")).toBeVisible();
  });

  it("requires loaded evidence and explicit review before saving the exact receipt", async () => {
    localStorage.setItem("prompt-enhancer.calibration.rater", "Example rater");
    const pending = deferred<ReturnType<typeof exampleCalibrationReview>>();
    const transport = { ...baseTransport(), reviewCalibrationCase: vi.fn(() => pending.promise), submitCalibrationRatings: vi.fn(async () => progress(1)) };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await act(async () => { pending.resolve(exampleCalibrationReview()); await pending.promise; });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(transport.submitCalibrationRatings).toHaveBeenCalledWith(expect.objectContaining({ session_id: SESSION_A, review_id: "f".repeat(32) }), expect.any(AbortSignal));
    expect(transport.getSessionTranscript).not.toHaveBeenCalled();
  });

  it("keeps the draft after a rejected receipt and requires a refreshed review to retry", async () => {
    localStorage.setItem("prompt-enhancer.calibration.rater", "Example rater");
    const transport = { ...baseTransport(), submitCalibrationRatings: vi.fn()
      .mockRejectedValueOnce(new TransportError("SYNTHETIC_PRIVATE_CANARY", 409, "calibration_review_expired"))
      .mockResolvedValue(progress(1)),
      reviewCalibrationCase: vi.fn().mockResolvedValueOnce(exampleCalibrationReview())
        .mockResolvedValue(exampleCalibrationReview(SESSION_A, { review_id: "e".repeat(32), case_fingerprint: "b".repeat(64) })),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    const high = screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement;
    fireEvent.click(high);
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/review receipt could not be confirmed/);
    expect(high).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
    fireEvent.click(screen.getByRole("button", { name: "Refresh case" }));
    await acknowledgeReview();
    expect(high).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(transport.submitCalibrationRatings).toHaveBeenLastCalledWith(expect.objectContaining({ review_id: "e".repeat(32), ratings: { [METRICS[0]]: "high" } }), expect.any(AbortSignal));
  });

  it("does not report an accepted save as unchanged when only its follow-up refresh fails", async () => {
    localStorage.setItem("prompt-enhancer.calibration.rater", "Example rater");
    const transport = {
      ...baseTransport(),
      submitCalibrationRatings: vi.fn(async () => progress(1)),
      getCalibrationSample: vi.fn().mockResolvedValueOnce(sample()).mockRejectedValue(new Error("example-refresh-failure")),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement);
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved, but the updated sample could not be loaded/)).toBeVisible();
    expect(screen.queryByText(/Nothing was changed/)).not.toBeInTheDocument();
    expect(transport.submitCalibrationRatings).toHaveBeenCalledTimes(1);
  });

  it("offers a bounded sample retry without needing to change the rater", async () => {
    const getCalibrationSample = vi.fn().mockRejectedValueOnce(new Error("example-load-failure")).mockResolvedValue(sample());
    render(<CalibrationPage transport={{ ...baseTransport(), getCalibrationSample }} />);
    await screen.findByText("The sample could not be verified.");
    fireEvent.click(screen.getByRole("button", { name: "Retry sample" }));
    expect(await screen.findByLabelText("Calibration sample")).toBeVisible();
    expect(getCalibrationSample).toHaveBeenCalledTimes(2);
  });

  it("disables unavailable judge and annotation commands even when their read APIs work", async () => {
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement()),
      getModelJudgeSweep: vi.fn(async () => sweep()),
      getAnnotationAllowance: vi.fn(async () => ({ contract_version: "annotation.v1" as const, agent_allowed: true, note: "Example allowance." })),
      getRemoteAnnotationDisclosure: vi.fn(async () => remoteDisclosure()),
    };
    render(<CalibrationPage transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    expect(await screen.findByRole("button", { name: "Judge this session" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Judge the whole sample" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Judge every session" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Agent annotation is ON/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Copy agent instructions" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeDisabled();
  });

  it("does not publish a pending save into a replacement transport", async () => {
    localStorage.setItem("prompt-enhancer.calibration.rater", "Example rater");
    const pending = deferred<CalibrationProgress>();
    const submitCalibrationRatings = vi.fn((_request: RatingSubmission, _signal?: AbortSignal) => pending.promise);
    const first = { ...baseTransport(), submitCalibrationRatings };
    const view = render(<CalibrationPage transport={first} />);
    fireEvent.click(await screen.findByRole("button", { name: "Next unrated" }));
    fireEvent.click(screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement);
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByLabelText("Rater name")).toBeDisabled();
    view.rerender(<CalibrationPage transport={baseTransport()} />);
    await screen.findByLabelText("Calibration sample");
    await act(async () => { pending.resolve(progress(1)); await pending.promise; });
    expect(submitCalibrationRatings.mock.calls[0][1]?.aborted).toBe(true);
    expect(first.getCalibrationSample).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
  });

  it("strictly validates every sample and member field used by the page", () => {
    const validWithUnknownLabels = sample();
    validWithUnknownLabels.members[0] = {
      ...validWithUnknownLabels.members[0],
      project_display_name: undefined,
      session_display_name: null,
      started_at: null,
    };
    const validUnicodeLabels = sample();
    validUnicodeLabels.members[0] = {
      ...validUnicodeLabels.members[0],
      project_display_name: "🚀".repeat(100),
      session_display_name: "🧪".repeat(150),
    };
    expect(safeCalibrationSample(sample())).toBe(true);
    expect(safeCalibrationSample(validWithUnknownLabels)).toBe(true);
    expect(safeCalibrationSample(validUnicodeLabels)).toBe(true);

    const first = sample().members[0];
    const malformed: unknown[] = [
      { ...sample(), contract_version: "other" },
      { ...sample(), sample_id: "not-a-pseudonym" },
      { ...sample(), sample_version: "" },
      { ...sample(), created_at: "not-a-date" },
      { ...sample(), created_at: "2026-03-01T09:00:00" },
      { ...sample(), created_at: "2026-02-31T09:00:00Z" },
      { ...sample(), target_size: 0 },
      { ...sample(), metric_keys: [...METRICS, METRICS[0]] },
      { ...sample(), metric_keys: [METRICS[0], null] },
      { ...sample(), metric_keys: [] },
      { ...sample(), metric_keys: ["not-supported-by-this-contract"] },
      { ...sample(), members: [{ ...first, position: -1 }] },
      { ...sample(), members: [{ ...first, session_id: "nope" }] },
      { ...sample(), members: [{ ...first, provider: "other" }] },
      { ...sample(), members: [{ ...first, project_id: null }] },
      { ...sample(), members: [{ ...first, project_display_name: { trim: "not-a-function" } }] },
      { ...sample(), members: [{ ...first, session_display_name: 7 }] },
      { ...sample(), members: [{ ...first, started_at: "not-a-date" }] },
      { ...sample(), members: [{ ...first, started_at: "2026-03-01T09:00:00" }] },
      { ...sample(), members: [{ ...first, rated_metric_keys: ["not-in-the-sample"] }] },
      { ...sample(), members: [{ ...first, rated_metric_keys: [METRICS[0], METRICS[0]] }] },
      { ...sample(), members: [{ ...first }, { ...first, position: 1 }] },
      { ...sample(), members: [{ ...first }, { ...first, session_id: SESSION_B }] },
    ];
    for (const value of malformed) expect(safeCalibrationSample(value)).toBe(false);
  });

  it("rejects a malformed member before rendering can access it", async () => {
    const invalid = {
      ...sample(),
      members: [{ ...sample().members[0], project_display_name: { trim: "not-a-function" } }],
    };
    render(<CalibrationPage transport={baseTransport(invalid)} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The sample could not be verified.");
    expect(screen.queryByLabelText("Calibration sample")).not.toBeInTheDocument();
  });

  it("lists the frozen sample, rates a session blind, and advances", async () => {
    let current = sample();
    const submitCalibrationRatings = vi.fn(async (_request: RatingSubmission) => {
      current = sample({ [SESSION_A]: METRICS });
      return progress(1);
    });
    const ratings: CalibrationRating[] = [];
    const transport = {
      ...baseTransport(),
      getCalibrationSample: vi.fn(async (_raterLabel: string | null, _signal?: AbortSignal) => current),
      submitCalibrationRatings,
      getCalibrationRatings: vi.fn(async () => ratings),
      getCalibrationProgress: vi.fn(async () => progress(0)),
      getCalibrationExport: vi.fn(async () => ({ contract_version: "calibration-ratings.v1" as const, sample_id: "d".repeat(64), sample_version: "calibration-sample-v1", rating_version: "calibration-rating-v1", exported_at: "2026-03-01T10:00:00Z", rows: [] })),
      getSessionTranscript: vi.fn(async () => transcript),
    };
    render(<CalibrationPage transport={transport} />);

    await screen.findByText("Add retries to the uploader", { selector: ".calibration__item-title" });
    expect(screen.getByText(/2 sessions · frozen sample/)).toBeTruthy();
    // Rater name is required and stored locally.
    const rater = screen.getByLabelText("Rater name");
    fireEvent.change(rater, { target: { value: "Owner" } });
    fireEvent.blur(rater);
    expect(localStorage.getItem("prompt-enhancer.calibration.rater")).toBe("Owner");

    await waitFor(() => expect(transport.getCalibrationSample.mock.calls.map((call) => call[0])).toContain("Owner"));
    fireEvent.click(await screen.findByRole("button", { name: /Next unrated/ }));
    await screen.findByRole("heading", { level: 2, name: "Add retries to the uploader" });
    // The reader shows the session; no metric value for it is rendered anywhere.
    await waitFor(() => expect(transport.reviewCalibrationCase).toHaveBeenCalledWith(SESSION_A, 15000, expect.any(AbortSignal)));
    expect(transport.getSessionTranscript).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(/0\.\d\d/);

    fireEvent.click(screen.getByLabelText("Task definition").querySelector("input[value='high']") as HTMLInputElement);
    fireEvent.click(screen.getByLabelText("Context given").querySelector("input[value='cannot_judge']") as HTMLInputElement);
    await acknowledgeReview();
    fireEvent.click(screen.getByRole("button", { name: "Save and next" }));
    await waitFor(() => expect(submitCalibrationRatings).toHaveBeenCalledTimes(1));
    expect(submitCalibrationRatings.mock.calls[0][0]).toEqual({
      rater_label: "Owner",
      session_id: SESSION_A,
      review_id: "f".repeat(32),
      ratings: { "prompt.task_definition_coverage": "high", "prompt.context_sufficiency": "cannot_judge" },
    });
    // Advances to the next unrated member (the Codex one, titled by its short id).
    await screen.findByRole("heading", { level: 2, name: `Session ${SESSION_B.slice(0, 8)}` });
  });

  it("explains an empty catalog and an unavailable runtime", async () => {
    const base = {
      ...baseTransport(),
      submitCalibrationRatings: vi.fn(),
      getCalibrationRatings: vi.fn(async () => []),
      getCalibrationProgress: vi.fn(async () => progress(0)),
      getCalibrationExport: vi.fn(),
      getSessionTranscript: vi.fn(),
    };
    const { unmount } = render(
      <CalibrationPage transport={{ ...base, getCalibrationSample: vi.fn(async () => { throw new TransportError("empty", 409); }) }} />,
    );
    await screen.findByText(/No sessions are indexed yet/);
    unmount();
    render(
      <CalibrationPage transport={{ ...base, getCalibrationSample: vi.fn(async () => { throw new TransportError("nope", 404); }) }} />,
    );
    await screen.findByText(/not available in this runtime/);
  });

  it("does not let an earlier polling load overwrite a command result", async () => {
    const intervalSpy = vi.spyOn(window, "setInterval");
    const stale = deferred<JudgeSweepStatus>();
    let sweepLoadCount = 0;
    const getModelJudgeSweep = vi.fn((_signal?: AbortSignal) => {
      sweepLoadCount += 1;
      return sweepLoadCount === 1 ? Promise.resolve(sweep()) : stale.promise;
    });
    const startModelJudgeSweep = vi.fn(async (_signal?: AbortSignal) => sweep({ running: true, total: 2 }));
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement()),
      getModelJudgeSweep,
      startModelJudgeSweep,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByRole("heading", { level: 2, name: "How often does the local model agree with you?" });
    const poll = intervalSpy.mock.calls.find((call) => call[1] === 15000)?.[0];
    act(() => {
      if (typeof poll !== "function") throw new Error("judge polling interval was not installed");
      poll();
    });
    await waitFor(() => expect(getModelJudgeSweep).toHaveBeenCalledTimes(2));
    const staleSignal = getModelJudgeSweep.mock.calls[1][0];

    fireEvent.click(screen.getByRole("button", { name: "Judge the whole sample" }));
    await screen.findByText("Judging 2 sessions in the background.");
    expect(startModelJudgeSweep).toHaveBeenCalledWith(expect.any(AbortSignal), "sample");
    expect(staleSignal?.aborted).toBe(true);
    expect(screen.getByText(/Sweep running: 0\/2/)).toBeInTheDocument();

    await act(async () => {
      stale.resolve(sweep());
      await stale.promise;
    });
    expect(screen.getByText(/Sweep running: 0\/2/)).toBeInTheDocument();
    expect(screen.getByText("Judging 2 sessions in the background.")).toBeInTheDocument();
  });

  it("does not let the polling interval supersede a pending command", async () => {
    const intervalSpy = vi.spyOn(window, "setInterval");
    const pending = deferred<JudgeSweepStatus>();
    const getModelJudgeAgreement = vi.fn(async () => agreement());
    const getModelJudgeSweep = vi.fn(async () => sweep());
    const startModelJudgeSweep = vi.fn((_signal?: AbortSignal) => pending.promise);
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement,
      getModelJudgeSweep,
      startModelJudgeSweep,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByRole("heading", { level: 2, name: "How often does the local model agree with you?" });
    const poll = intervalSpy.mock.calls.find((call) => call[1] === 15000)?.[0];
    fireEvent.click(screen.getByRole("button", { name: "Judge the whole sample" }));
    await waitFor(() => expect(startModelJudgeSweep).toHaveBeenCalledTimes(1));
    const commandSignal = startModelJudgeSweep.mock.calls[0][0];

    await act(async () => {
      if (typeof poll !== "function") throw new Error("judge polling interval was not installed");
      poll();
      await Promise.resolve();
    });
    expect(commandSignal?.aborted).toBe(false);
    expect(getModelJudgeAgreement).toHaveBeenCalledTimes(1);
    expect(getModelJudgeSweep).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve(sweep({ running: true, total: 3 }));
      await pending.promise;
    });
    expect(screen.getByText(/Sweep running: 0\/3/)).toBeInTheDocument();
    expect(screen.getByText("Judging 3 sessions in the background.")).toBeInTheDocument();
  });

  it("aborts an owned judge command on unmount and ignores its late result", async () => {
    const pending = deferred<JudgeSweepStatus>();
    const startModelJudgeSweep = vi.fn((_signal?: AbortSignal) => pending.promise);
    const transport = {
      ...baseTransport(),
      getModelJudgeAgreement: vi.fn(async () => agreement()),
      getModelJudgeSweep: vi.fn(async () => sweep()),
      startModelJudgeSweep,
    } as never;
    const view = render(<CalibrationPage transport={transport} />);

    fireEvent.click(await screen.findByRole("button", { name: "Judge the whole sample" }));
    await waitFor(() => expect(startModelJudgeSweep).toHaveBeenCalledTimes(1));
    const commandSignal = startModelJudgeSweep.mock.calls[0][0];
    expect(commandSignal?.aborted).toBe(false);
    view.unmount();
    expect(commandSignal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve(sweep({ running: true, total: 4 }));
      await pending.promise;
    });
  });

  it("aborts a remote command and unlocks confirmation when the transport context changes", async () => {
    const pending = deferred<RemoteAnnotationResult>();
    const firstRemote = vi.fn((_limit: number, _signal?: AbortSignal) => pending.promise);
    const secondRemote = vi.fn(async () => ({
      contract_version: "annotation.v1" as const,
      destination: "second synthetic destination",
      submitted: 2,
      annotated: 2,
      model_identity: "second-synthetic-model",
      stored_locally_as: "central:second-synthetic-model",
    }));
    const view = render(<CalibrationPage transport={annotationTransport(firstRemote)} />);
    await screen.findByText("More ways to annotate");

    fireEvent.click(screen.getByRole("button", { name: /Annotate remotely/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Send" }));
    await waitFor(() => expect(firstRemote).toHaveBeenCalledTimes(1));
    const firstSignal = firstRemote.mock.calls[0][1];
    expect(firstSignal?.aborted).toBe(false);

    const secondTransport = annotationTransport(secondRemote);
    view.rerender(<CalibrationPage transport={secondTransport} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(firstSignal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeEnabled();

    await act(async () => {
      pending.resolve({
        contract_version: "annotation.v1",
        destination: "stale destination",
        submitted: 1,
        annotated: 1,
        model_identity: "stale-model",
        stored_locally_as: "central:stale-model",
      });
      await pending.promise;
    });
    expect(screen.queryByText(/stale destination/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /Annotate remotely/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Send" }));
    await screen.findByText(/Sent 2 sessions to second synthetic destination/);
    expect(screen.getByText("central:second-synthetic-model")).toBeInTheDocument();

    view.rerender(<CalibrationPage transport={annotationTransport(vi.fn())} />);
    await waitFor(() => expect(screen.queryByText(/second synthetic destination/)).not.toBeInTheDocument());
    expect(screen.queryByText("central:second-synthetic-model")).not.toBeInTheDocument();
  });

  it("gates the agent path on the allowance and confirms before annotating remotely", async () => {
    const agreement = {
      contract_version: "model-judge.v1",
      model_alias: null,
      judged_sessions: 0,
      metrics: [],
      caveat: "Judgments are opinions, never product metrics.",
    };
    let allowed = false;
    const setAnnotationAllowance = vi.fn(async (next: boolean, _signal?: AbortSignal) => {
      allowed = next;
      return { contract_version: "annotation.v1" as const, agent_allowed: allowed, note: "Whatever model the agent runs on will see that content." };
    });
    const annotateRemotely = vi.fn(async (_limit: number, _signal?: AbortSignal) => ({
      contract_version: "annotation.v1" as const,
      destination: "embedded central server (this machine)",
      submitted: 2,
      annotated: 2,
      model_identity: "orca27b-iq3m",
      stored_locally_as: "central:orca27b-iq3m",
    }));
    const transport = {
      getCalibrationSample: vi.fn(async () => sample()),
      submitCalibrationRatings: vi.fn(),
      getCalibrationRatings: vi.fn(async () => []),
      getCalibrationProgress: vi.fn(async () => progress(0)),
      getCalibrationExport: vi.fn(),
      getSessionTranscript: vi.fn(async () => transcript),
      getModelJudgeAgreement: vi.fn(async () => agreement),
      getModelJudgeSweep: vi.fn(async () => ({ contract_version: "model-judge.v1", running: false, total: 0, done: 0, failed: 0 })),
      getAnnotationAllowance: vi.fn(async () => ({ contract_version: "annotation.v1" as const, agent_allowed: allowed, note: "Whatever model the agent runs on will see that content." })),
      setAnnotationAllowance,
      getAnnotationMetaprompt: vi.fn(),
      getRemoteAnnotationDisclosure: vi.fn(async () => remoteDisclosure({ active_model_alias: "orca27b-iq3m" })),
      annotateRemotely,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByText(/More ways to annotate/);

    // Allowance off: the toggle invites, no copy button yet.
    const toggle = screen.getByRole("button", { name: /Allow agent annotation/ });
    expect(screen.queryByRole("button", { name: /Copy agent instructions/ })).toBeNull();
    fireEvent.click(toggle);
    await screen.findByRole("button", { name: /Agent annotation is ON/ });
    expect(setAnnotationAllowance).toHaveBeenCalledWith(true, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: /Copy agent instructions/ })).toBeTruthy();

    // Annotate remotely: the safe action owns initial focus, traps it, and Escape sends nothing.
    const trigger = screen.getByRole("button", { name: /Annotate remotely/ });
    trigger.focus();
    fireEvent.click(trigger);
    expect(annotateRemotely).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", { name: "Send sessions for remote annotation?" });
    expect(dialog).toHaveAccessibleDescription("Nothing is sent until you explicitly choose Send.");
    expect(screen.getAllByText(/embedded central server \(this machine\)/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/configured active model at submission time/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/orca27b-iq3m/i).length).toBeGreaterThan(0);
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toHaveFocus());
    const send = screen.getByRole("button", { name: "Send" });
    send.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Cancel remote annotation" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(annotateRemotely).not.toHaveBeenCalled();

    // Cancel is also inert and restores the opener.
    fireEvent.click(trigger);
    const reopenedCancel = await screen.findByRole("button", { name: "Cancel" });
    fireEvent.click(reopenedCancel);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(annotateRemotely).not.toHaveBeenCalled();

    // Only the explicit Send action crosses the remote boundary.
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("button", { name: "Send" }));
    await waitFor(() => expect(annotateRemotely).toHaveBeenCalledWith(5, expect.any(AbortSignal)));
    await screen.findByText(/Sent 2 sessions to embedded central server/);
    await screen.findByText("central:orca27b-iq3m");
  });

  it.each([
    ["unavailable", vi.fn(async () => { throw new TransportError("unavailable", 503); })],
    ["malformed", vi.fn(async () => ({ ...remoteDisclosure(), raw_transcripts_sent: true }))],
  ])("fails closed when the remote disclosure is %s", async (_case, getRemoteAnnotationDisclosure) => {
    const annotateRemotely = vi.fn();
    const transport = {
      ...annotationTransport(annotateRemotely),
      getRemoteAnnotationDisclosure,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByText("More ways to annotate");
    await screen.findByRole("alert");

    expect(screen.getByText(/pre-send disclosure could not be verified/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(annotateRemotely).not.toHaveBeenCalled();
  });

  it("does not get stuck loading when the runtime omits the disclosure method", async () => {
    const annotateRemotely = vi.fn();
    const transport = {
      ...annotationTransport(annotateRemotely),
      getRemoteAnnotationDisclosure: undefined,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByRole("alert");

    expect(screen.queryByText(/Verifying the remote annotation destination/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeDisabled();
    expect(annotateRemotely).not.toHaveBeenCalled();
  });

  it("shows a verified destination but keeps sending disabled when no configured model is active", async () => {
    const annotateRemotely = vi.fn();
    const getRemoteAnnotationDisclosure = vi.fn()
      .mockResolvedValueOnce(remoteDisclosure({ active_model_alias: null }))
      .mockResolvedValue(remoteDisclosure({ active_model_alias: "synthetic-central-model" }));
    const transport = {
      ...annotationTransport(annotateRemotely),
      getRemoteAnnotationDisclosure,
    } as never;

    render(<CalibrationPage transport={transport} />);
    await screen.findByText("More ways to annotate");
    await screen.findByText(/No model is active there now/i);

    expect(screen.getByText("embedded central server (this machine)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeDisabled();
    expect(annotateRemotely).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Check for an active model/ }));
    await screen.findByText("synthetic-central-model");
    expect(getRemoteAnnotationDisclosure).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Annotate remotely/ })).toBeEnabled();
  });
});
