import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  MemberVisibilityGrant,
  ScopeAccess,
  TeamControlPlanePort,
  TeamMemberVisibilityRequest,
  TeamMemberVisibilityPage,
} from "../../shared/api/teamControlPlane";
import { createSyntheticTeamControlPlanePort } from "../../shared/api/teamControlPlaneSynthetic";
import {
  MemberVisibilityPanel,
  memberVisibilityGrantIdentity,
  memberVisibilityGrantIsUsable,
  memberVisibilityPageIsValid,
} from "./MemberVisibilityPanel";

async function fixtureGrantAndPage() {
  const base = createSyntheticTeamControlPlanePort();
  const report = await base.getCapabilities();
  const access = report.scopes.find((candidate) => candidate.scope === "team")!;
  const request: TeamMemberVisibilityRequest = {
    principal_id: report.principal_id,
    scope: "team",
    cohort_id: access.cohort_id!,
    team_id: access.team_id,
    organization_id: access.organization_id,
    grant_id: report.member_visibility.grant_id!,
  };
  const page = await base.getMemberVisibility(request);
  return { access, base, grant: report.member_visibility, page, request };
}

function portReturning(
  base: TeamControlPlanePort,
  page: unknown,
): TeamControlPlanePort {
  return { ...base, getMemberVisibility: async () => structuredClone(page) as TeamMemberVisibilityPage };
}

function panel(
  grant: MemberVisibilityGrant,
  port: TeamControlPlanePort,
  access: ScopeAccess,
) {
  return <MemberVisibilityPanel grant={grant} lensId="task-framing" port={port} scope="team" scopeAccess={access} />;
}

describe("MemberVisibilityPanel authorization", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("requires the exact consent reason, durable audit destination, and an unexpired grant", async () => {
    const { base, grant, request } = await fixtureGrantAndPage();
    const referenceNow = Date.parse(grant.audit.granted_at!) + 1;
    expect(memberVisibilityGrantIsUsable(grant, request, base.principalId, referenceNow)).toBe(true);
    const variants: MemberVisibilityGrant[] = [
      { ...grant, reason: "permission_not_granted" },
      { ...grant, audit: { ...grant.audit, access_logged: false } },
      { ...grant, audit: { ...grant.audit, log_destination: null } },
      { ...grant, audit: { ...grant.audit, log_destination: "invalid" as MemberVisibilityGrant["audit"]["log_destination"] } },
      { ...grant, audit: { ...grant.audit, granted_by_role: null } },
      { ...grant, audit: { ...grant.audit, granted_by_role: "   " } },
      { ...grant, audit: { ...grant.audit, granted_at: null } },
      { ...grant, audit: { ...grant.audit, granted_at: "not-a-timestamp" } },
      { ...grant, audit: { ...grant.audit, granted_at: new Date(referenceNow + 1_000).toISOString() } },
      { ...grant, audit: { ...grant.audit, expires_at: new Date(referenceNow - 1).toISOString() } },
      { ...grant, audit: { ...grant.audit, expires_at: null } },
      { ...grant, grant_id: "9f".repeat(32) },
      { ...grant, principal_id: "9e".repeat(32) },
    ];
    for (const candidate of variants) {
      expect(memberVisibilityGrantIsUsable(candidate, request, base.principalId, referenceNow)).toBe(false);
    }
  });

  it.each(["grant mismatch", "grant id mismatch", "request mismatch", "principal mismatch", "response principal mismatch", "withheld row", "port stamp mismatch"] as const)(
    "rejects the whole returned page for a %s and clears previously revealed rows",
    async (failure) => {
      const { access, base, grant, page } = await fixtureGrantAndPage();
      const view = render(panel(grant, base, access));
      fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
      expect(await screen.findByText("Member 01")).toBeVisible();

      const invalidPage: TeamMemberVisibilityPage = failure === "grant mismatch"
        ? { ...page, grant: { ...page.grant, audit: { ...page.grant.audit, expires_at: "2040-02-16T08:00:00Z" } } }
        : failure === "grant id mismatch"
          ? { ...page, grant: { ...page.grant, grant_id: "8f".repeat(32) } }
          : failure === "request mismatch"
            ? { ...page, request: { ...page.request, cohort_id: "9a".repeat(32) } }
          : failure === "principal mismatch"
            ? { ...page, request: { ...page.request, principal_id: "9d".repeat(32) } }
          : failure === "response principal mismatch"
            ? { ...page, principal_id: "9c".repeat(32) }
        : failure === "port stamp mismatch"
          ? { ...page, origin: "local_loopback" }
          : {
          ...page,
          members: [
            ...page.members,
            { ...page.members[0], member_id: "f6".repeat(32), display_handle: "Member 06", consent: "withheld" },
          ],
        };
      view.rerender(
        <MemberVisibilityPanel
          grant={grant}
          lensId="task-framing"
          port={portReturning(base, invalidPage)}
          scope="team"
          scopeAccess={access}
        />,
      );
      expect(screen.queryByText("Member 01")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/returned page did not match the exact active, audited consent grant/);
      expect(screen.queryByText("Member 01")).toBeNull();
      expect(screen.queryByText("Member 06")).toBeNull();
    },
  );

  it("synchronously gates a loaded page when the exact grant changes on the same port", async () => {
    const { access, base, grant } = await fixtureGrantAndPage();
    const view = render(panel(grant, base, access));
    fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
    expect(await screen.findByText("Member 01")).toBeVisible();
    const replacement = {
      ...grant,
      audit: { ...grant.audit, expires_at: "2040-02-14T08:00:00Z" },
    };
    expect(memberVisibilityGrantIdentity(replacement)).not.toBe(memberVisibilityGrantIdentity(grant));
    view.rerender(panel(replacement, base, access));
    // This assertion runs before any async effect can clear component state.
    expect(screen.queryByText("Member 01")).toBeNull();
    expect(screen.getByRole("button", { name: "Reveal individual members" })).toHaveAttribute("aria-expanded", "false");
  });

  it("rejects a structurally valid grant whose start instant is still in the future", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2040-01-31T09:00:00Z"));
    const { access, base, grant } = await fixtureGrantAndPage();
    const futureGrant: MemberVisibilityGrant = {
      ...grant,
      audit: {
        ...grant.audit,
        granted_at: "2040-02-01T09:00:00Z",
        expires_at: "2040-02-15T09:00:00Z",
      },
    };
    render(panel(futureGrant, base, access));
    expect(screen.getByRole("button", { name: "Reveal individual members" })).toBeDisabled();
    expect(screen.queryByText("Member 01")).toBeNull();
  });

  it("synchronously rejects a cached grant and page after the opaque principal changes", async () => {
    const { access, base, grant } = await fixtureGrantAndPage();
    const view = render(panel(grant, base, access));
    fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
    expect(await screen.findByText("Member 01")).toBeVisible();
    const nextPrincipal = "9c".repeat(32);
    view.rerender(panel(
      { ...grant, principal_id: nextPrincipal },
      base,
      { ...access, principal_id: nextPrincipal },
    ));
    expect(screen.queryByText("Member 01")).toBeNull();
    expect(screen.getByRole("button", { name: "Reveal individual members" })).toBeDisabled();
  });

  it("closes and clears revealed rows exactly when the grant expires", async () => {
    vi.useFakeTimers();
    const startsAt = new Date("2039-12-31T23:59:59.000Z");
    vi.setSystemTime(startsAt);
    const { access, base, grant, page } = await fixtureGrantAndPage();
    const expiringGrant: MemberVisibilityGrant = {
      ...grant,
      audit: {
        ...grant.audit,
        granted_at: "2039-12-15T08:00:00.000Z",
        expires_at: "2040-01-01T00:00:00.000Z",
      },
    };
    const expiringPage = { ...page, grant: expiringGrant };
    render(
      <MemberVisibilityPanel
        grant={expiringGrant}
        lensId="task-framing"
        port={portReturning(base, expiringPage)}
        scope="team"
        scopeAccess={access}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Member 01")).toBeVisible();

    act(() => { vi.advanceTimersByTime(999); });
    expect(screen.getByText("Member 01")).toBeVisible();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByText("Member 01")).toBeNull();
    expect(screen.getByRole("button", { name: "Reveal individual members" })).toBeDisabled();
    expect(screen.getByText(/grant lacks the exact active scope\/cohort binding, consent, audit logging, grant id, or an unexpired expiry/)).toBeVisible();
  });

  it("uses an injective canonical grant identity when string fields contain delimiters", async () => {
    const { grant } = await fixtureGrantAndPage();
    const left = { ...grant, audit: { ...grant.audit, granted_by_role: "fixture|role", granted_at: "stamp" } };
    const right = { ...grant, audit: { ...grant.audit, granted_by_role: "fixture", granted_at: "role|stamp" } };
    expect(memberVisibilityGrantIdentity(left)).not.toBe(memberVisibilityGrantIdentity(right));
  });

  it.each(["unsorted", "duplicate id", "duplicate handle", "invalid pseudonym", "ordering claim"] as const)(
    "rejects member rows with invalid runtime %s",
    async (failure) => {
      const { access, base, grant, page } = await fixtureGrantAndPage();
      const members = structuredClone(page.members);
      const invalidPage: TeamMemberVisibilityPage = failure === "unsorted"
        ? { ...page, members: [members[1], members[0], ...members.slice(2)] }
        : failure === "duplicate id"
          ? { ...page, members: [members[0], { ...members[1], member_id: members[0].member_id }] }
          : failure === "duplicate handle"
            ? { ...page, members: [members[0], { ...members[1], display_handle: members[0].display_handle }] }
            : failure === "invalid pseudonym"
              ? { ...page, members: [{ ...members[0], member_id: "not-a-pseudonym" }] }
              : { ...page, ordering: "ranked_by_value" as TeamMemberVisibilityPage["ordering"] };
      render(panel(grant, portReturning(base, invalidPage), access));
      fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/returned page did not match/);
      expect(screen.queryByText("Member 01")).toBeNull();
    },
  );

  it.each([
    "negative withheld count",
    "metrics is not an array",
    "duplicate metric",
    "unknown metric",
    "unreviewed version",
    "invalid state",
    "invalid provenance",
    "invalid timestamp",
    "out-of-bounds value",
    "incoherent fraction",
    "state carries a value",
    "missing page",
  ] as const)("rejects a malformed member-page payload without crashing: %s", async (failure) => {
    const { access, base, grant, page, request } = await fixtureGrantAndPage();
    const malformed = structuredClone(page) as TeamMemberVisibilityPage;
    const member = malformed.members[0];
    const metric = member.metrics[0];
    let payload: unknown = malformed;
    if (failure === "negative withheld count") {
      malformed.withheld_member_count = -1;
    } else if (failure === "metrics is not an array") {
      (member as unknown as { metrics: unknown }).metrics = null;
    } else if (failure === "duplicate metric") {
      (member.metrics as typeof metric[])[1] = structuredClone(metric);
    } else if (failure === "unknown metric") {
      metric.metric_key = "example.unreviewed_metric";
    } else if (failure === "unreviewed version") {
      metric.definition_version = 999;
    } else if (failure === "invalid state") {
      metric.value_state = "withheld" as typeof metric.value_state;
    } else if (failure === "invalid provenance") {
      metric.provenance = "experimental_model";
    } else if (failure === "invalid timestamp") {
      metric.newest_receipt_at = "not-a-timestamp";
    } else if (failure === "out-of-bounds value") {
      metric.numeric_value = 1.5;
    } else if (failure === "incoherent fraction") {
      metric.numeric_value = 0.123;
    } else if (failure === "state carries a value") {
      metric.value_state = "unknown";
    } else {
      payload = undefined;
    }
    expect(() => memberVisibilityPageIsValid(payload, grant, request, base)).not.toThrow();
    expect(memberVisibilityPageIsValid(payload, grant, request, base)).toBe(false);
    render(panel(grant, portReturning(base, payload), access));
    fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/returned page did not match/);
    expect(screen.queryByText("Member 01")).toBeNull();
  });

  it("never badges a column as measured while any member cell for it is missing or state-only", async () => {
    const { access, base, grant, page } = await fixtureGrantAndPage();
    const original = structuredClone(page.members);
    // Turn one member's first cell into a state-only unknown (no value) so that column is not fully measured.
    const droppedKey = original[0].metrics[0].metric_key;
    const members = [
      {
        ...original[0],
        metrics: [
          {
            ...original[0].metrics[0],
            value_state: "unknown",
            numeric_value: null,
            numerator: null,
            denominator: null,
            newest_receipt_at: null,
          } as typeof original[0]["metrics"][number],
          ...original[0].metrics.slice(1),
        ],
      },
      ...original.slice(1),
    ];
    render(panel(grant, portReturning(base, { ...page, members }), access));
    fireEvent.click(screen.getByRole("button", { name: "Reveal individual members" }));
    expect(await screen.findByText("Member 01")).toBeVisible();
    const stateOnlyCell = document.querySelector('td[data-state="unknown"]');
    expect(stateOnlyCell?.textContent).toBe("Unknown");
    const headers = screen.getAllByRole("columnheader").slice(1);
    for (const header of headers) {
      const trigger = header.querySelector("button")!;
      fireEvent.pointerEnter(trigger);
      const card = document.querySelector(".metric-explainer-card")!;
      const columnKey = card.getAttribute("data-metric-key");
      const known = members.every((member) => member.metrics.find((cell) => cell.metric_key === columnKey)?.value_state === "known");
      expect(card.getAttribute("data-provenance"), columnKey ?? "").toBe(known ? "measured" : "not_measured");
      if (columnKey === droppedKey) {
        expect(card.textContent).toContain("Not measured · state only");
        expect(card.textContent).not.toContain("Measured · typed evidence");
        expect(card.textContent).toMatch(/1 state-only or missing/);
      }
      // A later pointer-enter replaces the preview target; no timer needed.
    }
    expect(document.querySelectorAll('[role="tooltip"]')).toHaveLength(0);
  });
});
