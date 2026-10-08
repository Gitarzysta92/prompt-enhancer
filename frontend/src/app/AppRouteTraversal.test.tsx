import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createSyntheticTransport } from "../shared/api/syntheticTransport";
import type { AppRoute, PlatformAdapter } from "../shared/platform/platform";
import { createRuntimeComposition } from "../shared/platform/runtimeMode";
import { App } from "./App";
import { auditControlSurface } from "./appControlAudit.test-support";
import { routeMetadata } from "./appRouteManifest";

const PROJECT_ID = "a".repeat(64);
const SESSION_ID = "b".repeat(64);
const TASK_ID = "c".repeat(64);
const CHECK_ID = "d".repeat(64);

const DIRECT_ROUTE_EXAMPLES: readonly AppRoute[] = [
  { name: "discovery" },
  { name: "local_sources" },
  { name: "analysis_jobs" },
  { name: "research" },
  { name: "team" },
  { name: "social" },
  { name: "task_flow" },
  { name: "projects" },
  { name: "sessions" },
  { name: "calibration" },
  { name: "models" },
  { name: "prompt_checks" },
  { name: "prompt_checks", checkId: CHECK_ID },
  { name: "prompt_checks", sessionId: SESSION_ID },
  { name: "overview" },
  { name: "agent" },
  { name: "agent", window: true },
  { name: "agent", sessionId: "e".repeat(32), window: true },
  { name: "project_overview", projectId: PROJECT_ID },
  { name: "live", projectId: PROJECT_ID },
  { name: "live", projectId: PROJECT_ID, sessionId: SESSION_ID },
  { name: "project_sessions", projectId: PROJECT_ID },
  { name: "project_automation", projectId: PROJECT_ID },
  { name: "project_metrics", projectId: PROJECT_ID, category: "readiness" },
  {
    name: "session_metrics",
    projectId: PROJECT_ID,
    sessionId: SESSION_ID,
    category: "readiness",
  },
  { name: "task", taskId: TASK_ID, revision: 1 },
  { name: "not_found" },
];

function memoryPlatform(route: AppRoute): PlatformAdapter {
  const listeners = new Set<(next: AppRoute) => void>();
  let current = route;
  return {
    currentRoute: () => current,
    navigate(next) {
      current = next;
      listeners.forEach((listener) => listener(next));
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

function chromeLess(route: AppRoute): boolean {
  return route.name === "live" || (route.name === "agent" && route.window === true);
}

describe("complete direct-route shell traversal", () => {
  it.each(DIRECT_ROUTE_EXAMPLES)(
    "$name resolves to a nonblank, truthfully titled shell",
    async (route) => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
      const metadata = routeMetadata(route);
      render(
        <App
          platform={memoryPlatform(route)}
          runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
        />,
      );

      await waitFor(() => {
        expect(screen.queryByText(`Loading ${metadata.title}…`)).not.toBeInTheDocument();
      }, { timeout: 10_000 });

      const main = document.getElementById("main-content");
      expect(main).not.toBeNull();
      await waitFor(() => expect(main?.textContent?.trim()).not.toBe(""), { timeout: 10_000 });
      if (metadata.titleOwner === "screen") {
        await waitFor(
          () => expect(document.title).not.toBe(`${metadata.title} · Prompt Enhancer`),
          { timeout: 10_000 },
        );
        expect(document.title).toMatch(/ · Prompt Enhancer$/);
        expect(document.title).not.toContain(PROJECT_ID);
        expect(document.title).not.toContain(SESSION_ID);
      } else {
        expect(document.title).toBe(`${metadata.title} · Prompt Enhancer`);
      }
      expect(screen.queryByText("This screen could not be loaded")).not.toBeInTheDocument();

      if (chromeLess(route)) {
        expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
      } else {
        const primary = screen.getByRole("navigation", { name: "Primary" });
        const active = within(primary).queryAllByRole("button", { current: "page" });
        const expectsVisibleOwner = metadata.navigationKey !== null && route.name !== "local_sources";
        expect(active).toHaveLength(expectsVisibleOwner ? 1 : 0);
      }

      expect(auditControlSurface(main as HTMLElement)).toEqual([]);
      expect(consoleError).not.toHaveBeenCalled();
      consoleError.mockRestore();
    },
    15_000,
  );
});
