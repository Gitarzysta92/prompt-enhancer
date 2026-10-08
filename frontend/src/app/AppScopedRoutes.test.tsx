import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createSyntheticTransport } from "../shared/api/syntheticTransport";
import { createSyntheticTeamControlPlanePort } from "../shared/api/teamControlPlaneSynthetic";
import type { TeamControlPlanePort } from "../shared/api/teamControlPlane";
import type { AppRoute, PlatformAdapter } from "../shared/platform/platform";
import { parseRoute, routePath } from "../shared/platform/platform";
import { createRuntimeComposition } from "../shared/platform/runtimeMode";
import type { LocalRuntimeTransport } from "../shared/platform/runtimeMode";
import { App } from "./App";

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

function openLabsNavigation(): void {
  const summary = [...document.querySelectorAll("summary")]
    .find((candidate) => candidate.textContent?.trim() === "Labs");
  expect(summary).toBeDefined();
  fireEvent.click(summary!);
}

describe("scoped analytics and task flow routes", () => {
  it("round-trips the new routes through the platform paths", () => {
    expect(routePath({ name: "team" })).toBe("/team");
    expect(routePath({ name: "task_flow" })).toBe("/tasks/flow");
    expect(parseRoute("/team")).toEqual({ name: "team" });
    expect(parseRoute("/tasks/flow/")).toEqual({ name: "task_flow" });
    expect(parseRoute("/tasks/flow/extra")).toEqual({ name: "not_found" });
  });

  it("navigates to Team analytics with the synthetic port and a scoped trail", async () => {
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
      />,
    );
    openLabsNavigation();
    fireEvent.click(screen.getByRole("button", { name: "Team analytics (preview)" }));
    expect(await screen.findByRole(
      "heading",
      { level: 1, name: "Team analytics" },
      { timeout: 5_000 },
    )).toBeVisible();
    expect(screen.getByLabelText("Current location").textContent).toContain("Scoped workspace");
    expect(await screen.findByRole("group", { name: "Analytics scope" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Team analytics (preview)" })).toHaveAttribute("aria-current", "page");
  });

  it("navigates to Task flow and keeps the personal trail", async () => {
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Task flow" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Task flow" })).toBeVisible();
    expect(screen.getByLabelText("Current location").textContent).toContain("Personal workspace");
    expect(await screen.findByRole("group", { name: "Task flow board" })).toBeVisible();
  });

  it("does not compose even a fully relabelled synthetic team port into local-real mode", async () => {
    const fixtureBackedLoopbackStub: LocalRuntimeTransport = {
      ...createSyntheticTransport(),
      runtimeKind: "local_loopback",
      getRuntimeHealth: async () => ({ status: "ok", costMode: "offline_only", dataTier: "metadata" }),
    };
    const fixture = createSyntheticTeamControlPlanePort();
    const relabelledFixture: TeamControlPlanePort = {
      portVersion: fixture.portVersion,
      origin: "local_loopback",
      principalId: fixture.principalId,
      async getCapabilities(signal) {
        return { ...await fixture.getCapabilities(signal), origin: "local_loopback" };
      },
      async getAggregate(scope, signal) {
        return { ...await fixture.getAggregate(scope, signal), origin: "local_loopback" };
      },
      async getMemberVisibility(request, signal) {
        return { ...await fixture.getMemberVisibility(request, signal), origin: "local_loopback" };
      },
    };
    render(
      <App
        platform={createMemoryPlatform({ name: "team" })}
        runtime={createRuntimeComposition("local_real", fixtureBackedLoopbackStub)}
        teamControlPlane={relabelledFixture}
      />,
    );
    expect(await screen.findByText("Me scope is not served here")).toBeVisible();
    expect(screen.queryByText(/Synthetic platform guild/)).toBeNull();
    expect(screen.getByText(/exact immutable scope and cohort query identity/)).toBeVisible();
  });
});

describe("social hub route", () => {
  it("round-trips /social and opens the fictional social workspace in the synthetic preview", async () => {
    expect(routePath({ name: "social" })).toBe("/social");
    expect(parseRoute("/social/")).toEqual({ name: "social" });
    expect(parseRoute("/social/extra")).toEqual({ name: "not_found" });
    render(
      <App
        platform={createMemoryPlatform()}
        runtime={createRuntimeComposition("synthetic_demo", createSyntheticTransport())}
      />,
    );
    openLabsNavigation();
    fireEvent.click(screen.getByRole("button", { name: "Social hub (demo)" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Social hub" }, { timeout: 5_000 })).toBeVisible();
    expect(screen.getByLabelText("Current location").textContent).toContain("Social workspace");
    expect(await screen.findByRole("note", { name: "Fictional synthetic demo" })).toBeVisible();
    expect(await screen.findByRole("group", { name: "Local social state summary" })).toHaveTextContent("3 friends");
    expect(screen.getByRole("button", { name: "Social hub (demo)" })).toHaveAttribute("aria-current", "page");
  });

  it("fails closed for Social in local-real mode even when a fixture social port is injected", async () => {
    const loopbackStub: LocalRuntimeTransport = {
      ...createSyntheticTransport(),
      runtimeKind: "local_loopback",
      getRuntimeHealth: async () => ({ status: "ok", costMode: "offline_only", dataTier: "metadata" }),
    };
    const { createSyntheticSocialHubPort } = await import("../shared/api/socialHub");
    render(
      <App
        platform={createMemoryPlatform({ name: "social" })}
        runtime={createRuntimeComposition("local_real", loopbackStub)}
        socialHub={createSyntheticSocialHubPort()}
      />,
    );
    const closed = await screen.findByText("Social features are not served in this runtime", {}, { timeout: 5_000 });
    expect(closed).toBeVisible();
    expect(screen.getByText(/0 friends · 0 relationships · 0 requests · 0 conversations · 0 messages · 0 file offers · presence not shared/)).toBeVisible();
    expect(screen.queryByRole("note", { name: "Fictional synthetic demo" })).toBeNull();
    expect(screen.queryByText(/Alex Example/)).toBeNull();
  });
});
