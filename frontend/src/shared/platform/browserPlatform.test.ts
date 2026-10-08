import { afterEach, describe, expect, it, vi } from "vitest";
import { createBrowserPlatform } from "./browserPlatform";

afterEach(() => {
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
});

describe("createBrowserPlatform", () => {
  it("does not add a history entry or emit when the requested path is already current", () => {
    window.history.replaceState(null, "", "/overview/");
    const pushState = vi.spyOn(window.history, "pushState");
    const listener = vi.fn();
    const platform = createBrowserPlatform(window);
    const unsubscribe = platform.subscribe(listener);

    platform.navigate({ name: "overview" });

    expect(pushState).not.toHaveBeenCalled();
    expect(listener).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/overview/");
    unsubscribe();
  });

  it("pushes and emits exactly once for a different destination", () => {
    window.history.replaceState(null, "", "/overview");
    const pushState = vi.spyOn(window.history, "pushState");
    const listener = vi.fn();
    const platform = createBrowserPlatform(window);
    const unsubscribe = platform.subscribe(listener);

    platform.navigate({ name: "sessions" });

    expect(pushState).toHaveBeenCalledWith(null, "", "/sessions");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({ name: "sessions" });
    expect(window.location.pathname).toBe("/sessions");
    unsubscribe();
  });

  it("repairs a malformed path with multiple trailing slashes", () => {
    window.history.replaceState(null, "", "/overview//");
    const pushState = vi.spyOn(window.history, "pushState");
    const listener = vi.fn();
    const platform = createBrowserPlatform(window);
    const unsubscribe = platform.subscribe(listener);

    platform.navigate({ name: "overview" });

    expect(pushState).toHaveBeenCalledWith(null, "", "/overview");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({ name: "overview" });
    expect(window.location.pathname).toBe("/overview");
    unsubscribe();
  });

  it("keeps an unknown address in a content-free recovery route until the user leaves it", () => {
    window.history.replaceState(null, "", "/unexpected/private-shaped-value");
    const platform = createBrowserPlatform(window);

    expect(platform.currentRoute()).toEqual({ name: "not_found" });

    platform.navigate({ name: "overview" });

    expect(window.location.pathname).toBe("/overview");
    expect(platform.currentRoute()).toEqual({ name: "overview" });
  });

  it("emits allowlisted and content-free recovery routes for browser back/forward events", () => {
    window.history.replaceState(null, "", "/overview");
    const platform = createBrowserPlatform(window);
    const listener = vi.fn();
    const unsubscribe = platform.subscribe(listener);

    window.history.replaceState(null, "", "/sessions");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(listener).toHaveBeenLastCalledWith({ name: "sessions" });

    window.history.replaceState(null, "", "/unexpected/private-shaped-value");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(listener).toHaveBeenLastCalledWith({ name: "not_found" });
    expect(listener.mock.lastCall?.[0]).toEqual({ name: "not_found" });
    unsubscribe();
  });

  it("owns one popstate listener only while at least one subscriber exists", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const platform = createBrowserPlatform(window);
    const unsubscribeA = platform.subscribe(() => undefined);
    const unsubscribeB = platform.subscribe(() => undefined);

    expect(add.mock.calls.filter(([type]) => type === "popstate")).toHaveLength(1);
    unsubscribeA();
    expect(remove.mock.calls.filter(([type]) => type === "popstate")).toHaveLength(0);
    unsubscribeB();
    expect(remove.mock.calls.filter(([type]) => type === "popstate")).toHaveLength(1);
  });
});
