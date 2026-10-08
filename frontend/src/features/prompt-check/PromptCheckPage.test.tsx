import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PromptCheckRecord, PromptCheckResult } from "../../shared/api/contracts";
import { TransportError } from "../../shared/api/httpTransport";
import { PromptCheckPage, promptReadingLabel, shortName } from "./PromptCheckPage";
import { PromptMetricRadar, PromptMetricTrend, promptMetricQualityValue } from "./promptCheckPlots";

const CHECK = "c".repeat(64);

function reading(key: string, value: number | null, extra: Partial<PromptCheckResult["metrics"][number]> = {}): PromptCheckResult["metrics"][number] {
  return {
    key,
    display_name: shortName(key),
    description: "",
    state: value === null ? "unknown" : "known",
    value,
    numerator: value === null ? null : Math.round(value * 3),
    denominator: value === null ? null : 3,
    higher_is_better: true,
    explanation_code: value === null ? "constraints_unobserved" : "cues",
    cues: value === null ? [] : [{ code: "task.action", label: "what to do", status: "detected", count: 1 }, { code: "task.outcome", label: "the intended result", status: "missing", count: 0 }],
    ...extra,
  };
}

function result(overrides: Partial<PromptCheckResult> = {}): PromptCheckResult {
  return {
    contract_version: "prompt-check.v1" as const,
    check_id: CHECK,
    created_at: "2026-08-19T12:00:00Z",
    provider: "other",
    agent_model: null,
    metrics: [
      reading("prompt.task_definition_coverage", 2 / 3),
      reading("prompt.problem_evidence_quality", null),
      reading("prompt.context_sufficiency", 1 / 3),
      reading("prompt.constraint_precision", null),
      reading("prompt.acceptance_testability", 1),
      reading("prompt.deliverable_contract", 0),
    ],
    context: {
      task_type: "implement", language: "en", prompt_chars: 120, prompt_words: 20, sentence_count: 2, bullet_count: 0, question_count: 0,
      file_references: 1, code_identifiers: 2, urls: 0, prior_context_supplied: 1, depends_on_prior_context: true, verification_requested: false,
      missing_elements: ["how the result should be verified (tests, build, inspection)"],
    },
    commentary: {
      state: "ok",
      model_alias: "orca27b-iq3m",
      prompt_version: "prompt-check-commentary-v1",
      findings: [{ aspect: "acceptance", severity: "high", why: "No done-when.", suggestion: "Say which test must pass." }],
      reformulated_prompt: "Add retries to the uploader in client.py; done when pytest passes.",
      reformulated_elements: [{ element: "acceptance", original: null, suggested: "Done when pytest tests/test_upload.py passes." }],
      notes: null,
      caveat: "Commentary and rewrites come from a local model; they are suggestions, not metrics, and may be wrong.",
    },
    summary: "Prompt check - Task definition: 2/3 (missing: the intended result).",
    engine_version: "coaching-rules-en-pl-2",
    rubric_version: "coaching-observables-rubric-2",
    dashboard_path: `/prompt-checks/${CHECK}`,
    other_metric_families_note: "Collaboration, logic and outcome metrics need the agent's replies.",
    ...overrides,
  };
}

function record(): PromptCheckRecord {
  const r = result();
  return {
    check_id: CHECK, created_at: r.created_at, provider: "claude_code", agent_model: "claude-opus-5", language: "en", task_type: "implement",
    prompt_chars: 120, prior_message_count: 1, depends_on_prior_context: true, verification_requested: false, metrics: r.metrics,
    commentary_state: "ok", commentary_model_alias: "orca27b-iq3m", prompt_fingerprint: "f".repeat(64),
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

describe("PromptCheckPage", () => {
  it("explains the empty prompt prerequisite and enables the check when text is present", () => {
    render(<PromptCheckPage navigate={vi.fn()} transport={{ checkPrompt: vi.fn(), getPromptCheck: vi.fn(), getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [], limit: 60, offset: 0 })) }} />);
    const submit = screen.getByRole("button", { name: "Check prompt" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription(/enter a prompt before running the check/i);

    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Add a bounded retry to the example uploader." } });
    expect(submit).toBeEnabled();
    expect(submit).not.toHaveAttribute("aria-describedby");
  });

  it.each([
    [reading("example", 0.5, { numerator: 1, denominator: 2 }), "1/2"],
    [reading("example", 0.5, { numerator: 3, denominator: null }), "0.5"],
    [reading("example", 0.5, { numerator: null, denominator: null }), "0.5"],
    [reading("example", null, { numerator: 0, denominator: 3 }), "unknown"],
    [reading("example", Number.NaN, { numerator: null, denominator: null }), "Value unavailable"],
  ])("shows a truthful metric label without fabricating a fraction", (metric, expected) => {
    expect(promptReadingLabel(metric)).toBe(expected);
  });

  it("retries a failed history load without submitting the draft", async () => {
    const getPromptCheckHistory = vi.fn().mockRejectedValueOnce(new Error("example-history-error")).mockResolvedValue({ checks: [record()], limit: 60, offset: 0 });
    const checkPrompt = vi.fn();
    render(<PromptCheckPage navigate={vi.fn()} transport={{ checkPrompt, getPromptCheckHistory, getPromptCheck: vi.fn() }} />);
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Example unsent draft" } });
    await screen.findByText("The history could not be read.");
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(await screen.findByText(/claude_code · claude-opus-5/)).toBeVisible();
    expect(screen.getByLabelText("Prompt to check")).toHaveValue("Example unsent draft");
    expect(checkPrompt).not.toHaveBeenCalled();
  });

  it("does not let an old history load erase a newly stored check", async () => {
    const pending = deferred<{ contract_version: "prompt-check.v1"; checks: PromptCheckRecord[]; limit: number; offset: number }>();
    const getPromptCheckHistory = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue({ checks: [record()], limit: 60, offset: 0 });
    render(<PromptCheckPage navigate={vi.fn()} transport={{ checkPrompt: vi.fn(async () => result()), getPromptCheckHistory, getPromptCheck: vi.fn() }} />);
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Example new check" } });
    fireEvent.click(screen.getByRole("button", { name: "Check prompt" }));
    await screen.findByText(/claude_code · claude-opus-5/);
    await act(async () => { pending.resolve({ contract_version: "prompt-check.v1", checks: [], limit: 60, offset: 0 }); await pending.promise; });
    expect(screen.getByText(/claude_code · claude-opus-5/)).toBeVisible();
    expect(screen.queryByText(/No check yet/)).not.toBeInTheDocument();
  });

  it("aborts a check when its session context changes and ignores the late result", async () => {
    const pending = deferred<PromptCheckResult>();
    const checkPrompt = vi.fn((_request: unknown, _signal?: AbortSignal) => pending.promise);
    const transport = { checkPrompt, getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [], limit: 60, offset: 0 })), getPromptCheck: vi.fn() };
    const view = render(<PromptCheckPage navigate={vi.fn()} sessionId={"a".repeat(64)} transport={transport} />);
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Example context-specific check" } });
    fireEvent.click(screen.getByRole("button", { name: "Check prompt" }));
    view.rerender(<PromptCheckPage navigate={vi.fn()} sessionId={"b".repeat(64)} transport={transport} />);
    await act(async () => { pending.resolve(result()); await pending.promise; });
    expect(checkPrompt.mock.calls[0][1]?.aborted).toBe(true);
    expect(screen.queryByRole("heading", { name: "Result" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check prompt" })).toBeEnabled();
  });

  it("keeps the runtime-unavailable boundary accessible and explains how to use the feature", async () => {
    render(<PromptCheckPage navigate={vi.fn()} transport={{ checkPrompt: vi.fn(), getPromptCheck: vi.fn(), getPromptCheckHistory: vi.fn().mockRejectedValue(new TransportError("unavailable", 404)) }} />);
    await screen.findByText("Prompt checks are not available in this runtime.");
    expect(screen.getByRole("heading", { name: "Check a prompt", level: 1 })).toBeVisible();
    expect(screen.getByText(/Open the local application/)).toBeVisible();
  });

  it("checks a pasted prompt with earlier turns and shows cues, commentary, reformulation and history", async () => {
    const checkPrompt = vi.fn(async (_request: { prompt: string; prior_messages?: { role: string; content: string }[] | null; want_commentary?: boolean }) => result());
    const transport = {
      checkPrompt,
      getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [record()], limit: 60, offset: 0 })),
      getPromptCheck: vi.fn(async () => record()),
    };
    const navigate = vi.fn();
    render(<PromptCheckPage navigate={navigate} transport={transport} />);
    await screen.findByText("Your checks over time");
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Add retries to the uploader" } });
    fireEvent.change(screen.getByLabelText("Earlier turns"), { target: { value: "user: we looked at it yesterday\nassistant: the loop is in client.py" } });
    fireEvent.click(screen.getByRole("button", { name: "Check prompt" }));
    await waitFor(() => expect(checkPrompt).toHaveBeenCalledTimes(1));
    const request = checkPrompt.mock.calls[0][0];
    expect(request.prompt).toBe("Add retries to the uploader");
    expect(request.prior_messages).toEqual([{ role: "user", content: "we looked at it yesterday" }, { role: "assistant", content: "the loop is in client.py" }]);
    expect(request.want_commentary).toBe(true);
    await screen.findByText("Result");
    expect(screen.getAllByText(/the intended result/).length).toBeGreaterThan(0);
    expect(screen.getByText("Say which test must pass.")).toBeTruthy();
    expect(screen.getByText(/Add retries to the uploader in client.py; done when pytest passes./)).toBeTruthy();
    expect(screen.getByText(/model output, not a metric/)).toBeTruthy();
    expect(screen.getByRole("img", { name: "Prompt metric radar" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Prompt metric trend across checks" })).toBeTruthy();
    expect(screen.getByText(/claude_code · claude-opus-5/)).toBeTruthy();
  });

  it("keeps a current result visible while a linked stored check loads", async () => {
    const pending = deferred<PromptCheckRecord>();
    const transport = {
      checkPrompt: vi.fn(async () => result()),
      getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [], limit: 60, offset: 0 })),
      getPromptCheck: vi.fn(() => pending.promise),
    };
    const view = render(<PromptCheckPage navigate={vi.fn()} transport={transport} />);
    await screen.findByText(/No check yet/);
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Add a bounded retry" } });
    fireEvent.click(screen.getByRole("button", { name: "Check prompt" }));
    await screen.findByRole("heading", { name: "Result" });

    view.rerender(<PromptCheckPage checkId={CHECK} navigate={vi.fn()} transport={transport} />);
    expect(screen.getByRole("heading", { name: "Result" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading stored check…");

    await act(async () => {
      pending.resolve(record());
      await pending.promise;
    });
    expect(await screen.findByRole("region", { name: "Stored check" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Result" })).toBeNull();
  });

  it("distinguishes a missing stored check from a read error and retries both", async () => {
    const pending = deferred<PromptCheckRecord>();
    const getPromptCheck = vi.fn()
      .mockImplementationOnce(() => pending.promise)
      .mockRejectedValueOnce(new TransportError("read failed", 500))
      .mockResolvedValueOnce(record());
    const transport = {
      checkPrompt: vi.fn(),
      getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [], limit: 60, offset: 0 })),
      getPromptCheck,
    };
    render(<PromptCheckPage checkId={CHECK} navigate={vi.fn()} transport={transport} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading stored check…");

    await act(async () => {
      pending.reject(new TransportError("missing", 404));
      await pending.promise.catch(() => undefined);
    });
    expect(await screen.findByRole("status")).toHaveTextContent("No stored check was found for this link.");
    fireEvent.click(screen.getByRole("button", { name: "Retry stored check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The stored check could not be read.");
    fireEvent.click(screen.getByRole("button", { name: "Retry stored check" }));
    expect(await screen.findByRole("region", { name: "Stored check" })).toBeInTheDocument();
    expect(getPromptCheck).toHaveBeenCalledTimes(3);
  });

  it("uses the same quality orientation for lower-is-better radar labels, tooltips, and trends", () => {
    const { container } = render(
      <>
        <PromptMetricRadar readings={[{ key: "risk", label: "Risk", value: 0.1, higherIsBetter: false }]} />
        <PromptMetricTrend series={[{
          key: "risk",
          label: "Risk",
          higherIsBetter: false,
          points: [{ x: 0, value: 0.1, at: "2026-08-19T12:00:00Z" }],
        }]} />
      </>,
    );

    expect(promptMetricQualityValue(0.1, false)).toBeCloseTo(0.9);
    expect(container).toHaveTextContent("90% quality (raw 10%; lower is better)");
    expect(container).toHaveTextContent("Risk · quality (raw lower is better)");
    expect(Number(container.querySelector(".prompt-plot--radar .prompt-plot__dot")?.getAttribute("cy"))).toBeLessThan(60);
    expect(Number(container.querySelector(".prompt-plot--trend .prompt-plot__series circle")?.getAttribute("cy"))).toBeLessThan(50);
  });

  it("explains a missing model and hides itself when the feature is unavailable", async () => {
    const transport = {
      checkPrompt: vi.fn(async () => result({ commentary: { state: "no_active_model", model_alias: null, prompt_version: "v", findings: [], reformulated_prompt: null, reformulated_elements: [], notes: null, caveat: "c" } })),
      getPromptCheckHistory: vi.fn(async () => ({ contract_version: "prompt-check.v1" as const, checks: [], limit: 60, offset: 0 })),
      getPromptCheck: vi.fn(),
    };
    render(<PromptCheckPage navigate={vi.fn()} transport={transport} />);
    await screen.findByText(/No check yet/);
    fireEvent.change(screen.getByLabelText("Prompt to check"), { target: { value: "Refactor the parser" } });
    fireEvent.click(screen.getByRole("button", { name: "Check prompt" }));
    await screen.findByText(/No local model is active/);

    const unavailable = {
      checkPrompt: vi.fn(),
      getPromptCheckHistory: vi.fn(async () => { throw new TransportError("Local API request failed (404)", 404); }),
      getPromptCheck: vi.fn(),
    };
    render(<PromptCheckPage navigate={vi.fn()} transport={unavailable} />);
    await screen.findByText(/not available in this runtime/);
  });
});
