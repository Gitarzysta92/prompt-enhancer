import type { LocalModelChatDelta, LocalModelChatResult } from "./contracts";

// Match the Agent's bounded, display-only response limits. No usage is inferred.
export const MAX_LOCAL_CHAT_RESPONSE_BYTES = 2_000_000;
export const MAX_LOCAL_CHAT_TEXT_CHARS = 120_000;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalid(): never {
  throw new Error("model_reply_unusable");
}

function textField(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") return invalid();
  return value;
}

/**
 * Read one bounded local response. Delivered deltas are display-only until a
 * terminal receipt is verified; generation failures retain their finish reason.
 * Every path releases the response reader, including abort and parse failure.
 */
export async function readLocalModelChat(
  response: Response,
  onDelta: (delta: LocalModelChatDelta) => void,
  signal: AbortSignal | undefined,
  startedAt: number,
): Promise<LocalModelChatResult> {
  if (!response.body) return invalid();
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const mime = (response.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  const streaming = mime === "text/event-stream";
  const result: LocalModelChatResult = { content: "", reasoning: "", finish_reason: null, elapsed_ms: 0 };
  let sawChoice = false;
  let terminal = false;
  let sawToolRequest = false;
  let received = 0;
  let buffered = "";
  let dataLines: string[] = [];
  let cancellation: Promise<void> | undefined;

  const cancelReader = () => {
    cancellation ??= reader.cancel().catch(() => undefined);
    return cancellation;
  };
  const onAbort = () => { void cancelReader(); };
  const checkAbort = () => {
    if (signal?.aborted) throw new DOMException("The model reply was cancelled.", "AbortError");
  };
  const consume = (payload: unknown, whole: boolean) => {
    if (!record(payload) || payload.error != null || !Array.isArray(payload.choices)) return invalid();
    if (!whole && payload.choices.length === 0 && record(payload.usage)) return;
    if (payload.choices.length !== 1 || !record(payload.choices[0])) return invalid();
    const choice = payload.choices[0];
    if (choice.index !== undefined && choice.index !== 0) return invalid();
    const fields = whole ? choice.message : choice.delta ?? {};
    if (!record(fields)) return invalid();
    const finish = choice.finish_reason ?? null;
    if (finish !== null && (typeof finish !== "string" || !finish || finish.length > 128)) return invalid();
    const content = textField(fields.content);
    const reasoning = textField(fields.reasoning_content);
    if (fields.tool_calls != null) {
      if (!Array.isArray(fields.tool_calls)) return invalid();
      sawToolRequest ||= fields.tool_calls.length > 0;
    }
    if (fields.function_call != null) sawToolRequest = true;
    if (result.content.length + content.length > MAX_LOCAL_CHAT_TEXT_CHARS
        || result.reasoning.length + reasoning.length > MAX_LOCAL_CHAT_TEXT_CHARS) {
      throw new Error("model_reply_too_large");
    }
    checkAbort();
    sawChoice = true;
    result.content += content;
    result.reasoning += reasoning;
    result.finish_reason = finish;
    if (content || reasoning) onDelta({ content, reasoning });
    terminal = finish !== null;
  };
  const dispatch = () => {
    if (dataLines.length === 0 || terminal) return;
    const data = dataLines.join("\n");
    dataLines = [];
    if (data.trim() === "[DONE]") {
      terminal = true;
      return;
    }
    consume(JSON.parse(data) as unknown, false);
  };
  const line = (raw: string) => {
    const value = raw.replace(/\r$/, "");
    if (!value) dispatch();
    else if (value.startsWith("data:")) dataLines.push(value.slice(5).replace(/^ /, ""));
  };

  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    checkAbort();
    if (!streaming && mime !== "application/json" && !(mime.startsWith("application/") && mime.endsWith("+json"))) return invalid();
    while (!terminal) {
      checkAbort();
      const { value, done } = await reader.read();
      checkAbort();
      if (value) {
        received += value.byteLength;
        if (received > MAX_LOCAL_CHAT_RESPONSE_BYTES) throw new Error("model_reply_too_large");
      }
      buffered += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (streaming) {
        let newline = buffered.indexOf("\n");
        while (!terminal && newline !== -1) {
          line(buffered.slice(0, newline));
          buffered = buffered.slice(newline + 1);
          newline = buffered.indexOf("\n");
        }
      }
      if (done) {
        if (streaming) {
          if (!terminal && buffered) line(buffered);
          dispatch();
        } else consume(JSON.parse(buffered) as unknown, true);
        break;
      }
    }
    checkAbort();
    if (!sawChoice || !terminal) throw new Error("model_stream_incomplete");
    // This chat has no tool executor. Do not mistake a structured tool request
    // for a final text answer when a runtime gives it a generic stop marker.
    if (sawToolRequest && (result.finish_reason === null || result.finish_reason === "stop")) return invalid();
    result.elapsed_ms = Date.now() - startedAt;
    return result;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    await cancelReader();
    reader.releaseLock();
  }
}
