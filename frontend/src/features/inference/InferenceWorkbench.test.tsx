import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { InferenceModel, InferencePreview, PromptEnhancerTransport } from "../../shared/api/contracts";
import { InferenceWorkbench } from "./InferenceWorkbench";
import { SessionInferenceControl } from "./SessionInferenceControl";

const model: InferenceModel = { id: "example-model", name: "Example model", provider: "litellm", remote: true,
  available: true, availability: "configured", adapter_version: "synthetic.v1", streaming: true };
const preview: InferencePreview = { model, purpose: "chat", request: { messages: [{ role: "user", content: "Redacted example request" }] },
  approval: "example-invalid-review", redactor_version: "synthetic.v1", expires_in_seconds: 600 };
function transport() {
  return {
    getInferenceModels: vi.fn<NonNullable<PromptEnhancerTransport["getInferenceModels"]>>().mockResolvedValue({ contract_version: "inference.v1", models: [model], unavailable_providers: [] }),
    previewInferenceChat: vi.fn<NonNullable<PromptEnhancerTransport["previewInferenceChat"]>>().mockResolvedValue(preview),
    streamInferenceChat: vi.fn<NonNullable<PromptEnhancerTransport["streamInferenceChat"]>>().mockResolvedValue({ content: "Example reply", reasoning: "", finish_reason: "stop", elapsed_ms: 5 }),
    previewManualAnalysis: vi.fn<NonNullable<PromptEnhancerTransport["previewManualAnalysis"]>>().mockResolvedValue(preview),
    runManualAnalysis: vi.fn<NonNullable<PromptEnhancerTransport["runManualAnalysis"]>>().mockResolvedValue({ model, kind: "interpret", result: { summary: "Example interpretation" }, prompt_version: "manual-analysis.v1", redactor_version: "synthetic.v1", persisted: false }),
  };
}
afterEach(cleanup);
async function compose() {
  await screen.findByRole("option", { name: "Example model · litellm · configured" });
  fireEvent.change(screen.getByRole("textbox", { name: "Inference text" }), { target: { value: "Example request" } });
}
describe("reviewed inference", () => {
  it("does not send during preview and invalidates the preview when text changes", async () => {
    const api = transport(); render(<InferenceWorkbench transport={api} />); await compose();
    fireEvent.click(screen.getByRole("button", { name: "Review request" }));
    await screen.findByRole("button", { name: "Send reviewed request" });
    expect(api.streamInferenceChat).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Inference text" }), { target: { value: "Changed example request" } });
    expect(screen.queryByRole("button", { name: "Send reviewed request" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Review request" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send reviewed request" }));
    await screen.findByText("Example reply");
    expect(api.streamInferenceChat.mock.calls[0][0]).toMatchObject({ approval: preview.approval, messages: [{ role: "user", content: "Changed example request" }] });
  });
  it("aborts a stopped stream and discards its late completion", async () => {
    const api = transport(); let finish!: (value: Awaited<ReturnType<NonNullable<PromptEnhancerTransport["streamInferenceChat"]>>>) => void;
    api.streamInferenceChat.mockImplementation((_request, onDelta) => { onDelta({ content: "Partial reply", reasoning: "" }); return new Promise((resolve) => { finish = resolve; }); });
    render(<InferenceWorkbench transport={api} />); await compose();
    fireEvent.click(screen.getByRole("button", { name: "Review request" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send reviewed request" }));
    await screen.findByText("Partial reply"); fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(api.streamInferenceChat.mock.calls[0][2]?.aborted).toBe(true);
    finish({ content: "Late reply", reasoning: "", finish_reason: "stop", elapsed_ms: 5 });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop" })).toBeNull());
    expect(screen.queryByText("Late reply")).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear chat" })).toBeNull();
  });
  it("reviews manually supplied session text before interpretation", async () => {
    const api = transport(); render(<InferenceWorkbench transport={api} />); await compose();
    fireEvent.change(screen.getByRole("combobox", { name: "Inference task" }), { target: { value: "interpret" } });
    fireEvent.click(screen.getByRole("button", { name: "Review request" }));
    await screen.findByRole("button", { name: "Send reviewed request" });
    expect(api.runManualAnalysis).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send reviewed request" }));
    await screen.findByText(/Example interpretation/);
    expect(api.runManualAnalysis.mock.calls[0][0]).toMatchObject({ kind: "interpret", text: "Example request", approval: preview.approval });
  });
  it("clears a session review when the selected session changes", async () => {
    const api = { ...transport(), previewSessionInference: vi.fn().mockResolvedValue(preview), runSessionInference: vi.fn() };
    const view = render(<SessionInferenceControl sessionId="example-a" transport={api} onJudged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Review external explanation" }));
    await screen.findByRole("button", { name: "Send reviewed request" });
    view.rerender(<SessionInferenceControl sessionId="example-b" transport={api} onJudged={vi.fn()} />);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Send reviewed request" })).toBeNull());
    expect(api.runSessionInference).not.toHaveBeenCalled();
  });
});
