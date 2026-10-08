import {
  hasNativeAgentWindowBridge,
  openNativeAgentChatWindow,
} from "../../shared/platform/nativeDesktopBridge";

export const AGENT_WINDOW_CHANNEL_VERSION = "agent-window-channel-v1" as const;
const AGENT_WINDOW_CHANNEL_NAME = "prompt-enhancer-agent-window-v1";
const WINDOW_KEY = /^[a-f0-9]{32}$/u;
const SESSION_ID = /^[a-f0-9]{32}$/u;

type ChannelMessage =
  | { version: typeof AGENT_WINDOW_CHANNEL_VERSION; kind: "probe" | "ready"; window_key: string }
  | { version: typeof AGENT_WINDOW_CHANNEL_VERSION; kind: "active" | "select" | "selected"; window_key: string; session_id: string }
  | { version: typeof AGENT_WINDOW_CHANNEL_VERSION; kind: "catalog-changed" };

type ChannelLike = {
  addEventListener(type: "message", listener: (event: MessageEvent<unknown>) => void): void;
  removeEventListener(type: "message", listener: (event: MessageEvent<unknown>) => void): void;
  postMessage(message: unknown): void;
  close(): void;
};

type ChannelConstructor = new (name: string) => ChannelLike;

export type AgentWindowOpenResult = {
  status: "opened" | "focused" | "focus_unconfirmed" | "unavailable";
  selection: "delivered" | "unconfirmed";
  native: boolean;
  windowKey: string | null;
};

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(value).sort().join(",") === [...expected].sort().join(",");
}

function channelMessage(value: unknown): ChannelMessage | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.version !== AGENT_WINDOW_CHANNEL_VERSION || typeof record.kind !== "string") return null;
  if (record.kind === "catalog-changed") {
    return exactKeys(record, ["kind", "version"])
      ? record as ChannelMessage
      : null;
  }
  if (!WINDOW_KEY.test(String(record.window_key))) return null;
  if (record.kind === "probe" || record.kind === "ready") {
    return exactKeys(record, ["kind", "version", "window_key"])
      ? record as ChannelMessage
      : null;
  }
  if (record.kind === "active" || record.kind === "select" || record.kind === "selected") {
    return exactKeys(record, ["kind", "session_id", "version", "window_key"])
      && SESSION_ID.test(String(record.session_id))
      ? record as ChannelMessage
      : null;
  }
  return null;
}

export type AgentCatalogSync = {
  notify(): void;
  close(): void;
};

export type AgentWindowSelectionOwner = {
  assign(windowKey: string, sessionId: string): boolean;
  close(): void;
};

export function connectAgentCatalogSync(onChange: () => void): AgentCatalogSync {
  const channel = openSelectionChannel();
  if (channel === null) return { notify: () => undefined, close: () => undefined };
  const listener = (event: MessageEvent<unknown>) => {
    const message = channelMessage(event.data);
    if (message?.kind === "catalog-changed") onChange();
  };
  channel.addEventListener("message", listener);
  return {
    notify(): void {
      channel.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "catalog-changed",
      } satisfies ChannelMessage);
    },
    close(): void {
      channel.removeEventListener("message", listener);
      channel.close();
    },
  };
}

export function broadcastAgentCatalogChange(): void {
  const channel = openSelectionChannel();
  if (channel === null) return;
  channel.postMessage({
    version: AGENT_WINDOW_CHANNEL_VERSION,
    kind: "catalog-changed",
  } satisfies ChannelMessage);
  globalThis.setTimeout(() => channel.close(), 0);
}

/**
 * Keep the latest content-free child-window selection available while the
 * owning Agent page remains mounted. A child emits `ready` again after a page
 * reload, so the exact live chat can be restored without putting its identity
 * in a URL, native bridge call, browser-storage record, or Python process.
 */
export function connectAgentWindowSelectionOwner(): AgentWindowSelectionOwner {
  const channel = openSelectionChannel();
  if (channel === null) return { assign: () => false, close: () => undefined };
  let closed = false;
  let selection: { windowKey: string; sessionId: string } | null = null;
  const send = () => {
    if (closed || selection === null) return;
    channel.postMessage({
      version: AGENT_WINDOW_CHANNEL_VERSION,
      kind: "select",
      window_key: selection.windowKey,
      session_id: selection.sessionId,
    } satisfies ChannelMessage);
  };
  const listener = (event: MessageEvent<unknown>) => {
    const message = channelMessage(event.data);
    if (
      message?.kind === "active"
      && selection !== null
      && message.window_key === selection.windowKey
    ) {
      selection = { windowKey: message.window_key, sessionId: message.session_id };
      return;
    }
    if (
      message?.kind === "ready"
      && selection !== null
      && message.window_key === selection.windowKey
    ) send();
  };
  channel.addEventListener("message", listener);
  return {
    assign(windowKey: string, sessionId: string): boolean {
      if (closed || !WINDOW_KEY.test(windowKey) || !SESSION_ID.test(sessionId)) return false;
      selection = { windowKey, sessionId };
      send();
      return true;
    },
    close(): void {
      if (closed) return;
      closed = true;
      selection = null;
      channel.removeEventListener("message", listener);
      channel.close();
    },
  };
}

/**
 * Update the primary renderer's reload target after navigation inside the
 * detached window. BroadcastChannel does not deliver to its sending instance,
 * and the owner accepts this only for the exact opaque key it already owns.
 */
export function announceAgentWindowActiveSession(windowKey: string, sessionId: string): boolean {
  if (!WINDOW_KEY.test(windowKey) || !SESSION_ID.test(sessionId)) return false;
  const channel = openSelectionChannel();
  if (channel === null) return false;
  channel.postMessage({
    version: AGENT_WINDOW_CHANNEL_VERSION,
    kind: "active",
    window_key: windowKey,
    session_id: sessionId,
  } satisfies ChannelMessage);
  globalThis.setTimeout(() => channel.close(), 0);
  return true;
}

function channelConstructor(): ChannelConstructor | null {
  const candidate = (globalThis as typeof globalThis & { BroadcastChannel?: ChannelConstructor }).BroadcastChannel;
  return typeof candidate === "function" ? candidate : null;
}

export function newAgentWindowKey(): string | null {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function") return null;
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function readAgentWindowKey(search = globalThis.location?.search ?? ""): string | null {
  const parameters = new URLSearchParams(search);
  if ([...parameters.keys()].some((key) => key !== "window")) return null;
  const values = parameters.getAll("window");
  return values.length === 1 && WINDOW_KEY.test(values[0]) ? values[0] : null;
}

function openSelectionChannel(): ChannelLike | null {
  const Channel = channelConstructor();
  if (Channel === null) return null;
  try {
    return new Channel(AGENT_WINDOW_CHANNEL_NAME);
  } catch {
    return null;
  }
}

function selectionSender(channel: ChannelLike | null, sessionId: string) {
  const ready = new Set<string>();
  let actualKey: string | null = null;
  let settled = false;
  let resolveDelivery: ((delivered: boolean) => void) | null = null;
  const delivery = new Promise<boolean>((resolve) => { resolveDelivery = resolve; });
  const sendSelection = () => {
    if (actualKey === null || channel === null || !ready.has(actualKey)) return;
    channel.postMessage({
      version: AGENT_WINDOW_CHANNEL_VERSION,
      kind: "select",
      window_key: actualKey,
      session_id: sessionId,
    } satisfies ChannelMessage);
  };
  const listener = (event: MessageEvent<unknown>) => {
    const message = channelMessage(event.data);
    if (message === null) return;
    if (message.kind === "ready") {
      ready.add(message.window_key);
      sendSelection();
      return;
    }
    if (message.kind === "selected" && message.window_key === actualKey && message.session_id === sessionId) {
      settled = true;
      resolveDelivery?.(true);
    }
  };
  channel?.addEventListener("message", listener);
  return {
    selectWindowKey(windowKey: string): void {
      actualKey = windowKey;
      if (channel !== null) {
        channel.postMessage({
          version: AGENT_WINDOW_CHANNEL_VERSION,
          kind: "probe",
          window_key: windowKey,
        } satisfies ChannelMessage);
        sendSelection();
      }
    },
    async finish(timeoutMs = 2000): Promise<boolean> {
      if (channel === null || actualKey === null) return false;
      const probe = globalThis.setInterval(() => {
        if (settled || actualKey === null) return;
        channel.postMessage({
          version: AGENT_WINDOW_CHANNEL_VERSION,
          kind: "probe",
          window_key: actualKey,
        } satisfies ChannelMessage);
      }, 100);
      const timeout = globalThis.setTimeout(() => resolveDelivery?.(false), timeoutMs);
      const delivered = await delivery;
      globalThis.clearInterval(probe);
      globalThis.clearTimeout(timeout);
      return delivered;
    },
    close(): void {
      channel?.removeEventListener("message", listener);
      channel?.close();
    },
  };
}

export async function openAgentChatWindow(sessionId: string): Promise<AgentWindowOpenResult> {
  if (!SESSION_ID.test(sessionId)) return { status: "unavailable", selection: "unconfirmed", native: false, windowKey: null };
  const requestedKey = newAgentWindowKey();
  if (requestedKey === null) return { status: "unavailable", selection: "unconfirmed", native: false, windowKey: null };
  const channel = openSelectionChannel();
  const sender = selectionSender(channel, sessionId);
  const native = hasNativeAgentWindowBridge();
  try {
    let status: AgentWindowOpenResult["status"];
    let actualKey = requestedKey;
    if (native) {
      const receipt = await openNativeAgentChatWindow(requestedKey);
      if (receipt.status === "invalid_request" || receipt.status === "unavailable" || receipt.windowKey === null) {
        return { status: "unavailable", selection: "unconfirmed", native: true, windowKey: null };
      }
      status = receipt.status;
      actualKey = receipt.windowKey;
    } else {
      let opened: Window | null = null;
      try {
        opened = window.open(
          `/agent/window?window=${requestedKey}`,
          "pe-agent-chat",
          "popup=yes,width=1100,height=860,resizable=yes,scrollbars=yes",
        );
      } catch {
        opened = null;
      }
      if (opened === null) return { status: "unavailable", selection: "unconfirmed", native: false, windowKey: null };
      status = "opened";
    }
    sender.selectWindowKey(actualKey);
    const delivered = await sender.finish();
    return { status, selection: delivered ? "delivered" : "unconfirmed", native, windowKey: actualKey };
  } catch {
    return { status: "unavailable", selection: "unconfirmed", native, windowKey: null };
  } finally {
    sender.close();
  }
}

export function listenForAgentWindowSelection(
  windowKey: string,
  onSelection: (sessionId: string) => boolean | Promise<boolean>,
): () => void {
  if (!WINDOW_KEY.test(windowKey)) return () => undefined;
  const channel = openSelectionChannel();
  if (channel === null) return () => undefined;
  let closed = false;
  let acceptedSessionId: string | null = null;
  let pendingSessionId: string | null = null;
  let selectionRevision = 0;
  const ready = () => channel.postMessage({
    version: AGENT_WINDOW_CHANNEL_VERSION,
    kind: "ready",
    window_key: windowKey,
  } satisfies ChannelMessage);
  const listener = (event: MessageEvent<unknown>) => {
    const message = channelMessage(event.data);
    if (message === null || message.kind === "catalog-changed" || message.window_key !== windowKey) return;
    if (message.kind === "probe") {
      ready();
      return;
    }
    if (message.kind !== "select") return;
    if (message.session_id === acceptedSessionId) {
      channel.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "selected",
        window_key: windowKey,
        session_id: message.session_id,
      } satisfies ChannelMessage);
      return;
    }
    if (message.session_id === pendingSessionId) return;
    const revision = ++selectionRevision;
    pendingSessionId = message.session_id;
    void Promise.resolve(onSelection(message.session_id)).then((accepted) => {
      if (revision !== selectionRevision) return;
      pendingSessionId = null;
      if (!accepted || closed) return;
      acceptedSessionId = message.session_id;
      channel.postMessage({
        version: AGENT_WINDOW_CHANNEL_VERSION,
        kind: "selected",
        window_key: windowKey,
        session_id: message.session_id,
      } satisfies ChannelMessage);
    }).catch(() => {
      if (revision === selectionRevision) pendingSessionId = null;
    });
  };
  channel.addEventListener("message", listener);
  ready();
  return () => {
    closed = true;
    selectionRevision += 1;
    channel.removeEventListener("message", listener);
    channel.close();
  };
}
