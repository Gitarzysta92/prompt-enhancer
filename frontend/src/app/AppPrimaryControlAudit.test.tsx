import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createSyntheticTransport } from "../shared/api/syntheticTransport";
import type { AppRoute, PlatformAdapter } from "../shared/platform/platform";
import { createRuntimeComposition } from "../shared/platform/runtimeMode";
import { App } from "./App";
import { auditControlSurface } from "./appControlAudit.test-support";
import { routeMetadata } from "./appRouteManifest";

const PRIMARY_ROUTES = [
  { name: "overview" },
  { name: "projects" },
  { name: "sessions" },
  { name: "agent" },
  { name: "models" },
] as const satisfies readonly AppRoute[];

const READY_HEADING: Record<(typeof PRIMARY_ROUTES)[number]["name"], string> = {
  overview: "Overview",
  projects: "Projects",
  sessions: "Sessions",
  agent: "Agent workspace",
  models: "Models",
};

const SECONDARY_ROUTES = [
  { route: { name: "discovery" }, ready: "Discovery inbox" },
  { route: { name: "task_flow" }, ready: "Task flow" },
  { route: { name: "prompt_checks" }, ready: "Check a prompt" },
  { route: { name: "calibration" }, ready: "Rate sessions" },
  { route: { name: "analysis_jobs" }, ready: "Analysis jobs" },
  { route: { name: "research" }, ready: "Methods & models" },
  { route: { name: "team" }, ready: "Team analytics" },
  { route: { name: "social" }, ready: "Social hub" },
] as const satisfies readonly { route: AppRoute; ready: string }[];

const LOCAL_REAL_REGRESSION_ROUTES = [
  { route: { name: "agent" }, ready: "Agent workspace" },
  { route: { name: "models" }, ready: "Models" },
  { route: { name: "prompt_checks" }, ready: "Check a prompt" },
  { route: { name: "analysis_jobs" }, ready: "Analysis jobs" },
  { route: { name: "local_sources" }, ready: "Data sources" },
] as const satisfies readonly { route: AppRoute; ready: string }[];

function fixedPlatform(route: AppRoute): PlatformAdapter {
  return {
    currentRoute: () => route,
    navigate: () => undefined,
    subscribe: () => () => undefined,
  };
}

function localAuditRuntime() {
  const fixture = createSyntheticTransport();
  return createRuntimeComposition("local_real", {
    ...fixture,
    runtimeKind: "local_loopback" as const,
    getRuntimeHealth: async () => ({
      status: "ok" as const,
      costMode: "offline_only" as const,
      dataTier: "metadata" as const,
    }),
  });
}

describe("route-level control explanations", () => {
  it.each(PRIMARY_ROUTES)("$name gives every initially disabled control an accessible reason", async (route) => {
    const metadata = routeMetadata(route);
    render(
      <App
        platform={fixedPlatform(route)}
        runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText(`Loading ${metadata.title}…`)).not.toBeInTheDocument();
    }, { timeout: 10_000 });
    await screen.findByRole(
      "heading",
      { level: 1, name: READY_HEADING[route.name] },
      { timeout: 10_000 },
    );

    const main = document.getElementById("main-content");
    expect(main).not.toBeNull();
    await waitFor(() => expect(main?.textContent?.trim()).not.toBe(""), { timeout: 10_000 });

    expect(auditControlSurface(main as HTMLElement)).toEqual([]);
  }, 15_000);

  it.each(SECONDARY_ROUTES)(
    "$route.name gives every initially disabled control an accessible reason",
    async ({ route, ready }) => {
      const metadata = routeMetadata(route);
      render(
        <App
          platform={fixedPlatform(route)}
          runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
        />,
      );

      await waitFor(() => {
        expect(screen.queryByText(`Loading ${metadata.title}…`)).not.toBeInTheDocument();
      }, { timeout: 10_000 });
      await screen.findByRole("heading", { level: 1, name: ready }, { timeout: 10_000 });

      const main = document.getElementById("main-content");
      expect(main).not.toBeNull();
      expect(auditControlSurface(main as HTMLElement)).toEqual([]);
    },
    15_000,
  );

  it("keeps the synthetic Data sources gate actionable without a disabled dead end", async () => {
    const route = { name: "local_sources" } as const;
    render(
      <App
        platform={fixedPlatform(route)}
        runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
      />,
    );

    await screen.findByText("Data sources are disabled in synthetic preview");
    const main = document.getElementById("main-content");
    expect(main).not.toBeNull();
    expect(auditControlSurface(main as HTMLElement)).toEqual([]);
    expect(screen.getByRole("button", { name: "Return to Discovery" })).toBeEnabled();
  });

  it.each(LOCAL_REAL_REGRESSION_ROUTES)(
    "$route.name gives every settled local-real control an accessible reason",
    async ({ route, ready }) => {
      const metadata = routeMetadata(route);
      render(<App platform={fixedPlatform(route)} runtime={localAuditRuntime()} />);

      await waitFor(() => {
        expect(screen.queryByText(`Loading ${metadata.title}…`)).not.toBeInTheDocument();
      }, { timeout: 10_000 });
      await screen.findByRole("heading", { level: 1, name: ready }, { timeout: 10_000 });
      await screen.findByText("Local real · Service available", {}, { timeout: 10_000 });

      const main = document.getElementById("main-content");
      expect(main).not.toBeNull();
      await waitFor(() => expect(auditControlSurface(main as HTMLElement)).toEqual([]), {
        timeout: 10_000,
      });
    },
    15_000,
  );
});
