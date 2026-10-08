import { describe, expect, it, vi } from "vitest";
import { createHttpTransport, TransportError } from "./httpTransport";
import { MAX_LOCAL_CHAT_RESPONSE_BYTES, MAX_LOCAL_CHAT_TEXT_CHARS } from "./localModelChatStream";

const AUTH = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
  user_presence_confirmation_available: false,
  user_presence_confirmation_mode: "unavailable",
};
const encoder = new TextEncoder();
const sse = (choice: unknown) => "data: " + JSON.stringify({ choices: [choice] }) + "\n\n";

function streamResponse(chunks: string[] | Uint8Array[]) {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

function chat(response: Response, onDelta = vi.fn(), signal?: AbortSignal) {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(AUTH), { headers: { "Content-Type": "application/json" } }))
    .mockResolvedValueOnce(response);
  const transport = createHttpTransport({ fetch: fetchMock as typeof fetch, origin: "http://127.0.0.1:4173" });
  return transport.streamLocalModelChat("example-model", { messages: [{ role: "user", content: "Example request" }] }, onDelta, signal);
}

describe("local model completion receipts", () => {
  it.each(["content", "reasoning_content"])("bounds accumulated %s and still releases the stream", async (field) => {
    const response = streamResponse([
      sse({ delta: { content: "Example partial" } }),
      sse({ delta: { [field]: "x".repeat(MAX_LOCAL_CHAT_TEXT_CHARS + 1) }, finish_reason: "stop" }),
    ]);
    const onDelta = vi.fn();
    await expect(chat(response, onDelta)).rejects.toBeInstanceOf(TransportError);
    expect(onDelta).toHaveBeenCalledTimes(1);
    expect(response.body?.locked).toBe(false);
  });

  it.each(["text/event-stream", "application/json"])("bounds total bytes for %s", async (kind) => {
    const response = new Response(new Uint8Array(MAX_LOCAL_CHAT_RESPONSE_BYTES + 1).fill(32), {
      headers: { "Content-Type": kind },
    });
    await expect(chat(response)).rejects.toBeInstanceOf(TransportError);
    expect(response.body?.locked).toBe(false);
  });

  it("cancels an open stream as soon as its finish receipt arrives", async () => {
    const cancel = vi.fn();
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(sse({ delta: { content: "Example answer" }, finish_reason: "stop" })));
      },
      cancel,
    }), { headers: { "Content-Type": "text/event-stream" } });
    await expect(chat(response)).resolves.toMatchObject({ content: "Example answer", finish_reason: "stop" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(response.body?.locked).toBe(false);
  });

  it("cancels a pending read on abort and never completes the partial reply", async () => {
    let delivered!: () => void;
    const firstDelta = new Promise<void>((resolve) => { delivered = resolve; });
    const cancel = vi.fn();
    const controller = new AbortController();
    const response = new Response(new ReadableStream<Uint8Array>({
      start(stream) { stream.enqueue(encoder.encode(sse({ delta: { content: "Example partial" } }))); },
      cancel,
    }), { headers: { "Content-Type": "text/event-stream" } });
    const pending = chat(response, vi.fn(delivered), controller.signal);
    await firstDelta;
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(response.body?.locked).toBe(false);
  });

  it("accepts multiline SSE data and CRLF framing", async () => {
    const response = streamResponse([
      ': example heartbeat\r\ndata: {"choices": [\r\ndata: {"delta": {"content": "Example answer"}, "finish_reason": "stop"}]}\r\n\r\n',
    ]);
    await expect(chat(response)).resolves.toMatchObject({ content: "Example answer", finish_reason: "stop" });
  });

  it.each(["stop", "length"])("preserves a valid whole-response %s receipt", async (reason) => {
    const response = new Response(JSON.stringify({ choices: [{ message: {
      content: "Example answer", reasoning_content: "Example model trace",
    }, finish_reason: reason }] }), { headers: { "Content-Type": "application/json" } });
    await expect(chat(response)).resolves.toMatchObject({
      content: "Example answer", reasoning: "Example model trace", finish_reason: reason,
    });
    expect(response.body?.locked).toBe(false);
  });

  it("rejects a bare DONE marker with no reply choice", async () => {
    await expect(chat(streamResponse(["data: [DONE]\n\n"]))).rejects.toBeInstanceOf(TransportError);
  });

  it("does not silently accept a structured tool request as plain chat", async () => {
    const response = streamResponse([sse({ delta: {
      content: "Example plan", tool_calls: [{ function: { name: "list_dir", arguments: "{}" } }],
    }, finish_reason: "stop" })]);
    await expect(chat(response)).rejects.toBeInstanceOf(TransportError);
  });

  it("rejects an ended stream with no completion receipt while retaining delivered deltas", async () => {
    const onDelta = vi.fn();
    const response = streamResponse([sse({ delta: { content: "Example partial answer" } })]);
    await expect(chat(response, onDelta)).rejects.toBeInstanceOf(TransportError);
    expect(onDelta).toHaveBeenCalledWith(expect.objectContaining({ content: "Example partial answer" }));
    expect(response.body?.locked).toBe(false);
  });

  it.each([
    ["invalid JSON", "data: {broken-example\n\n"],
    ["wrong content type", sse({ delta: { content: { text: "example" } } })],
    ["wrong reasoning type", sse({ delta: { reasoning_content: 17 } })],
    ["wrong delta type", sse({ delta: [] })],
    ["wrong finish type", sse({ delta: {}, finish_reason: { example: "stop" } })],
    ["invalid envelope", 'data: {"error":{"message":"EXAMPLE_PRIVATE_ERROR_CANARY"}}\n\n'],
    ["wrong choices type", 'data: {"choices":{"0":{"delta":{"content":"example"}}}}\n\n'],
  ])("rejects %s instead of silently certifying the earlier text", async (_label, badLine) => {
    const response = streamResponse([
      sse({ delta: { content: "Example partial answer" } }), badLine, "data: [DONE]\n\n",
    ]);
    await expect(chat(response)).rejects.toBeInstanceOf(TransportError);
    expect(response.body?.locked).toBe(false);
  });

  it("ends at the terminal receipt without accepting later unsolicited text", async () => {
    const response = streamResponse([
      sse({ delta: { content: "Example answer" }, finish_reason: "stop" }),
      sse({ delta: { content: " unexpected extra" } }),
      "data: [DONE]\n\n",
    ]);
    await expect(chat(response)).resolves.toMatchObject({ content: "Example answer", finish_reason: "stop" });
  });

  it.each(["length", "content_filter", "example_unknown"])("preserves the explicit %s reason for the chat UI", async (reason) => {
    const response = streamResponse([
      sse({ delta: { content: "Example partial answer" }, finish_reason: reason }),
      "data: [DONE]\n\n",
    ]);
    await expect(chat(response)).resolves.toMatchObject({ content: "Example partial answer", finish_reason: reason });
    expect(response.body?.locked).toBe(false);
  });

  it("accepts a terminal marker without a trailing newline", async () => {
    const response = streamResponse([sse({ delta: { content: "Example answer" } }), "data: [DONE]"]);
    await expect(chat(response)).resolves.toMatchObject({ content: "Example answer", finish_reason: null });
    expect(response.body?.locked).toBe(false);
  });

  it("accepts a valid terminal choice without a separate DONE marker", async () => {
    const response = streamResponse([sse({ delta: { content: "Example answer" }, finish_reason: "stop" }).trimEnd()]);
    await expect(chat(response)).resolves.toMatchObject({ content: "Example answer", finish_reason: "stop" });
  });

  it("keeps split UTF-8 characters and permits a usage-only terminal trailer", async () => {
    const bytes = encoder.encode(
      sse({ delta: { content: "Przykładowa odpowiedź." }, finish_reason: "stop" })
      + 'data: {"choices":[],"usage":{"completion_tokens":4}}\n\n'
      + "data: [DONE]\n\n",
    );
    const response = streamResponse(Array.from(bytes, (byte) => Uint8Array.of(byte)));
    await expect(chat(response)).resolves.toMatchObject({ content: "Przykładowa odpowiedź.", finish_reason: "stop" });
  });

  it("rejects invalid UTF-8 rather than replacing bytes inside a claimed answer", async () => {
    const response = streamResponse([
      encoder.encode('data: {"choices":[{"delta":{"content":"'),
      Uint8Array.of(255),
      encoder.encode('"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'),
    ]);
    await expect(chat(response)).rejects.toBeInstanceOf(TransportError);
  });

  it("releases a failed reader without exposing its upstream error", async () => {
    let pulled = false;
    const response = new Response(new ReadableStream<Uint8Array>({
      pull(controller) {
        if (!pulled) {
          pulled = true;
          controller.enqueue(encoder.encode(sse({ delta: { content: "Example partial" } })));
        } else controller.error(new Error("EXAMPLE_PRIVATE_READER_CANARY"));
      },
    }), { headers: { "Content-Type": "text/event-stream" } });
    const error = await chat(response).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TransportError);
    expect(String(error)).not.toContain("EXAMPLE_PRIVATE_READER_CANARY");
    expect(response.body?.locked).toBe(false);
  });

  it("rejects an unfinished whole-response fallback", async () => {
    const onDelta = vi.fn();
    const response = new Response(JSON.stringify({ choices: [{ message: { content: "Example partial answer" } }] }), {
      headers: { "Content-Type": "application/json" },
    });
    await expect(chat(response, onDelta)).rejects.toBeInstanceOf(TransportError);
    expect(onDelta).toHaveBeenCalledWith(expect.objectContaining({ content: "Example partial answer" }));
  });

  it("does not deliver a reply after its signal has been aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const onDelta = vi.fn();
    const response = streamResponse([sse({ delta: { content: "Example stale answer" }, finish_reason: "stop" })]);
    await expect(chat(response, onDelta, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(onDelta).not.toHaveBeenCalled();
    expect(response.body?.locked).toBe(false);
  });
});
