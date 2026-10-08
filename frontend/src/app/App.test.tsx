import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createSyntheticTransport } from "../shared/api/syntheticTransport";
import {
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_QUALITY_SESSION_ID,
} from "../shared/api/syntheticFixtures";
import type { AppRoute, PlatformAdapter } from "../shared/platform/platform";
import { createBrowserPlatform } from "../shared/platform/browserPlatform";
import {
  createRuntimeComposition,
  type LocalRuntimeTransport,
  type RuntimeHealth,
  type RuntimeComposition,
  type SyntheticRuntimeTransport,
} from "../shared/platform/runtimeMode";
import { App, RouteErrorBoundary } from "./App";
import { Suspense, useState } from "react";
import { retryableLazy } from "../shared/ui/retryableLazy";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, reject, resolve };
}

function createMemoryPlatform(initialRoute: AppRoute = { name: "discovery" }): PlatformAdapter {
  let route: AppRoute = initialRoute;
  const listeners = new Set<(next: AppRoute) => void>();
  return {
    currentRoute: () => route,
    navigate(next) {
      route = next;
      listeners.forEach((listener) => listener(next));
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

const HEALTHY_LOCAL_RUNTIME: RuntimeHealth = {
  status: "ok",
  costMode: "offline_only",
  dataTier: "metadata",
};

function syntheticRuntime(
  transport: SyntheticRuntimeTransport = createSyntheticTransport(),
): RuntimeComposition {
  return createRuntimeComposition("synthetic_demo", transport);
}

function localFixtureTransport(
  getRuntimeHealth: LocalRuntimeTransport["getRuntimeHealth"],
): LocalRuntimeTransport {
  return {
    ...createSyntheticTransport(),
    runtimeKind: "local_loopback",
    getRuntimeHealth,
  };
}

describe("App discovery navigation", () => {
  it("renders a truthful content-free recovery screen for an unknown route", async () => {
    const platform = createMemoryPlatform({ name: "not_found" });
    render(
      <App
        runtime={syntheticRuntime()}
        platform={platform}
      />,
    );

    const recovery = screen.getByRole("region", { name: "Page not found" });
    expect(within(recovery).getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(within(recovery).getByText(/invalid path is not retained or displayed/i)).toBeVisible();
    expect(document.title).toBe("Page not found · Prompt Enhancer");
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Open Overview" }));

    await waitFor(() => expect(platform.currentRoute()).toEqual({ name: "overview" }));
    await waitFor(() => expect(document.title).toBe("Overview · Prompt Enhancer"));
    await waitFor(() => expect(document.getElementById("main-content")).toHaveFocus());
  });

  it("keeps the rendered screen, title and active navigation synchronized with browser history", async () => {
    window.history.replaceState(null, "", "/overview");
    const platform = createBrowserPlatform(window);
    const view = render(<App runtime={syntheticRuntime()} platform={platform} />);

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    expect(document.title).toBe("Overview · Prompt Enhancer");
    expect(screen.getByRole("button", { name: "Overview", current: "page" })).toBeVisible();

    window.history.pushState(null, "", "/sessions");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
    expect(document.title).toBe("Sessions · Prompt Enhancer");
    expect(screen.getByRole("button", { name: "Sessions", current: "page" })).toBeVisible();
    expect(document.getElementById("main-content")).toHaveFocus();

    window.history.pushState(null, "", "/unrecognized-sensitive-shaped-route");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByRole("region", { name: "Page not found" })).toBeVisible();
    expect(document.title).toBe("Page not found · Prompt Enhancer");
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(0);
    expect(document.body).not.toHaveTextContent("unrecognized-sensitive-shaped-route");

    view.unmount();
    window.history.replaceState(null, "", "/");
  });

  it("exposes a responsive shell with a keyboard skip target", () => {
    const { container } = render(
      <App
        runtime={syntheticRuntime()}
        platform={createMemoryPlatform()}
      />,
    );

    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(container.querySelector(".app-shell")).toHaveAttribute(
      "data-layout",
      "responsive-shell",
    );
    expect(container.querySelector("#main-content")).toHaveAttribute("tabindex", "-1");
    const primaryNavigation = screen.getByRole("navigation", { name: "Primary" });
    expect(primaryNavigation).toBeVisible();
    expect(within(primaryNavigation).getAllByRole("group")).toHaveLength(3);
    const navigationGlyphs = within(primaryNavigation).getAllByRole("button").map(
      (button) => button.querySelector("svg")?.innerHTML,
    );
    expect(navigationGlyphs.every(Boolean)).toBe(true);
    expect(new Set(navigationGlyphs).size).toBe(navigationGlyphs.length);
    expect(screen.getByLabelText("Synthetic demo fixture ready")).toBeVisible();
    expect(screen.getByText("Synthetic demo · Fixture ready")).toBeVisible();
    expect(
      screen.getByLabelText(/Private by default\. Mobile runtime status: Synthetic demo fixture ready/),
    ).toBeInTheDocument();
  });

  it("keeps the content-free software update action in the desktop sidebar", async () => {
    const transport = createSyntheticTransport();
    const status = {
      contract_version: "application-update-status.v3" as const,
      instance_id: "a".repeat(32),
      revision: 1,
      contains_private_data: false as const,
      installed_version: "1.2.3",
      channel: "stable" as const,
      state: "current" as const,
      available_version: null,
      artifact_size_bytes: null,
      downloaded_bytes: null,
      last_checked_at: "2040-01-02T03:04:05Z",
      reason_code: null,
      verification_code: null,
      can_check: true,
      can_stage: false,
      can_cancel: false,
      can_retry: false,
      can_apply: false as const,
      can_verify: false,
      package_review: { state: "not_configured" as const, reason_code: null, checked_at: null },
    };
    transport.getApplicationUpdateStatus = vi.fn(async () => status);
    transport.checkApplicationUpdate = vi.fn(async () => status);
    render(<App runtime={syntheticRuntime(transport)} platform={createMemoryPlatform()} />);

    const sidebar = screen.getByRole("complementary", { name: "Application" });
    const button = await within(sidebar).findByRole("button", { name: /software is current/i });
    fireEvent.click(button);
    fireEvent.click(within(sidebar).getByRole("button", { name: /check for updates/i }));

    await waitFor(() => expect(transport.checkApplicationUpdate).toHaveBeenCalledOnce());
    expect(within(sidebar).getByRole("region", { name: "Software updates" })).toHaveAttribute(
      "data-update-state",
      "current",
    );
  });

  it("includes the same update status in compact navigation", async () => {
    render(<App runtime={syntheticRuntime()} platform={createMemoryPlatform()} />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));

    const dialog = screen.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
    const update = within(dialog).getByRole("region", { name: "Software updates" });
    expect(await within(update).findByRole("button", { name: /updates not connected/i })).toBeEnabled();
    expect(within(dialog).getByText(/no automatic update traffic/i)).toBeVisible();
  });

  it("gives the Agent workbench a focused shell at medium desktop widths", () => {
    const previousMatchMedia = window.matchMedia;
    const removeEventListener = vi.fn();
    const matchMedia = vi.fn((query: string): MediaQueryList => ({
      matches: query === "(max-width: 1180px)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    }));
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: matchMedia,
    });

    try {
      const { container, unmount } = render(
        <App
          runtime={syntheticRuntime()}
          platform={createMemoryPlatform({ name: "agent" })}
        />,
      );

      expect(container.querySelector(".app-shell")).toHaveClass("app-shell--agent-focus");
      expect(matchMedia).toHaveBeenCalledWith("(max-width: 1180px)");
      unmount();
      expect(removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
    } finally {
      Object.defineProperty(window, "matchMedia", {
        configurable: true,
        value: previousMatchMedia,
      });
    }
  });

  it("opens a grouped mobile navigation dialog and initially focuses the current destination", async () => {
    render(
      <App
        runtime={syntheticRuntime()}
        platform={createMemoryPlatform({ name: "overview" })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
    const mobileNavigation = within(dialog).getByRole("navigation", { name: "Mobile primary" });
    expect(within(mobileNavigation).getAllByRole("group")).toHaveLength(3);
    const overview = within(mobileNavigation).getByRole("button", { name: "Overview" });
    expect(overview).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(overview).toHaveFocus());

    fireEvent.click(within(mobileNavigation).getByRole("button", { name: "Sessions" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Navigate Prompt Enhancer" })).not.toBeInTheDocument();
  });

  it("keeps the controlled Labs disclosure state aligned with native toggles", () => {
    render(<App runtime={syntheticRuntime()} platform={createMemoryPlatform()} />);

    const navigation = screen.getByRole("navigation", { name: "Primary" });
    const labs = navigation.querySelector("details");
    const summary = labs?.querySelector("summary");
    expect(labs).not.toBeNull();
    expect(summary).not.toBeNull();
    expect(labs).not.toHaveAttribute("open");

    fireEvent.click(summary!);
    expect(labs).toHaveAttribute("open");
    fireEvent.click(summary!);
    expect(labs).not.toHaveAttribute("open");
  });

  it("keeps reviewed-task progress visible after the mobile drawer closes", async () => {
    const transport = createSyntheticTransport();
    const response = await transport.listTaskRevisions();
    const pending = deferred<typeof response>();
    transport.listTaskRevisions = vi.fn(() => pending.promise);
    render(
      <App
        runtime={syntheticRuntime(transport)}
        platform={createMemoryPlatform({ name: "overview" })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reviewed tasks" }));

    await waitFor(() => expect(transport.listTaskRevisions).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog", { name: "Navigate Prompt Enhancer" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Opening reviewed task$/ })).toHaveTextContent(
      "Opening…",
    );
    expect(
      screen.getAllByRole("status").some((status) => status.textContent === "Opening reviewed task…"),
    ).toBe(true);

    await act(async () => {
      pending.resolve(response);
      await pending.promise;
    });
  });

  it("sets an exact initial title without stealing focus, then focuses main on click navigation only", async () => {
    document.title = "Prompt Enhancer";
    render(
      <App
        runtime={syntheticRuntime()}
        platform={createMemoryPlatform()}
      />,
    );

    const main = document.querySelector<HTMLElement>("#main-content")!;
    expect(document.title).toBe("Discovery · Prompt Enhancer");
    expect(main).not.toHaveFocus();
    await screen.findByRole("heading", { name: "Discovery inbox" }, { timeout: 5_000 });

    const sessionsNavigation = screen.getByRole("button", { name: "Sessions" });
    sessionsNavigation.focus();
    fireEvent.click(sessionsNavigation);

    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" }, { timeout: 5_000 })).toBeVisible();
    await waitFor(() => expect(main).toHaveFocus());
    expect(document.title).toBe("Sessions · Prompt Enhancer");

    const search = screen.getByRole("searchbox", { name: "Search sessions by project or title" });
    search.focus();
    fireEvent.change(search, { target: { value: "fictional" } });
    expect(search).toHaveFocus();
    expect(document.title).toBe("Sessions · Prompt Enhancer");
  }, 10_000);

  it("leaves project-workspace titles and subsequent heading focus to the finer route policy", async () => {
    render(
      <App
        platform={createMemoryPlatform({
          name: "project_overview",
          projectId: SYNTHETIC_QUALITY_PROJECT_ID,
        })}
        runtime={syntheticRuntime()}
      />,
    );

    const deckHeading = await screen.findByRole(
      "heading",
      { name: "What do you want to review?" },
      { timeout: 5_000 },
    );
    await waitFor(() => expect(document.title).toBe("Metric deck · Synthetic Metric Lab · Prompt Enhancer"));
    expect(deckHeading).not.toHaveFocus();

    const projectNavigation = screen.getByRole("navigation", { name: "Project sections" });
    fireEvent.click(within(projectNavigation).getByRole("link", { name: /Sessions, 1 indexed/ }));

    const sessionsHeading = await screen.findByRole(
      "heading",
      { level: 2, name: "Sessions" },
      { timeout: 5_000 },
    );
    await waitFor(() => expect(sessionsHeading).toHaveFocus());
    expect(document.title).toBe("Sessions · Synthetic Metric Lab · Prompt Enhancer");
  }, 10_000);

  it("keeps the sidebar review count synchronized after a decision", async () => {
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime()}
      />,
    );

    expect(await screen.findByLabelText("2 candidates need review")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Accept as one task" }));
    expect(await screen.findByLabelText("1 candidate needs review")).toBeVisible();
  });

  it("announces a reviewed-task navigation result in one live status region", async () => {
    const transport = createSyntheticTransport();
    transport.listTaskRevisions = vi.fn(async () => ({ limit: 100, offset: 0, tasks: [] }));
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime(transport)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reviewed tasks" }));

    const notices = await screen.findAllByText("No reviewed task is available yet.");
    expect(notices).toHaveLength(1);
    expect(notices[0]).toHaveAttribute("role", "status");

    fireEvent.click(screen.getByRole("button", { name: "Sessions" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
    expect(screen.queryByText("No reviewed task is available yet.")).toBeNull();
  });

  it("aborts a pending reviewed-task lookup when newer navigation wins", async () => {
    const transport = createSyntheticTransport();
    const response = await transport.listTaskRevisions();
    const pending = deferred<typeof response>();
    transport.listTaskRevisions = vi.fn((_taskId?: string, _signal?: AbortSignal) => pending.promise);
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime(transport)}
      />,
    );

    const reviewedTasks = screen.getByRole("button", { name: "Reviewed tasks" });
    fireEvent.click(reviewedTasks);
    await waitFor(() => expect(transport.listTaskRevisions).toHaveBeenCalledTimes(1));
    expect(reviewedTasks).toBeDisabled();
    expect(reviewedTasks).toHaveAttribute("aria-busy", "true");
    expect(reviewedTasks).toHaveTextContent("Opening reviewed task…");
    const signal = vi.mocked(transport.listTaskRevisions).mock.calls[0][1];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Sessions" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
    expect(signal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve(response);
      await pending.promise;
    });
    expect(screen.getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
    expect(screen.queryByText(/reviewed task is available|task index could not be loaded/i)).toBeNull();
  });

  it("keeps fictional projects available in preview while local-source controls stay local", async () => {
    const { unmount } = render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Data sources" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Projects" })).toBeVisible();
    unmount();

    const local = localFixtureTransport(async () => HEALTHY_LOCAL_RUNTIME);
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("local_real", local)}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Data sources" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Projects" })).toBeVisible();
    expect(
      await screen.findByLabelText("Local loopback service available"),
    ).toBeVisible();
  });

  it("shows an accessible deterministic fallback while a route bundle loads", async () => {
    render(
      <App
        platform={createMemoryPlatform({ name: "research" })}
        runtime={syntheticRuntime()}
      />,
    );

    const fallback = screen.getByText("Loading Methods & models…").closest(".async-state");
    expect(fallback).toHaveAttribute("role", "status");
    expect(fallback).toHaveAttribute("aria-atomic", "true");
    expect(fallback).toHaveAttribute("aria-live", "polite");
    expect(screen.getByLabelText("Current location")).toHaveTextContent("Methods & models");
    expect(
      await screen.findByRole("heading", { name: "Methods & models" }),
    ).toBeVisible();
  });

  it("reports local service checking before a successful health response", async () => {
    let resolveHealth!: (health: RuntimeHealth) => void;
    const getRuntimeHealth = vi.fn(
      () =>
        new Promise<RuntimeHealth>((resolve) => {
          resolveHealth = resolve;
        }),
    );
    const local = localFixtureTransport(getRuntimeHealth);

    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("local_real", local)}
      />,
    );

    expect(
      screen.getByLabelText("Local loopback service is being checked"),
    ).toBeVisible();
    expect(screen.getByText("Local real · Checking service")).toBeVisible();

    await act(async () => resolveHealth(HEALTHY_LOCAL_RUNTIME));

    expect(
      await screen.findByLabelText("Local loopback service available"),
    ).toBeVisible();
    expect(getRuntimeHealth).toHaveBeenCalledTimes(1);
  });

  it("reports local service unavailable when the health check fails", async () => {
    const getRuntimeHealth = vi.fn().mockRejectedValue(new Error("SYNTHETIC_PRIVATE_HEALTH_FAILURE"));
    const local = localFixtureTransport(getRuntimeHealth);

    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("local_real", local)}
      />,
    );

    expect(
      await screen.findByLabelText("Local loopback service unavailable"),
    ).toBeVisible();
    expect(screen.getByText("Local real · Service unavailable")).toBeVisible();
    expect(document.body).not.toHaveTextContent("SYNTHETIC_PRIVATE_HEALTH_FAILURE");
    expect(getRuntimeHealth).toHaveBeenCalledTimes(1);
    getRuntimeHealth.mockResolvedValueOnce(HEALTHY_LOCAL_RUNTIME);
    fireEvent.click(screen.getByRole("button", { name: "Recheck local service" }));
    expect(await screen.findByLabelText("Local loopback service available")).toBeVisible();
    expect(getRuntimeHealth).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Recheck local service" })).toBeNull();
  });

  it("ignores a stale health failure after the runtime transport changes", async () => {
    const older = deferred<RuntimeHealth>();
    const current = deferred<RuntimeHealth>();
    const olderRuntime = createRuntimeComposition(
      "local_real",
      localFixtureTransport(vi.fn(() => older.promise)),
    );
    const currentRuntime = createRuntimeComposition(
      "local_real",
      localFixtureTransport(vi.fn(() => current.promise)),
    );
    const platform = createMemoryPlatform({ name: "overview" });
    const view = render(<App platform={platform} runtime={olderRuntime} />);

    expect(screen.getByLabelText("Local loopback service is being checked")).toBeVisible();
    view.rerender(<App platform={platform} runtime={currentRuntime} />);
    await act(async () => current.resolve(HEALTHY_LOCAL_RUNTIME));
    expect(await screen.findByLabelText("Local loopback service available")).toBeVisible();

    await act(async () => {
      older.reject(new Error("SYNTHETIC_STALE_PRIVATE_HEALTH_FAILURE"));
      await older.promise.catch(() => undefined);
    });
    expect(screen.getByLabelText("Local loopback service available")).toBeVisible();
    expect(screen.queryByLabelText("Local loopback service unavailable")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SYNTHETIC_STALE_PRIVATE_HEALTH_FAILURE");
  });

  it("does not contact local-source APIs for a synthetic direct route", () => {
    const transport = createSyntheticTransport();
    const statusSpy = vi.spyOn(transport, "getCodexLocalSourceStatus");
    render(
      <App
        platform={createMemoryPlatform({ name: "local_sources" })}
        runtime={syntheticRuntime(transport)}
      />,
    );

    expect(
      screen.getByText("Data sources are disabled in synthetic preview"),
    ).toBeVisible();
    const closedState = screen.getByText("Data sources are disabled in synthetic preview")
      .closest(".ui-empty-state");
    expect(closedState).toHaveAttribute("data-tone", "closed");
    expect(closedState).toHaveAttribute("role", "status");
    expect(statusSpy).not.toHaveBeenCalled();
  });

  it("opens the methods and models lab from primary navigation", async () => {
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Methods & models" }));
    expect(
      await screen.findByRole("heading", { name: "Methods & models" }),
    ).toBeVisible();
  });

  it("opens a truthful synthetic job centre without inventing queue records", async () => {
    const transport = createSyntheticTransport();
    const listJobs = vi.spyOn(transport, "listAnalysisJobs");
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={syntheticRuntime(transport)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Analysis jobs" }));
    expect(await screen.findByRole("heading", { name: "Analysis jobs" })).toBeVisible();
    expect(screen.getByText("No jobs ran")).toBeVisible();
    expect(listJobs).not.toHaveBeenCalled();
  });

  it("loads the authenticated job centre only after local health succeeds", async () => {
    const local = localFixtureTransport(async () => HEALTHY_LOCAL_RUNTIME);
    const listJobs = vi.fn(async () => ({ jobs: [], limit: 25, offset: 0 }));
    local.listAnalysisJobs = listJobs;
    render(
      <App
        platform={createMemoryPlatform({ name: "analysis_jobs" })}
        runtime={createRuntimeComposition("local_real", local)}
      />,
    );

    expect(await screen.findByLabelText("Local loopback service available")).toBeVisible();
    expect(await screen.findByText(/no durable jobs match this filter/i)).toBeVisible();
    expect(listJobs).toHaveBeenCalledWith(null, 25, 0, expect.any(AbortSignal));
  });

  it("renders project automation as explicitly non-operational in synthetic mode", async () => {
    const transport = createSyntheticTransport();
    const listGrants = vi.spyOn(transport, "listAutomationGrants");
    const listSessions = vi.spyOn(transport, "listProjectSessions");
    render(
      <App
        platform={createMemoryPlatform({
          name: "project_automation",
          projectId: SYNTHETIC_QUALITY_PROJECT_ID,
        })}
        runtime={syntheticRuntime(transport)}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Project automation" })).toBeVisible();
    expect(screen.getByText("Automation is not running")).toBeVisible();
    expect(screen.getByRole("button", { name: "Projects" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(listGrants).not.toHaveBeenCalled();
    expect(listSessions).not.toHaveBeenCalled();
  });

  it("isolates a failed route, offers a truthful exit, and retries the same route", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onExit = vi.fn();
    let shouldFail = true;
    function FailingRoute() {
      if (shouldFail) throw new Error("SYNTHETIC_ROUTE_FAILURE_CANARY");
      return <p>Recovered route</p>;
    }

    render(
      <main id="main-content" tabIndex={-1}>
        <RouteErrorBoundary exitLabel="Return to Discovery" onExit={onExit} resetKey="/failed-route">
          <FailingRoute />
        </RouteErrorBoundary>
      </main>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This screen could not be loaded");
    expect(screen.getByRole("alert")).toHaveTextContent(/No provider error or session content is shown/);
    expect(document.body.textContent).not.toContain("SYNTHETIC_ROUTE_FAILURE_CANARY");
    fireEvent.click(screen.getByRole("button", { name: "Return to Discovery" }));
    expect(onExit).toHaveBeenCalledTimes(1);

    shouldFail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry screen" }));
    expect(await screen.findByText("Recovered route")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(document.getElementById("main-content")).toHaveFocus();
    consoleError.mockRestore();
  });

  it("retries a rejected lazy import only after an explicit screen retry", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error("SYNTHETIC_IMPORT_FAILURE"))
      .mockResolvedValue({ default: () => <p>Recovered imported screen</p> });
    const Screen = retryableLazy(loader);
    render(<RouteErrorBoundary resetKey="/synthetic"><Suspense fallback={<p>Loading route</p>}><Screen /></Suspense></RouteErrorBoundary>);
    await screen.findByRole("button", { name: "Retry screen" });
    expect(loader).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Reload app" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry screen" }));
    expect(await screen.findByText("Recovered imported screen")).toBeVisible();
    expect(loader).toHaveBeenCalledTimes(2);
    consoleError.mockRestore();
  });

  it("keeps a healthy lazy workspace mounted when only its route key changes", async () => {
    const loader = vi.fn(async () => ({ default: function ExampleWorkspace() {
      const [count, setCount] = useState(0);
      return <button onClick={() => setCount((value) => value + 1)} type="button">Example state {count}</button>;
    } }));
    const Screen = retryableLazy(loader);
    const child = <Suspense fallback="Loading"><Screen /></Suspense>;
    const { rerender } = render(<RouteErrorBoundary resetKey="/example/a">{child}</RouteErrorBoundary>);
    fireEvent.click(await screen.findByRole("button", { name: "Example state 0" }));
    rerender(<RouteErrorBoundary resetKey="/example/b">{child}</RouteErrorBoundary>);
    expect(screen.getByRole("button", { name: "Example state 1" })).toBeVisible();
    expect(loader).toHaveBeenCalledOnce();
  });

  it("omits a circular exit action when retry is the only truthful route recovery", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function FailingRoute(): never {
      throw new Error("SYNTHETIC_DISCOVERY_FAILURE_CANARY");
    }

    render(
      <RouteErrorBoundary resetKey="/">
        <FailingRoute />
      </RouteErrorBoundary>,
    );

    expect(screen.getByRole("button", { name: "Retry screen" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Return|Leave/ })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SYNTHETIC_DISCOVERY_FAILURE_CANARY");
    consoleError.mockRestore();
  });

  it("renders the fictional project catalog in synthetic preview", async () => {
    const transport = createSyntheticTransport();
    const listSpy = vi.spyOn(transport, "listCodexSessions");
    const coverageSpy = vi.spyOn(transport, "getMetricCoverage");
    render(
      <App
        platform={createMemoryPlatform({ name: "projects" })}
        runtime={syntheticRuntime(transport)}
      />,
    );

    expect(await screen.findByText("Synthetic Metric Lab")).toBeVisible();
    expect(listSpy).toHaveBeenCalledTimes(1);
    expect(coverageSpy).toHaveBeenCalledWith("synthetic", expect.any(AbortSignal));
  });

  it("selects codex coverage for the local runtime", async () => {
    const local = localFixtureTransport(async () => HEALTHY_LOCAL_RUNTIME);
    local.listCodexSessions = vi.fn(async () => ({ sessions: [], limit: 100, offset: 0 }));
    const coverage = vi.spyOn(local, "getMetricCoverage").mockRejectedValue(
      new Error("Synthetic local coverage failure"),
    );
    render(
      <App
        platform={createMemoryPlatform({ name: "projects" })}
        runtime={createRuntimeComposition("local_real", local)}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Metric coverage: Unknown" }))
      .toBeVisible();
    expect(coverage).toHaveBeenCalledWith("codex", expect.any(AbortSignal));
  });

  it("supports a direct fictional canonical metric route with an optional legacy QA disclosure", async () => {
    render(
      <App
        platform={createMemoryPlatform({
          name: "session_metrics",
          projectId: SYNTHETIC_QUALITY_PROJECT_ID,
          sessionId: SYNTHETIC_QUALITY_SESSION_ID,
          category: "prompt-quality",
        })}
        runtime={syntheticRuntime()}
      />,
    );

    expect(await screen.findByRole("heading", {
      name: "Measure the analyzed window, then estimate every eligible axis locally",
    })).toBeVisible();
    fireEvent.click(screen.getByText("Legacy coaching profile"));
    expect(await screen.findByText("Coherent metric pack v3")).toBeVisible();
    expect(
      screen.getByRole("img", { name: /6-axis 100% fixed-scale quality lens radar/i }),
    ).toBeVisible();
    expect(await screen.findByText("Verification passed")).toBeVisible();
    expect(screen.getByText("Watch for:")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Analyze locally" })).toBeEnabled();
    expect(
      screen.getByRole("heading", { name: "Prompt & collaboration coaching" }),
    ).toBeVisible();
  });

  it("renders a project quality profile from one server-style aggregate call", async () => {
    const transport = createSyntheticTransport();
    const aggregate = vi.spyOn(transport, "aggregateSessionQuality");
    const latest = vi.spyOn(transport, "getLatestSessionQualityAnalysis");
    render(
      <App
        platform={createMemoryPlatform({
          name: "project_metrics",
          projectId: SYNTHETIC_QUALITY_PROJECT_ID,
          category: "prompt-quality",
        })}
        runtime={syntheticRuntime(transport)}
      />,
    );

    expect(await screen.findByText("1 of 1 selected sessions have a compatible Coaching v1 run")).toBeVisible();
    expect(screen.getByText("Coherent metric pack v3")).toBeVisible();
    expect(
      screen.getByRole("img", { name: /6-axis 100% fixed-scale quality lens radar/i }),
    ).toBeVisible();
    expect(aggregate).toHaveBeenCalledWith(
      { session_ids: [SYNTHETIC_QUALITY_SESSION_ID] },
      expect.any(AbortSignal),
    );
    expect(latest).not.toHaveBeenCalled();
  });
});
