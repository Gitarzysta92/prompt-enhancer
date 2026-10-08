import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ModelLinkExperimentRequest,
  ModelLinkExperimentOutcome,
  ModelLinkAnnotation,
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
} from "../../shared/api/contracts";
import {
  SYNTHETIC_MODEL_LINK_EXPERIMENT,
  SYNTHETIC_MODEL_LINK_OUTCOME,
  SYNTHETIC_QUALITY_SESSION_ID,
} from "../../shared/api/syntheticFixtures";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { TransportError } from "../../shared/api/httpTransport";
import { ModelLinkExperimentPanel } from "./ModelLinkExperimentPanel";
import {
  parseModelLinkExperiment,
  parseModelLinkOutcome,
} from "./modelLinkContract";


const EXACT: ProviderCompatibilityStatus = {
  provider: "codex",
  capability: "session_text_analysis",
  state: "exact",
  capability_state: "supported",
  provider_family: "codex_app_server",
  provider_version: "1.2.3",
  adapter_family: "codex_app_server",
  adapter_version: "2.0.0",
  source_schema_family: "codex_thread",
  source_schema_version: "1",
  content_schema_family: "codex_thread_items",
  content_schema_version: "1",
  reason_code: "exact_match",
  checked_at: "2040-01-01T10:00:00Z",
  update_support: "unsupported",
  update_target: null,
};

const CAPABILITY = {
  available: true,
  reason_code: "available",
  data_tier: "redacted_content",
  content_persistence: false,
  network_inference: false,
  raw_transcripts: false,
} as const;

function panelElement(transport: PromptEnhancerTransport, sessionId = SYNTHETIC_QUALITY_SESSION_ID) {
  return (
    <ModelLinkExperimentPanel
      analysisCapability={CAPABILITY}
      providerCompatibility={EXACT}
      sessionId={sessionId}
      transport={transport}
    />
  );
}

function renderPanel(transport: PromptEnhancerTransport) {
  return render(panelElement(transport));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

describe("ModelLinkExperimentPanel", () => {
  it.each(["failure", "cancel"] as const)("recovers the interrupted initial metadata read after a run %s without restarting the model", async (result) => {
    const initial = deferred<typeof SYNTHETIC_MODEL_LINK_EXPERIMENT>();
    const pendingRun = deferred<ModelLinkExperimentOutcome>();
    const getLatestModelLinkExperiment = vi.fn()
      .mockImplementationOnce(() => initial.promise)
      .mockResolvedValue(structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT));
    const startModelLinkExperiment = vi.fn(() => pendingRun.promise);
    renderPanel({ ...createSyntheticTransport(), getLatestModelLinkExperiment, startModelLinkExperiment });
    expect(screen.queryByText(/No model-link experiment has been stored/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Run Qwen + BGE locally" }));
    if (result === "cancel") fireEvent.click(screen.getByRole("button", { name: "Cancel wait" }));
    else await act(async () => pendingRun.reject(new Error("synthetic failure")));
    expect(await screen.findByText(/Only content-free scores and labels survive reload/)).toBeVisible();
    expect(getLatestModelLinkExperiment).toHaveBeenCalledTimes(2);
    expect(startModelLinkExperiment).toHaveBeenCalledOnce();
    expect(screen.queryByText(/No model-link experiment has been stored/)).toBeNull();
    await act(async () => initial.resolve(structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT)));
    expect(getLatestModelLinkExperiment).toHaveBeenCalledTimes(2);
  });

  it("keeps a failed metadata read unknown and offers a read-only retry", async () => {
    const base = createSyntheticTransport();
    const start = vi.spyOn(base, "startModelLinkExperiment");
    base.getLatestModelLinkExperiment = vi.fn().mockRejectedValueOnce(new Error("synthetic read failure"))
      .mockResolvedValue(structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT));
    renderPanel(base);
    const retry = await screen.findByRole("button", { name: "Retry stored metadata" });
    expect(screen.getByRole("status")).toHaveTextContent("availability is unknown");
    fireEvent.click(retry);
    expect(await screen.findByText(/Only content-free scores and labels survive reload/)).toBeVisible();
    expect(start).not.toHaveBeenCalled();
  });

  it.each([
    ["session", "resolve"], ["session", "reject"], ["transport", "resolve"], ["transport", "reject"],
  ] as const)("ignores a late run %s context change and %s", async (context, completion) => {
    const pending = deferred<ModelLinkExperimentOutcome>();
    const start = vi.fn((_id: string, _request: ModelLinkExperimentRequest, _key: string, _signal?: AbortSignal) => pending.promise);
    const transport = { ...createSyntheticTransport(),
      getLatestModelLinkExperiment: vi.fn(async () => { throw new TransportError("example-not-found", 404); }),
      startModelLinkExperiment: start };
    const view = renderPanel(transport);
    fireEvent.click(await screen.findByRole("button", { name: "Run Qwen + BGE locally" }));
    view.rerender(panelElement(context === "transport" ? { ...transport } : transport, context === "session" ? "f".repeat(64) : SYNTHETIC_QUALITY_SESSION_ID));
    await screen.findByText(/No model-link experiment has been stored/);
    expect(screen.queryByRole("button", { name: "Cancel wait" })).not.toBeInTheDocument();
    await act(async () => {
      if (completion === "resolve") pending.resolve(structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME));
      else pending.reject(new Error("example-late-error"));
      await pending.promise.catch(() => undefined);
    });
    expect(start.mock.calls[0][3]?.aborted).toBe(true);
    expect(screen.queryByText("User request")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Qwen + BGE locally" })).toBeEnabled();
  });

  it("does not let an old cancelled wait release a replacement run's controller", async () => {
    const first = deferred<ModelLinkExperimentOutcome>();
    const second = deferred<ModelLinkExperimentOutcome>();
    const start = vi.fn((_id: string, _request: ModelLinkExperimentRequest, _key: string, _signal?: AbortSignal) => (
      start.mock.calls.length === 1 ? first.promise : second.promise
    ));
    renderPanel({ ...createSyntheticTransport(), startModelLinkExperiment: start });
    fireEvent.click(await screen.findByRole("button", { name: "Run Qwen + BGE locally" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel wait" }));
    expect(screen.getByText(/worker may still be running/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Run Qwen + BGE locally" }));
    await act(async () => { first.resolve(structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME)); await first.promise; });
    fireEvent.click(screen.getByRole("button", { name: "Cancel wait" }));
    expect(start.mock.calls[1][3]?.aborted).toBe(true);
    await act(async () => { second.resolve(structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME)); await second.promise; });
    expect(screen.queryByText("User request")).not.toBeInTheDocument();
  });

  it("aborts a pending review label on context change and does not merge it into the replacement experiment", async () => {
    const pending = deferred<ModelLinkAnnotation>();
    const annotate = vi.fn((_run: string, _link: string, _request: unknown, _signal?: AbortSignal) => pending.promise);
    const transport = { ...createSyntheticTransport(), annotateModelLink: annotate,
      startModelLinkExperiment: vi.fn(async () => structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME)) };
    const view = renderPanel(transport);
    fireEvent.click(await screen.findByRole("button", { name: "Run Qwen + BGE locally" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "Relevant" }))[0]);
    view.rerender(panelElement(transport, "f".repeat(64)));
    await waitFor(() => expect(screen.queryByText("Loading stored experiment metadata...")).not.toBeInTheDocument());
    await act(async () => { pending.resolve({ link_id: SYNTHETIC_MODEL_LINK_OUTCOME.suggestions[0].link_id, revision: 1, label: "relevant", annotated_at: "2040-01-03T09:02:00Z" }); await pending.promise; });
    expect(annotate.mock.calls[0][3]?.aborted).toBe(true);
    expect(screen.queryByText(/Qwen: 1\/1 relevant/)).not.toBeInTheDocument();
    expect(screen.queryByText("User request")).not.toBeInTheDocument();
  });

  it("loads only content-free stored metadata and makes no experiment command on render", async () => {
    const latest = vi.fn(async () => structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT));
    const start = vi.fn();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelLinkExperiment: latest,
      startModelLinkExperiment: start,
    };
    renderPanel(transport);

    expect(
      await screen.findByRole("heading", {
        name: /do the models link requests to the right agent work/i,
      }),
    ).toBeVisible();
    await waitFor(() => expect(latest).toHaveBeenCalledTimes(1));
    expect(start).not.toHaveBeenCalled();
    expect(screen.getByText(/retrieval method, not your intelligence/i)).toBeVisible();
    fireEvent.click(screen.getByText("How this experiment works"));
    expect(screen.getByRole("list", { name: "How the model experiment works" })).toBeVisible();
    expect(screen.getByText("Run locally")).toBeVisible();
    expect(screen.getByText("Review suggestions")).toBeVisible();
    expect(screen.getByText("Judge the method")).toBeVisible();
    expect(screen.queryByText(/overall score/i)).not.toBeInTheDocument();
    expect(screen.getByText(/only content-free scores and labels survive reload/i)).toBeVisible();
  });

  it("runs the fixed local experiment with one explicit button and shows transient review pairs", async () => {
    const start = vi.fn(
      async (
        _sessionId: string,
        _request: ModelLinkExperimentRequest,
        _idempotencyKey: string,
      ) => structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME),
    );
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelLinkExperiment: async () => {
        throw new TransportError("not found", 404);
      },
      startModelLinkExperiment: start,
    };
    renderPanel(transport);

    const button = await screen.findByRole("button", {
      name: "Run Qwen + BGE locally",
    });
    fireEvent.click(button);

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toBe(SYNTHETIC_QUALITY_SESSION_ID);
    expect(start.mock.calls[0][1]).toEqual({
      confirmation: "compare_selected_redacted_text_with_local_models",
      device: "auto",
    });
    expect(start.mock.calls[0][2]).toMatch(/^dashboard-model-link-experiment-/);
    expect(await screen.findAllByText("User request")).toHaveLength(2);
    expect(screen.getAllByText(/fictional readiness summary/i).length).toBeGreaterThan(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("stores a human label with the current revision and excludes unsure from precision", async () => {
    const annotate = vi.fn(async (_runId, linkId, request) => ({
      link_id: linkId,
      revision: request.expected_revision + 1,
      label: request.label,
      annotated_at: "2040-01-03T09:02:00Z",
    }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelLinkExperiment: async () => {
        throw new TransportError("not found", 404);
      },
      startModelLinkExperiment: async () =>
        structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME),
      annotateModelLink: annotate,
    };
    renderPanel(transport);
    fireEvent.click(
      await screen.findByRole("button", { name: "Run Qwen + BGE locally" }),
    );
    const relevant = (await screen.findAllByRole("button", {
      name: "Relevant",
    }))[0];
    fireEvent.click(relevant);

    await waitFor(() => expect(annotate).toHaveBeenCalledTimes(1));
    expect(annotate.mock.calls[0][2]).toEqual({
      label: "relevant",
      expected_revision: 0,
    });
    expect(await screen.findByText(/Qwen: 1\/1 relevant/)).toBeVisible();
    expect(screen.getByText(/Unsure is excluded/)).toBeVisible();
  });

  it("fails closed for malformed model responses without displaying injected text", async () => {
    const malformed = structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME) as unknown as Record<string, unknown>;
    const experiment = malformed.experiment as Record<string, unknown>;
    experiment["private_excerpt"] = "SYNTHETIC_PRIVATE_CANARY";
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelLinkExperiment: async () => {
        throw new TransportError("not found", 404);
      },
      startModelLinkExperiment: async () => malformed as never,
    };
    renderPanel(transport);
    fireEvent.click(
      await screen.findByRole("button", { name: "Run Qwen + BGE locally" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /did not complete/i,
    );
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it("does not offer another identical model run after a terminal provider-response limit", async () => {
    const start = vi.fn(async () => {
      throw new TransportError(
        "SYNTHETIC_PRIVATE_LIMIT_CANARY",
        413,
        "source_provider_response_limit",
      );
    });
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelLinkExperiment: async () => {
        throw new TransportError("not found", 404);
      },
      startModelLinkExperiment: start,
    };
    renderPanel(transport);
    const run = await screen.findByRole("button", {
      name: "Run Qwen + BGE locally",
    });

    fireEvent.click(run);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /local Codex response exceeded the transport limit/i,
    );
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_LIMIT_CANARY");
    expect(run).toBeDisabled();
    fireEvent.click(run);
    expect(start).toHaveBeenCalledTimes(1);
  });
});

describe("model-link runtime contract", () => {
  it("rejects missing provenance, extra transcript fields, and suggestions outside stored links", () => {
    const missing = structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT) as unknown as Record<string, unknown>;
    delete (missing.run as Record<string, unknown>).qwen_model;
    expect(() => parseModelLinkExperiment(missing)).toThrow("invalid-model-link-contract");

    const extra = structuredClone(SYNTHETIC_MODEL_LINK_EXPERIMENT) as unknown as Record<string, unknown>;
    extra.transcript = "SYNTHETIC_PRIVATE_CANARY";
    expect(() => parseModelLinkExperiment(extra)).toThrow("invalid-model-link-contract");

    const outside = structuredClone(SYNTHETIC_MODEL_LINK_OUTCOME);
    outside.suggestions[0].link_id = "9".repeat(64);
    expect(() => parseModelLinkOutcome(outside)).toThrow("invalid-model-link-contract");
  });
});
