import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { JudgeOutcome, SessionInterpretation, SessionJudgments } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { ModelJudgePane } from "./ModelJudgePane";

const SESSION = "a".repeat(64);
const REPLACEMENT_SESSION = "c".repeat(64);
const EXAMPLE_MODEL_IDENTITY = "example.invalid/models/nyx13b-q4.gguf";
const STALE_SUMMARY = "A delayed reading for a session the reader has already left.";

function judgments(overrides: Partial<SessionJudgments> = {}): SessionJudgments {
  return {
    contract_version: "model-judge.v1" as SessionJudgments["contract_version"],
    session_id: SESSION,
    active_model_alias: "orca27b-iq3m",
    accepted_case_version: "calibration-case.v1",
    accepted_prompt_versions: ["judge-v4-complete-json-anchor-15k"],
    questions: {
      "prompt.task_definition_coverage": "Did the person say clearly what they wanted done?",
      "prompt.context_sufficiency": "Did the prompts carry the context the agent needed?",
      "outcome.verification_strategy_adequacy": "Was the work checked before it was called done?",
    },
    judgments: [
      { session_id: SESSION, metric_key: "prompt.task_definition_coverage", label: "high", model_alias: "orca27b-iq3m", model_identity: "x.gguf", prompt_version: "judge-v1", window_fingerprint: "b".repeat(64), judged_at: "2026-08-19T10:00:00Z" },
      { session_id: SESSION, metric_key: "prompt.context_sufficiency", label: "medium", model_alias: "orca27b-iq3m", model_identity: "x.gguf", prompt_version: "judge-v1", window_fingerprint: "b".repeat(64), judged_at: "2026-08-19T10:00:00Z" },
      { session_id: SESSION, metric_key: "outcome.verification_strategy_adequacy", label: "cannot_judge", model_alias: "orca27b-iq3m", model_identity: "x.gguf", prompt_version: "judge-v1", window_fingerprint: "b".repeat(64), judged_at: "2026-08-19T10:00:00Z" },
    ],
    caveat: "Model judgments are labels from a local model, stored apart from metrics; they are never metric values.",
    ...overrides,
  };
}

/** Synthetic judgments for the session that replaces the first one on screen. */
function replacementJudgments(sessionId = REPLACEMENT_SESSION): SessionJudgments {
  const shared = {
    session_id: sessionId,
    model_alias: "nyx13b-q4",
    model_identity: EXAMPLE_MODEL_IDENTITY,
    prompt_version: "judge-v1",
    window_fingerprint: "d".repeat(64),
    judged_at: "2040-03-04T08:30:00Z",
  };
  return {
    contract_version: "model-judge.v1" as SessionJudgments["contract_version"],
    session_id: sessionId,
    active_model_alias: "nyx13b-q4",
    accepted_case_version: "calibration-case.v1",
    accepted_prompt_versions: ["judge-v4-complete-json-anchor-15k"],
    questions: {
      "prompt.task_definition_coverage": "Did the person say clearly what they wanted done?",
      "prompt.context_sufficiency": "Did the prompts carry the context the agent needed?",
      "outcome.verification_strategy_adequacy": "Was the work checked before it was called done?",
    },
    judgments: [
      { ...shared, metric_key: "prompt.task_definition_coverage", label: "medium" },
      { ...shared, metric_key: "prompt.context_sufficiency", label: "high" },
      { ...shared, metric_key: "outcome.verification_strategy_adequacy", label: "low" },
    ],
    caveat: "Model judgments are labels from a local model, stored apart from metrics; they are never metric values.",
  };
}

const STALE_OUTCOME: JudgeOutcome = {
  contract_version: "model-judge.v1" as SessionJudgments["contract_version"],
  session_id: SESSION,
  model_alias: "orca27b-iq3m",
  judgments: [],
  raw_valid: true,
};

/** Fictional model prose, never a metric value. */
const STALE_READING: SessionInterpretation = {
  contract_version: "model-judge.v1",
  session_id: SESSION,
  model_alias: "orca27b-iq3m",
  summary: STALE_SUMMARY,
  prompt_version: "interpret-v2-complete-json",
  strengths: ["The goal was named in the first message."],
  improvements: ["Say which example file should change."],
  reframed_prompt: "Update docs/example/notes.md so the check runs.",
  caveat: "A local model wrote this reading; it is not a metric.",
  metrics_seen: 12,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((settle, fail) => { resolve = settle; reject = fail; });
  return { promise, resolve, reject };
}

describe("ModelJudgePane", () => {
  it("keeps stored labels after an invalid completion and lets the user retry", async () => {
    const judgeSessionWithModel = vi.fn()
      .mockRejectedValueOnce(new TransportError("SYNTHETIC_PRIVATE_CANARY", 502, "model_reply_invalid"))
      .mockResolvedValueOnce(STALE_OUTCOME);
    const getModelJudgments = vi.fn(async () => judgments());
    render(<ModelJudgePane sessionId={SESSION} transport={{ getModelJudgments, judgeSessionWithModel }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Judge again" }));
    expect(await screen.findByText(/incomplete or invalid reply.*Existing judgments were kept/)).toBeVisible();
    expect(screen.getByText("high")).toBeVisible();
    expect(screen.getByRole("button", { name: "Judge again" })).toBeEnabled();
    expect(getModelJudgments).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
    fireEvent.click(screen.getByRole("button", { name: "Judge again" }));
    expect(await screen.findByText("Judged by orca27b-iq3m.")).toBeVisible();
    expect(judgeSessionWithModel).toHaveBeenCalledTimes(2);
  });

  it("keeps the previous explanation when a regeneration is incomplete", async () => {
    const interpretSessionWithModel = vi.fn().mockResolvedValueOnce(STALE_READING)
      .mockRejectedValueOnce(new TransportError("SYNTHETIC_PRIVATE_CANARY", 502, "model_reply_invalid"));
    render(<ModelJudgePane sessionId={SESSION} transport={{ getModelJudgments: vi.fn(async () => judgments()), interpretSessionWithModel }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain this session" }));
    expect(await screen.findByText(STALE_SUMMARY)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Explain this session" }));
    expect(await screen.findByText(/incomplete or invalid explanation/)).toBeVisible();
    expect(screen.getByText(STALE_SUMMARY)).toBeVisible();
    expect(screen.getByRole("button", { name: "Explain this session" })).toBeEnabled();
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it("shows historical protocol eligibility without erasing the old labels", async () => {
    render(<ModelJudgePane sessionId={SESSION} transport={{
      getModelJudgments: vi.fn(async () => judgments({ accepted_prompt_versions: ["example-current-protocol"] })),
    }} />);
    expect(await screen.findByText("high")).toBeVisible();
    expect(screen.getAllByText(/Historical protocol · excluded from agreement/)).toHaveLength(3);
    expect(screen.getAllByText("judge-v1")).toHaveLength(3);
  });

  it("does not call an unreported protocol current", async () => {
    const { accepted_prompt_versions: _versions, ...legacy } = judgments();
    render(<ModelJudgePane sessionId={SESSION} transport={{ getModelJudgments: vi.fn(async () => legacy as SessionJudgments) }} />);
    expect(await screen.findByText("high")).toBeVisible();
    expect(screen.getAllByText("Protocol eligibility unavailable")).toHaveLength(3);
  });

  it("marks a missing window identity ineligible even with a current protocol", async () => {
    const data = judgments({ accepted_prompt_versions: ["judge-v1"] });
    data.judgments = data.judgments.map((row) => ({ ...row, window_fingerprint: "0".repeat(64) }));
    render(<ModelJudgePane sessionId={SESSION} transport={{ getModelJudgments: vi.fn(async () => data) }} />);
    expect(await screen.findByText("high")).toBeVisible();
    expect(screen.getAllByText("Window identity missing · excluded from agreement")).toHaveLength(3);
  });

  it.each([null, "no_active_model", "model_not_active"] as const)("classifies a 409 by its safe reason (%s) instead of claiming every conflict is a stopped model", async (reason) => {
    render(<ModelJudgePane sessionId={SESSION} transport={{
      getModelJudgments: vi.fn(async () => judgments()),
      judgeSessionWithModel: vi.fn().mockRejectedValue(new TransportError("synthetic conflict", 409, reason)),
    }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Judge again" }));
    expect(await screen.findByText(reason ? /No local model is active - activate one/ : /model judge is not available right now/)).toBeVisible();
    if (!reason) expect(screen.queryByText(/No local model is active - activate one/)).toBeNull();
  });

  it("shows one label per question per model, apart from metrics, with the caveat", async () => {
    const transport = { getModelJudgments: vi.fn(async () => judgments()), judgeSessionWithModel: vi.fn() };
    render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    await screen.findByText("What the local model thinks of this session");
    expect(screen.getByText("orca27b-iq3m · active")).toBeTruthy();
    expect(screen.getByText("high")).toBeTruthy();
    expect(screen.getByText("medium")).toBeTruthy();
    expect(screen.getByText("cannot judge")).toBeTruthy();
    expect(screen.getByText(/never metric values/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Judge again" })).toBeTruthy();
  });

  it("offers to judge now when nothing is stored and a model is active, then reloads", async () => {
    let current = judgments({ judgments: [] });
    const judgeSessionWithModel = vi.fn(async () => {
      current = judgments();
      return { contract_version: "model-judge.v1" as const, session_id: SESSION, model_alias: "orca27b-iq3m", judgments: current.judgments, raw_valid: true };
    });
    const transport = { getModelJudgments: vi.fn(async () => current), judgeSessionWithModel };
    render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    await screen.findByText(/judges new sessions automatically/);
    fireEvent.click(screen.getByRole("button", { name: "Judge now" }));
    await waitFor(() => expect(judgeSessionWithModel).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal)));
    await screen.findByText("high");
    expect(screen.getByText("Judged by orca27b-iq3m.")).toBeTruthy();
  });

  it("renders nothing when the judge lane is not available", async () => {
    const transport = { getModelJudgments: vi.fn(async () => { throw new TransportError("Local API request failed (404)", 404); }) };
    const { container } = render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    await waitFor(() => expect(transport.getModelJudgments).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector(".model-judge-pane")).toBeNull());
  });

  it("keeps a delayed judgment from landing on the session that replaced it", async () => {
    const pending = deferred<JudgeOutcome>();
    const judgeSessionWithModel = vi.fn(async () => pending.promise);
    const getModelJudgments = vi.fn(async (id: string) => (id === SESSION ? judgments({ judgments: [] }) : replacementJudgments()));
    const transport = { getModelJudgments, judgeSessionWithModel };
    const { rerender } = render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    await screen.findByText(/judges new sessions automatically/);
    fireEvent.click(screen.getByRole("button", { name: "Judge now" }));
    await screen.findByRole("button", { name: "Judging…" });
    expect(judgeSessionWithModel).toHaveBeenCalledWith(SESSION, expect.any(AbortSignal));

    rerender(<ModelJudgePane sessionId={REPLACEMENT_SESSION} transport={transport} />);
    await screen.findByText("nyx13b-q4 · active");
    // the replacement context is unlocked at once, while the old call is open
    expect(screen.getByRole("button", { name: "Judge again" })).toBeTruthy();

    await act(async () => {
      pending.resolve(STALE_OUTCOME);
      await pending.promise;
    });

    expect(screen.queryByText(/^Judged by/)).toBeNull();
    expect(getModelJudgments).toHaveBeenCalledTimes(2);
    expect(screen.getByText("nyx13b-q4 · active")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Judge again" })).toBeTruthy();
  });

  it("keeps a delayed explanation from landing after the transport is replaced", async () => {
    const pending = deferred<SessionInterpretation>();
    const first = {
      getModelJudgments: vi.fn(async () => judgments()),
      interpretSessionWithModel: vi.fn(async () => pending.promise),
    };
    const second = {
      getModelJudgments: vi.fn(async () => replacementJudgments(SESSION)),
      interpretSessionWithModel: vi.fn(async () => STALE_READING),
    };
    const { rerender } = render(<ModelJudgePane sessionId={SESSION} transport={first} />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain this session" }));
    await screen.findByRole("button", { name: "Explaining…" });

    rerender(<ModelJudgePane sessionId={SESSION} transport={second} />);
    await screen.findByText("nyx13b-q4 · active");
    expect(screen.getByRole("button", { name: "Explain this session" })).toBeTruthy();

    await act(async () => {
      pending.resolve(STALE_READING);
      await pending.promise;
    });

    expect(screen.queryByText(STALE_SUMMARY)).toBeNull();
    expect(second.interpretSessionWithModel).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Explain this session" })).toBeTruthy();
  });

  it("ignores a delayed first read for a session that has been replaced", async () => {
    const slow = deferred<SessionJudgments>();
    const getModelJudgments = vi.fn(async (id: string) => (id === SESSION ? slow.promise : replacementJudgments()));
    const transport = { getModelJudgments };
    const { rerender } = render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    await screen.findByText("Looking for model judgments…");

    rerender(<ModelJudgePane sessionId={REPLACEMENT_SESSION} transport={transport} />);
    await screen.findByText("nyx13b-q4 · active");

    await act(async () => {
      slow.resolve(judgments());
      await slow.promise;
    });

    expect(screen.getByText("nyx13b-q4 · active")).toBeTruthy();
    expect(screen.queryByText("orca27b-iq3m · active")).toBeNull();
  });

  it.each(["judge", "explain"] as const)("aborts a stale %s action and ignores its error after navigation", async (action) => {
    const pending = deferred<never>();
    const request = vi.fn((_id: string, _signal?: AbortSignal) => pending.promise);
    const transport = {
      getModelJudgments: vi.fn(async (id: string) => judgments({ session_id: id, judgments: [] })),
      judgeSessionWithModel: request,
      interpretSessionWithModel: request,
    };
    const view = render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: action === "judge" ? "Judge now" : "Explain this session" }));
    expect(screen.getByRole("button", { name: action === "judge" ? "Explain this session" : "Judge now" })).toBeDisabled();
    view.rerender(<ModelJudgePane sessionId={REPLACEMENT_SESSION} transport={transport} />);
    await screen.findByRole("button", { name: "Explain this session" });
    await act(async () => { pending.reject(new Error("example-late-error")); await pending.promise.catch(() => undefined); });
    expect(request.mock.calls[0][1]?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Explain this session" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Judge now" })).toBeEnabled();
    expect(screen.queryByText(/could not explain|not available right now/)).not.toBeInTheDocument();
  });

  it("retries the judgment read without starting model inference", async () => {
    const transport = { getModelJudgments: vi.fn().mockRejectedValueOnce(new Error("example-read-error")).mockResolvedValue(judgments()), judgeSessionWithModel: vi.fn() };
    render(<ModelJudgePane sessionId={SESSION} transport={transport} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry model judgments" }));
    expect(await screen.findByText("orca27b-iq3m · active")).toBeVisible();
    expect(transport.judgeSessionWithModel).not.toHaveBeenCalled();
  });

  it("does not display a judgment response belonging to another session", async () => {
    render(<ModelJudgePane sessionId={SESSION} transport={{ getModelJudgments: vi.fn(async () => replacementJudgments()) }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Model judgments could not be read.");
    expect(screen.queryByText("nyx13b-q4 · active")).not.toBeInTheDocument();
  });
});
