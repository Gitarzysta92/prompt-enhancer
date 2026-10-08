import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TeamControlPlanePort } from "../../shared/api/teamControlPlane";
import { createLocalLoopbackTeamControlPlanePort } from "../../shared/api/teamControlPlaneUnavailable";
import { createSyntheticTeamControlPlanePort } from "../../shared/api/teamControlPlaneSynthetic";
import { TeamContextDrawer } from "./TeamContextDrawer";

function toggle() {
  const details = document.querySelector("details.team-context-drawer") as HTMLDetailsElement;
  details.open = !details.open;
  fireEvent(details, new Event("toggle", { bubbles: false }));
}

describe("TeamContextDrawer", () => {
  it("states plainly that team context is unavailable without a port", () => {
    render(<TeamContextDrawer lensId="task-framing" port={null} />);
    const details = document.querySelector("details.team-context-drawer")!;
    expect(details).toHaveAttribute("data-team-access", "unavailable");
    expect(details.textContent).toContain("Team context");
    expect(details.textContent).toContain("Unavailable · local-only overlay");
    expect(document.querySelector(".team-context-drawer__body")).toBeNull();
    toggle();
    expect(screen.getByText(/runs without a team control plane/)).toBeInTheDocument();
    expect(document.querySelectorAll(".team-aggregate-list")).toHaveLength(0);
  });

  it("stays collapsed by default and shows the compact lens aggregate once opened", async () => {
    render(<TeamContextDrawer lensId="collaboration-flow" port={createSyntheticTeamControlPlanePort()} />);
    const details = document.querySelector("details.team-context-drawer")!;
    expect(details).not.toHaveAttribute("open");
    expect(await screen.findByText(/Synthetic platform guild/)).toBeInTheDocument();
    expect(document.querySelector(".team-aggregate-list")).toBeNull();
    toggle();
    const list = await screen.findByRole("list", { name: /Collaboration flow/ });
    const items = list.querySelectorAll("li");
    expect(items).toHaveLength(5);
    const rework = [...items].find((item) => item.textContent?.includes("Rework"))!;
    expect(rework).toHaveAttribute("data-status", "known");
    expect(rework.textContent).toContain("89% rq · raw 11%");
    const explore = [...items].find((item) => item.textContent?.includes("Explore"))!;
    expect(explore).toHaveAttribute("data-status", "not_applicable");
    expect(explore.querySelector(".team-interval__point")).toBeNull();
    expect(explore.querySelector(".team-interval__state")?.textContent).toBe("not applicable");
    const trigger = rework.querySelector("button")!;
    fireEvent.focus(trigger);
    const card = document.querySelector('[role="region"][data-metric-key]')!;
    expect(card.className).toContain("metric-explainer-card--compact");
    expect(card.textContent).toContain("Rework-candidate rate");
    expect(card.textContent).toContain("Measured · typed evidence");
    expect(document.querySelectorAll("polygon, polyline")).toHaveLength(0);
  });

  it("explains a denied team scope instead of hiding the drawer", async () => {
    render(<TeamContextDrawer lensId="task-framing" port={createSyntheticTeamControlPlanePort({ team: "denied" })} />);
    expect(await screen.findByText("Not permitted for this role")).toBeInTheDocument();
    toggle();
    expect(screen.getByText(/does not permit this scope/)).toBeInTheDocument();
  });

  it("shows exact loopback readiness blockers and never requests a team value", async () => {
    const port = createLocalLoopbackTeamControlPlanePort({
      getControlPlaneReadiness: async () => ({
        contract_version: "control-plane-v2",
        delivery_guarantee: "at_least_once_with_monotonic_ack",
        gaps: ["disclosure_control_unreviewed", "producer_pipeline_not_connected"],
        production_ready: false,
        profile: "development",
        remote_listening_enabled: false,
      }),
    }, () => "2040-03-01T12:00:00Z");
    const getAggregate = vi.spyOn(port, "getAggregate");

    render(<TeamContextDrawer lensId="task-framing" port={port} />);
    expect(await screen.findByText("Development boundary · 2 blockers")).toBeVisible();
    toggle();
    expect(screen.getByText(/Development boundary reachable/)).toBeVisible();
    fireEvent.click(screen.getByText("2 exact backend blockers"));
    expect(screen.getByText("disclosure_control_unreviewed")).toBeVisible();
    expect(screen.getByText("producer_pipeline_not_connected")).toBeVisible();
    expect(document.querySelector(".team-aggregate-list")).toBeNull();
    expect(getAggregate).not.toHaveBeenCalled();
  });

  it("clears capability and aggregate state when the port identity changes", async () => {
    const first = createSyntheticTeamControlPlanePort();
    const view = render(<TeamContextDrawer lensId="task-framing" port={first} />);
    expect(await screen.findByText(/Synthetic platform guild/)).toBeInTheDocument();
    toggle();
    expect(await screen.findByRole("list", { name: /Task framing/ })).toBeVisible();

    view.rerender(<TeamContextDrawer lensId="task-framing" port={null} />);
    expect(screen.getByText("Unavailable · local-only overlay")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /Task framing/ })).toBeNull();
    expect(screen.getByText(/runs without a team control plane/)).toBeInTheDocument();
  });

  it("rejects a response whose origin does not match the declared port", async () => {
    const synthetic = createSyntheticTeamControlPlanePort();
    const maliciousLocalPort: TeamControlPlanePort = { ...synthetic, origin: "local_loopback" };
    render(<TeamContextDrawer lensId="task-framing" port={maliciousLocalPort} />);
    expect(await screen.findByText("Permissions unavailable")).toBeVisible();
    toggle();
    expect(screen.getByRole("alert")).toHaveTextContent(/permissions could not be read/i);
    expect(screen.queryByRole("list", { name: /Task framing/ })).toBeNull();
  });

  it("rejects malformed same-stamp readiness and never loads an aggregate", async () => {
    const base = createSyntheticTeamControlPlanePort();
    const report = await base.getCapabilities();
    const getAggregate = vi.fn(base.getAggregate.bind(base));
    const malformed: TeamControlPlanePort = {
      ...base,
      getCapabilities: async () => ({
        ...report,
        readiness: [report.readiness[0], report.readiness[0], report.readiness[2], report.readiness[3]],
      }),
      getAggregate,
    };
    render(<TeamContextDrawer lensId="task-framing" port={malformed} />);
    expect(await screen.findByText("Permissions unavailable")).toBeVisible();
    toggle();
    expect(screen.getByRole("alert")).toHaveTextContent(/permissions could not be read/i);
    expect(getAggregate).not.toHaveBeenCalled();
  });
});
