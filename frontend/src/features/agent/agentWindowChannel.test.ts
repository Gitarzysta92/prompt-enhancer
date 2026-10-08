import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AGENT_WINDOW_CHANNEL_VERSION,
  announceAgentWindowActiveSession,
  broadcastAgentCatalogChange,
  connectAgentCatalogSync,
  connectAgentWindowSelectionOwner,
  listenForAgentWindowSelection,
  openAgentChatWindow,
  readAgentWindowKey,
} from "./agentWindowChannel";

const SESSION = "1".repeat(32);
const SECOND_SESSION = "2".repeat(32);
const EXISTING_KEY = "b".repeat(32);
const originalBroadcastChannel = Object.getOwnPropertyDescriptor(globalThis, "BroadcastChannel");
const originalPywebview = Object.getOwnPropertyDescriptor(globalThis, "pywebview");

class FakeBroadcastChannel {
  static channels = new Set<FakeBroadcastChannel>();
  readonly name: string;
  private listeners = new Set<(event: MessageEvent<unknown>) => void>();

  constructor(name: string) {
    this.name = name;
    FakeBroadcastChannel.channels.add(this);
  }

  addEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
    this.listeners.add(listener);
  }

  removeEventListener(_type: "message", listener: (event: MessageEvent<unknown>) => void): void {
    this.listeners.delete(listener);
  }

  postMessage(message: unknown): void {
    for (const channel of FakeBroadcastChannel.channels) {
      if (channel === this || channel.name !== this.name) continue;
      queueMicrotask(() => {
        for (const listener of channel.listeners) listener(new MessageEvent("message", { data: message }));
      });
    }
  }

  close(): void {
    this.listeners.clear();
    FakeBroadcastChannel.channels.delete(this);
  }
}

function installNativeOpen(value: unknown): ReturnType<typeof vi.fn> {
  const open = vi.fn().mockResolvedValue(value);
  Object.defineProperty(globalThis, "pywebview", {
    configurable: true,
    value: { api: { open_agent_chat_window: open } },
  });
  return open;
}

beforeEach(() => {
  FakeBroadcastChannel.channels.clear();
  Object.defineProperty(globalThis, "BroadcastChannel", {
    configurable: true,
    value: FakeBroadcastChannel,
  });
  Reflect.deleteProperty(globalThis, "pywebview");
});

afterEach(() => {
  vi.restoreAllMocks();
  FakeBroadcastChannel.channels.clear();
  if (originalBroadcastChannel) Object.defineProperty(globalThis, "BroadcastChannel", originalBroadcastChannel);
  else Reflect.deleteProperty(globalThis, "BroadcastChannel");
  if (originalPywebview) Object.defineProperty(globalThis, "pywebview", originalPywebview);
  else Reflect.deleteProperty(globalThis, "pywebview");
});

describe("Agent child-window rendezvous", () => {
  it("opens one reusable browser popup without putting the session id in its URL", async () => {
    let closeChild: () => void = () => undefined;
    const selected: string[] = [];
    const open = vi.spyOn(window, "open").mockImplementation((url) => {
      const parsed = new URL(String(url), "http://127.0.0.1");
      const key = parsed.searchParams.get("window");
      expect(parsed.pathname).toBe("/agent/window");
      expect(parsed.href).not.toContain(SESSION);
      expect(key).toMatch(/^[a-f0-9]{32}$/u);
      closeChild = listenForAgentWindowSelection(key!, (sessionId) => {
        selected.push(sessionId);
        return true;
      });
      return {} as Window;
    });

    await expect(openAgentChatWindow(SESSION)).resolves.toEqual({
      status: "opened",
      selection: "delivered",
      native: false,
      windowKey: expect.stringMatching(/^[a-f0-9]{32}$/u),
    });

    expect(selected).toEqual([SESSION]);
    expect(open).toHaveBeenCalledOnce();
    expect(open.mock.calls[0][1]).toBe("pe-agent-chat");
    closeChild();
  });

  it("focuses an existing native child and targets the key returned by its owner", async () => {
    const selected: string[] = [];
    const closeChild = listenForAgentWindowSelection(EXISTING_KEY, (sessionId) => {
      selected.push(sessionId);
      return true;
    });
    const open = installNativeOpen({
      version: "native-agent-window-v1",
      status: "focused",
      window_key: EXISTING_KEY,
      listener_started: false,
      worker_started: false,
      process_spawned: false,
      runtime_owner_created: false,
    });
    const popup = vi.spyOn(window, "open");

    await expect(openAgentChatWindow(SESSION)).resolves.toEqual({
      status: "focused",
      selection: "delivered",
      native: true,
      windowKey: EXISTING_KEY,
    });

    expect(open).toHaveBeenCalledOnce();
    expect(open.mock.calls[0][0]).toEqual({
      version: "native-agent-window-v1",
      window_key: expect.stringMatching(/^[a-f0-9]{32}$/u),
    });
    expect(popup).not.toHaveBeenCalled();
    expect(selected).toEqual([SESSION]);
    closeChild();
  });

  it("opens without inventing selection evidence when the memory channel is unavailable", async () => {
    Reflect.deleteProperty(globalThis, "BroadcastChannel");
    vi.spyOn(window, "open").mockReturnValue({} as Window);

    await expect(openAgentChatWindow(SESSION)).resolves.toEqual({
      status: "opened",
      selection: "unconfirmed",
      native: false,
      windowKey: expect.stringMatching(/^[a-f0-9]{32}$/u),
    });
  });

  it("restores the exact assigned chat when the same child document reconnects after reload", async () => {
    const selected: string[] = [];
    const owner = connectAgentWindowSelectionOwner();
    expect(owner.assign(EXISTING_KEY, SESSION)).toBe(true);

    const first = listenForAgentWindowSelection(EXISTING_KEY, (sessionId) => {
      selected.push(sessionId);
      return true;
    });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(selected).toEqual([SESSION]);
    expect(announceAgentWindowActiveSession(EXISTING_KEY, SECOND_SESSION)).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    first();

    const reloaded = listenForAgentWindowSelection(EXISTING_KEY, (sessionId) => {
      selected.push(sessionId);
      return true;
    });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(selected).toEqual([SESSION, SECOND_SESSION]);

    expect(owner.assign(EXISTING_KEY, SESSION)).toBe(true);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(selected).toEqual([SESSION, SECOND_SESSION, SESSION]);

    reloaded();
    owner.close();
  });

  it("acknowledges only the newest selection when an older lookup settles late", async () => {
    let resolveFirst!: (accepted: boolean) => void;
    const first = new Promise<boolean>((resolve) => { resolveFirst = resolve; });
    const selected = vi.fn((sessionId: string) => sessionId === SESSION ? first : Promise.resolve(true));
    const closeChild = listenForAgentWindowSelection(EXISTING_KEY, selected);
    const sender = new FakeBroadcastChannel("prompt-enhancer-agent-window-v1");
    const acknowledgements: string[] = [];
    const observer = new FakeBroadcastChannel("prompt-enhancer-agent-window-v1");
    observer.addEventListener("message", (event) => {
      const message = event.data as { kind?: unknown; session_id?: unknown };
      if (message.kind === "selected" && typeof message.session_id === "string") acknowledgements.push(message.session_id);
    });

    sender.postMessage({ version: AGENT_WINDOW_CHANNEL_VERSION, kind: "select", window_key: EXISTING_KEY, session_id: SESSION });
    await Promise.resolve();
    sender.postMessage({ version: AGENT_WINDOW_CHANNEL_VERSION, kind: "select", window_key: EXISTING_KEY, session_id: SECOND_SESSION });
    await Promise.resolve();
    await Promise.resolve();
    resolveFirst(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(selected).toHaveBeenCalledTimes(2);
    expect(acknowledgements).toEqual([SECOND_SESSION]);
    observer.close();
    sender.close();
    closeChild();
  });

  it("accepts only one exact opaque window query", () => {
    expect(readAgentWindowKey(`?window=${EXISTING_KEY}`)).toBe(EXISTING_KEY);
    expect(readAgentWindowKey(`?window=${EXISTING_KEY}&extra=1`)).toBeNull();
    expect(readAgentWindowKey(`?window=${EXISTING_KEY}&window=${"c".repeat(32)}`)).toBeNull();
    expect(readAgentWindowKey("?window=not-a-key")).toBeNull();
  });

  it("ignores malformed, cross-key, and extra-field selection messages", async () => {
    const selected = vi.fn(() => true);
    const closeChild = listenForAgentWindowSelection(EXISTING_KEY, selected);
    const sender = new FakeBroadcastChannel("prompt-enhancer-agent-window-v1");
    sender.postMessage({ version: AGENT_WINDOW_CHANNEL_VERSION, kind: "select", window_key: "c".repeat(32), session_id: SESSION });
    sender.postMessage({ version: AGENT_WINDOW_CHANNEL_VERSION, kind: "select", window_key: EXISTING_KEY, session_id: "bad" });
    sender.postMessage({ version: AGENT_WINDOW_CHANNEL_VERSION, kind: "select", window_key: EXISTING_KEY, session_id: SESSION, extra: true });
    await Promise.resolve();
    await Promise.resolve();

    expect(selected).not.toHaveBeenCalled();
    sender.close();
    closeChild();
  });

  it("synchronizes content-free catalog invalidations across Agent windows", async () => {
    const firstRefresh = vi.fn();
    const secondRefresh = vi.fn();
    const first = connectAgentCatalogSync(firstRefresh);
    const second = connectAgentCatalogSync(secondRefresh);

    first.notify();
    await Promise.resolve();
    await Promise.resolve();
    expect(firstRefresh).not.toHaveBeenCalled();
    expect(secondRefresh).toHaveBeenCalledOnce();

    broadcastAgentCatalogChange();
    await Promise.resolve();
    await Promise.resolve();
    expect(firstRefresh).toHaveBeenCalledOnce();
    expect(secondRefresh).toHaveBeenCalledTimes(2);

    const malformed = new FakeBroadcastChannel("prompt-enhancer-agent-window-v1");
    malformed.postMessage({
      version: AGENT_WINDOW_CHANNEL_VERSION,
      kind: "catalog-changed",
      leaked_content: "must be rejected",
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(firstRefresh).toHaveBeenCalledOnce();
    expect(secondRefresh).toHaveBeenCalledTimes(2);

    malformed.close();
    first.close();
    second.close();
  });
});
