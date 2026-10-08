import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  teamAggregateRequestForAccess,
  TeamControlPlaneError,
  type AnalyticsScope,
  type TeamAggregateSnapshot,
  type TeamControlPlanePort,
} from "../../shared/api/teamControlPlane";
import {
  createSyntheticTeamControlPlanePort,
  createUnavailableTeamControlPlanePort,
} from "../../shared/api/teamControlPlaneSynthetic";
import { createLocalLoopbackTeamControlPlanePort } from "../../shared/api/teamControlPlaneUnavailable";
import type { AppRoute } from "../../shared/platform/platform";
import { TeamAnalyticsPage } from "./TeamAnalyticsPage";

async function fixtureAggregate(port: TeamControlPlanePort, scope: AnalyticsScope) {
  const report = await port.getCapabilities();
  const request = teamAggregateRequestForAccess(report.scopes.find((candidate) => candidate.scope === scope)!)!;
  return port.getAggregate(request);
}

function renderPage(options: {
  port?: TeamControlPlanePort;
  runtimeMode?: "synthetic_demo" | "local_real";
  serviceState?: "checking" | "available" | "unavailable";
  navigate?: (route: AppRoute) => void;
} = {}) {
  const navigate = options.navigate ?? vi.fn();
  render(
    <TeamAnalyticsPage
      navigate={navigate}
      port={options.port ?? createSyntheticTeamControlPlanePort()}
      runtimeMode={options.runtimeMode ?? "synthetic_demo"}
      serviceState={options.serviceState ?? "available"}
    />,
  );
  return { navigate };
}

describe("TeamAnalyticsPage", () => {
  it("offers retry for a failed allowed-scope read instead of calling the scope unserved", async () => {
    const base = createSyntheticTeamControlPlanePort();
    const getAggregate = vi.fn(base.getAggregate).mockRejectedValueOnce(new TeamControlPlaneError("scope_not_allowed", "SYNTHETIC_PRIVATE_CANARY"));
    renderPage({ port: { ...base, getAggregate } });
    expect(await screen.findByRole("alert")).toHaveTextContent("aggregate could not be loaded");
    expect(screen.queryByText(/Team scope is not served here/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table")).toBeVisible();
    expect(getAggregate).toHaveBeenCalledTimes(2);
    expect(getAggregate.mock.calls[1][0]).toEqual(getAggregate.mock.calls[0][0]);
    expect(document.body.textContent).not.toContain("SYNTHETIC_PRIVATE_CANARY");
  });

  it("renders a permission-aware scope switcher whose blocked scopes stay discoverable", async () => {
    renderPage();
    const group = await screen.findByRole("group", { name: "Analytics scope" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent?.startsWith("Me") || button.textContent?.startsWith("Team") || button.textContent?.startsWith("Organization"))).toEqual([true, true, true]);
    const organization = within(group).getByRole("button", { name: /^Organization/ });
    expect(organization).toHaveAttribute("aria-disabled", "true");
    expect(organization).not.toBeDisabled();
    expect(within(group).getByRole("button", { name: /^Team/ })).toHaveAttribute("aria-pressed", "true");
    const reasons = screen.getByRole("list", { name: "Scopes not available" });
    expect(reasons.textContent).toContain("Organization");
    expect(reasons.textContent).toContain("Not permitted");
    fireEvent.click(organization);
    expect(within(group).getByRole("button", { name: /^Team/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: /^Me/ }));
    expect(await screen.findByRole("heading", { level: 2, name: /This installation only/ })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Member visibility" })).toBeNull();
  });

  it("shows readiness cards that are disabled or unavailable when capabilities are absent", async () => {
    renderPage();
    const list = await screen.findByRole("list", { name: "Capability readiness" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards.map((card) => card.getAttribute("data-card"))).toEqual(["local", "team_sync", "deep_analysis", "billing"]);
    expect(cards[0]).toHaveAttribute("data-state", "ready");
    expect(cards[0].textContent).toContain("Fictional in-memory fixtures");
    expect(cards[1]).toHaveAttribute("data-state", "unavailable");
    expect(cards[1].textContent).toContain("No team sync service exists in this build");
    expect(within(cards[1]).queryByRole("button")).toBeNull();
    expect(cards[3]).toHaveAttribute("data-state", "unavailable");
    expect(cards[3].textContent).toContain("Nothing is metered or charged");
    expect(within(cards[2]).getByRole("button", { name: "Open Methods & models" })).toBeEnabled();
  });

  it("renders the team aggregate table with cohort, missingness, comparability, freshness, and uncertainty", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers).toEqual(["Metric", "Value & uncertainty", "Cohort", "Missingness", "Comparability", "Freshness"]);
    const suppressedRow = within(table).getByRole("row", { name: /Constraint precision/ });
    expect(suppressedRow).toHaveAttribute("data-status", "suppressed");
    expect(suppressedRow.textContent).toContain("Suppressed");
    expect(suppressedRow.textContent).toContain("below minimum of 3");
    expect(suppressedRow.querySelector(".team-interval__point")).toBeNull();
    expect(suppressedRow.querySelector(".team-interval__state")?.textContent).toBe("suppressed · small contributing cohort");
    const knownRow = within(table).getByRole("row", { name: /Task definition coverage/ });
    expect(knownRow.textContent).toContain("72% · 41/57");
    expect(knownRow.textContent).toMatch(/95% interval/);
    expect(knownRow.querySelector(".team-interval__band")).not.toBeNull();
    expect(knownRow.querySelector(".team-interval__model-point")).not.toBeNull();
    expect(document.querySelectorAll("polygon, polyline")).toHaveLength(0);
    // Every row is its own construct: no column, cell, or footer sums or orders members.
    expect(within(table).queryByText(/^Rank|Leaderboard|Overall score/)).toBeNull();
  });

  it("opens the two-sentence explainer from keyboard focus and switches lenses", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const trigger = within(table).getByRole("button", { name: /Task definition coverage/ });
    const description = document.getElementById(trigger.getAttribute("aria-describedby")!);
    expect(description?.textContent).toContain("Measured · typed evidence");
    fireEvent.focus(trigger);
    const card = document.querySelector('[role="region"][data-metric-key]');
    expect(card).not.toBeNull();
    expect(card!.textContent).toContain("Meaning");
    expect(card!.textContent).toContain("Next action");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector('[role="region"][data-metric-key]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Evidence lane lens/ }));
    expect(within(screen.getByRole("table")).getByRole("row", { name: /First-pass verification|first pass/i })).toBeInTheDocument();
  });

  it("reveals individual members only through the explicit audited action", async () => {
    renderPage();
    const reveal = await screen.findByRole("button", { name: "Reveal individual members" });
    expect(reveal).toBeEnabled();
    expect(screen.getAllByText(/written to the local audit log/)).toHaveLength(2);
    expect(screen.queryByText("Member 01")).toBeNull();
    fireEvent.click(reveal);
    expect(await screen.findByText("Member 01", {}, { timeout: 5_000 })).toBeVisible();
    expect(screen.queryByText("Member 05")).toBeNull();
    expect(screen.getByText(/1 withheld consent and is not listed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide individual members" }));
    expect(screen.queryByText("Member 01")).toBeNull();
  }, 10_000);

  it("keeps the member reveal disabled without a grant", async () => {
    renderPage({ port: createSyntheticTeamControlPlanePort({ memberVisibility: "denied" }) });
    const reveal = await screen.findByRole("button", { name: "Reveal individual members" });
    expect(reveal).toBeDisabled();
    expect(screen.getByText(/No permission grants individual member visibility/)).toBeInTheDocument();
  });

  it("states that no scope is served in the local runtime and links to the personal workspace", async () => {
    const navigate = vi.fn();
    renderPage({ port: createUnavailableTeamControlPlanePort(() => "2040-02-01T00:00:00Z"), runtimeMode: "local_real", serviceState: "unavailable", navigate });
    expect(await screen.findByText("Me scope is not served here")).toBeVisible();
    const group = screen.getByRole("group", { name: "Analytics scope" });
    expect(within(group).getByRole("button", { name: /^Team/ })).toHaveAttribute("aria-disabled", "true");
    expect(within(group).getByRole("button", { name: /^Organization/ })).toHaveAttribute("aria-disabled", "true");
    const list = screen.getByRole("list", { name: "Capability readiness" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards[0]).toHaveAttribute("data-state", "unavailable");
    expect(cards[0].textContent).toContain("loopback service did not answer");
    expect(cards[1]).toHaveAttribute("data-state", "unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Open Projects" }));
    expect(navigate).toHaveBeenCalledWith({ name: "projects" });
    await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
    expect(screen.queryByRole("heading", { name: "Member visibility" })).toBeNull();
  });

  it("shows backend readiness in full mode without requesting a cohort aggregate", async () => {
    const port = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => ({
        contract_version: "control-plane-v2",
        delivery_guarantee: "at_least_once_with_monotonic_ack",
        gaps: ["governance_review_pending"],
        production_ready: false,
        profile: "development",
        remote_listening_enabled: false,
      }),
    }, () => "2040-03-01T12:00:00Z");
    const getAggregate = vi.spyOn(port, "getAggregate");

    renderPage({ port, runtimeMode: "local_real", serviceState: "available" });

    expect(await screen.findByText(/Development boundary reachable/)).toBeVisible();
    expect(screen.getByText(/team data remains closed/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
    expect(getAggregate).not.toHaveBeenCalled();
  });

  it("never publishes a late ready snapshot into a different active scope", async () => {
    const base = createSyntheticTeamControlPlanePort();
    let resolveTeam!: (snapshot: TeamAggregateSnapshot) => void;
    const lateTeam = new Promise<TeamAggregateSnapshot>((resolve) => { resolveTeam = resolve; });
    const port: TeamControlPlanePort = {
      ...base,
      getAggregate: (request) => request.scope === "team"
        ? lateTeam
        : base.getAggregate(request),
    };
    render(
      <TeamAnalyticsPage
        navigate={() => undefined}
        port={port}
        runtimeMode="synthetic_demo"
        serviceState="available"
      />,
    );
    const scopes = await screen.findByRole("group", { name: "Analytics scope" });
    fireEvent.click(within(scopes).getByRole("button", { name: /^Me/ }));
    expect(await screen.findByRole("heading", { level: 2, name: /This installation only/ })).toBeVisible();
    await act(async () => { resolveTeam(await fixtureAggregate(base, "team")); });
    expect(screen.getByRole("heading", { level: 2, name: /This installation only/ })).toBeVisible();
    expect(document.querySelector(".team-aggregate-board")).toHaveAttribute("data-scope", "me");
    expect(screen.queryByRole("heading", { level: 2, name: /Synthetic platform guild/ })).toBeNull();
  });

  it("synchronously drops team member rows when the active scope changes to another cohort identity", async () => {
    const base = createSyntheticTeamControlPlanePort();
    const report = await base.getCapabilities();
    const teamSnapshot = await fixtureAggregate(base, "team");
    const organization = {
      principal_id: report.principal_id,
      scope: "organization" as const,
      state: "allowed" as const,
      reason: "granted" as const,
      cohort_label: "Synthetic organization cohort",
      cohort_id: "6d".repeat(32),
      team_id: null,
      organization_id: "7e".repeat(32),
      aggregate_query_id: "8f".repeat(32),
    };
    const getMemberVisibility = vi.fn(base.getMemberVisibility.bind(base));
    const port: TeamControlPlanePort = {
      ...base,
      getCapabilities: async () => ({
        ...report,
        scopes: report.scopes.map((access) => access.scope === "organization" ? organization : access),
      }),
      getAggregate: async (request) => request.scope === "organization"
        ? { ...teamSnapshot, request, scope: "organization", cohort_label: organization.cohort_label }
        : base.getAggregate(request),
      getMemberVisibility,
    };
    renderPage({ port });
    fireEvent.click(await screen.findByRole("button", { name: "Reveal individual members" }));
    expect(await screen.findByText("Member 01", {}, { timeout: 5_000 })).toBeVisible();
    expect(getMemberVisibility).toHaveBeenCalledTimes(1);

    const scopes = screen.getByRole("group", { name: "Analytics scope" });
    fireEvent.click(within(scopes).getByRole("button", { name: /^Organization/ }));
    // The new scope/cohort props synchronously invalidate the bound team page;
    // this does not rely on the cleanup effect running after the commit.
    expect(screen.queryByText("Member 01")).toBeNull();
    expect(screen.getByRole("button", { name: "Reveal individual members" })).toBeDisabled();
    expect(getMemberVisibility).toHaveBeenCalledTimes(1);
  });

  it("synchronously gates capabilities and aggregates when the port identity changes", async () => {
    const first = createSyntheticTeamControlPlanePort();
    const second = createUnavailableTeamControlPlanePort(() => "2040-02-01T00:00:00Z");
    const view = render(
      <TeamAnalyticsPage
        navigate={() => undefined}
        port={first}
        runtimeMode="synthetic_demo"
        serviceState="available"
      />,
    );
    expect(await screen.findByText(/Synthetic platform guild/)).toBeVisible();
    expect(await screen.findByRole("table")).toBeVisible();

    view.rerender(
      <TeamAnalyticsPage
        navigate={() => undefined}
        port={second}
        runtimeMode="local_real"
        serviceState="available"
      />,
    );
    // These assertions run synchronously, before the reset effect resolves.
    expect(screen.queryByText(/Synthetic platform guild/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("rejects a synthetic capability payload returned by a declared local-loopback port", async () => {
    const synthetic = createSyntheticTeamControlPlanePort();
    const maliciousLocalPort: TeamControlPlanePort = {
      ...synthetic,
      origin: "local_loopback",
    };
    renderPage({ port: maliciousLocalPort, runtimeMode: "local_real" });
    expect(await screen.findByText(/Scope permissions could not be read from the port/)).toBeVisible();
    expect(screen.queryByRole("group", { name: "Analytics scope" })).toBeNull();
  });

  it("rejects a same-stamp capability report with duplicated scopes before it enters UI state", async () => {
    const base = createSyntheticTeamControlPlanePort();
    const report = await base.getCapabilities();
    const malformed: TeamControlPlanePort = {
      ...base,
      getCapabilities: async () => ({
        ...report,
        scopes: [report.scopes[0], report.scopes[1], report.scopes[1]],
      }),
    };
    renderPage({ port: malformed });
    expect(await screen.findByText(/Scope permissions could not be read from the port/)).toBeVisible();
    expect(screen.queryByRole("group", { name: "Analytics scope" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("rejects a well-formed cached capability report issued to another opaque principal", async () => {
    const active = createSyntheticTeamControlPlanePort();
    const otherPrincipal = createSyntheticTeamControlPlanePort({ principalId: "8c".repeat(32) });
    const crossPrincipal: TeamControlPlanePort = {
      ...active,
      getCapabilities: (signal) => otherPrincipal.getCapabilities(signal),
    };
    renderPage({ port: crossPrincipal });
    expect(await screen.findByText(/Scope permissions could not be read from the port/)).toBeVisible();
    expect(screen.queryByRole("group", { name: "Analytics scope" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("rejects a synthetic aggregate payload even after a matching local capability report", async () => {
    const synthetic = createSyntheticTeamControlPlanePort();
    const report = await synthetic.getCapabilities();
    const localStampedPort: TeamControlPlanePort = {
      ...synthetic,
      origin: "local_loopback",
      getCapabilities: async () => ({ ...report, origin: "local_loopback" }),
    };
    renderPage({ port: localStampedPort, runtimeMode: "local_real" });
    expect(await screen.findByText(/The aggregate could not be loaded from the port/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("keeps suppressed, withheld, N/A, and abstained guidance distinct and state-authoritative", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    fireEvent.focus(within(within(table).getByRole("row", { name: /Problem evidence quality/ })).getByRole("button"));
    let card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card).toHaveAttribute("data-state", "suppressed");
    expect(card).toHaveAttribute("data-suppression-reason", "overlap_or_differencing");
    expect(card.textContent).toMatch(/minimum was met.*overlap or differencing/);
    expect(card.textContent).toContain("Evidence authority");

    fireEvent.focus(within(within(table).getByRole("row", { name: /Deliverable contract/ })).getByRole("button"));
    card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card).toHaveAttribute("data-state", "withheld");
    expect(card).toHaveAttribute("data-comparability", "mixed_definition_versions");
    expect(card.textContent).toMatch(/Do not compare or combine/);

    fireEvent.click(screen.getByRole("button", { name: /Collaboration flow lens/ }));
    const collaboration = screen.getByRole("table");
    fireEvent.focus(within(within(collaboration).getByRole("row", { name: /Exploration-to-plan conversion/ })).getByRole("button"));
    card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card).toHaveAttribute("data-state", "not_applicable");
    expect(card.textContent).toMatch(/No action for this window:/);

    fireEvent.focus(within(within(collaboration).getByRole("row", { name: /Scope-change acknowledgement/ })).getByRole("button"));
    card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card).toHaveAttribute("data-state", "abstained");
    expect(card.textContent).toMatch(/abstained instead of guessing/);
  });

  it("rejects a same-scope aggregate returned for a different cohort identity", async () => {
    const base = createSyntheticTeamControlPlanePort();
    const report = await base.getCapabilities();
    const request = teamAggregateRequestForAccess(report.scopes.find((access) => access.scope === "team")!)!;
    const snapshot = await base.getAggregate(request);
    const crossCohort: TeamControlPlanePort = {
      ...base,
      getAggregate: async () => ({
        ...snapshot,
        request: { ...snapshot.request, cohort_id: "fa".repeat(32) },
      }),
    };
    renderPage({ port: crossCohort });
    expect(await screen.findByText(/The aggregate could not be loaded from the port/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
