import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deriveLoadedUiRevision,
  startUiRevisionGuard,
} from "./uiRevisionGuard";

const LOADED_REVISION = "assets/index-AbCdEf12.js";
const LOADED_MODULE_URL = `http://127.0.0.1:8766/${LOADED_REVISION}`;
const CURRENT_REVISION = "assets/index-ZyXwVu98.js";

function response(payload: unknown, ok = true) {
  return {
    ok,
    json: vi.fn(async () => payload),
  };
}

async function settleAsyncCheck() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function setVisibility(visibilityState: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: visibilityState,
  });
}

describe("deriveLoadedUiRevision", () => {
  it("derives the exact safe hashed asset revision", () => {
    expect(deriveLoadedUiRevision(LOADED_MODULE_URL)).toBe(LOADED_REVISION);
    expect(
      deriveLoadedUiRevision(
        "https://example.invalid/ui/v2/assets/dashboard-a1B2_c3D.js",
      ),
    ).toBe("assets/dashboard-a1B2_c3D.js");
  });

  it.each([
    "not a URL",
    "http://127.0.0.1:8766/src/main.tsx",
    "http://127.0.0.1:8766/assets/index.js",
    "http://127.0.0.1:8766/assets/index-short.js",
    "http://127.0.0.1:8766/assets/index-AbCdEf12.js?stale=1",
    "http://127.0.0.1:8766/assets/%2e%2e-AbCdEf12.js",
  ])("rejects an unsafe or non-production module URL: %s", (moduleUrl) => {
    expect(deriveLoadedUiRevision(moduleUrl)).toBeNull();
  });
});

describe("startUiRevisionGuard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(document, "visibilityState");
    vi.restoreAllMocks();
  });

  it("keeps the loaded app when the current revision matches", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ revision: LOADED_REVISION }));
    const reload = vi.fn();

    const guard = startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload,
    });
    await settleAsyncCheck();

    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledWith("/app-revision.json", {
      cache: "no-store",
      credentials: "same-origin",
    });
    expect(reload).not.toHaveBeenCalled();
    guard.dispose();
  });

  it("reloads exactly once after a confirmed mismatch", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ revision: CURRENT_REVISION }));
    const reload = vi.fn();

    startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload,
    });
    await settleAsyncCheck();

    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(15_000);

    expect(reload).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it.each([
    null,
    {},
    { revision: CURRENT_REVISION, unexpected: true },
    { revision: "assets/index.js" },
    { revision: "../assets/index-ZyXwVu98.js" },
  ])("ignores malformed revision payloads", async (payload) => {
    const fetchImpl = vi.fn().mockResolvedValue(response(payload));
    const reload = vi.fn();

    const guard = startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload,
    });
    await settleAsyncCheck();

    expect(reload).not.toHaveBeenCalled();
    guard.dispose();
  });

  it("ignores fetch, HTTP, and JSON failures without mutation", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error("synthetic network failure"))
      .mockResolvedValueOnce(response({ revision: CURRENT_REVISION }, false))
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn(async () => {
          throw new Error("synthetic JSON failure");
        }),
      });
    const reload = vi.fn();

    const guard = startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload,
    });
    await settleAsyncCheck();
    window.dispatchEvent(new Event("focus"));
    await settleAsyncCheck();
    window.dispatchEvent(new Event("focus"));
    await settleAsyncCheck();

    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(reload).not.toHaveBeenCalled();
    guard.dispose();
  });

  it("checks on visible focus, visibility restoration, and a five-second interval", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ revision: LOADED_REVISION }));
    const guard = startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload: vi.fn(),
    });
    await settleAsyncCheck();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await settleAsyncCheck();
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    window.dispatchEvent(new Event("focus"));
    await settleAsyncCheck();
    expect(fetchImpl).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    guard.dispose();
  });

  it("disposes listeners and its interval without leaking checks", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ revision: LOADED_REVISION }));
    const guard = startUiRevisionGuard({
      enabled: true,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload: vi.fn(),
    });
    await settleAsyncCheck();

    guard.dispose();
    guard.dispose();
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(15_000);

    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("is inert in synthetic/development mode", async () => {
    const fetchImpl = vi.fn();
    const reload = vi.fn();
    const guard = startUiRevisionGuard({
      enabled: false,
      moduleUrl: LOADED_MODULE_URL,
      fetchImpl,
      reload,
    });

    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(15_000);

    expect(fetchImpl).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    guard.dispose();
  });
});
