import { expect, test, type Page } from "@playwright/test";

/** Visible text nodes below the requested floor and horizontal overflow, scoped to one root. */
async function layoutAudit(page: Page, rootSelector: string, minimumFontSize: number) {
  return page.evaluate(({ selector, minimum }) => {
    const root = document.querySelector<HTMLElement>(selector);
    if (root === null) throw new Error(`synthetic root ${selector} missing`);
    const textSelectors = "small,span,p,strong,button,select,dt,dd,b,td,th,li,summary,h1,h2,h3,h4";
    const tooSmall = [...root.querySelectorAll<HTMLElement>(textSelectors)]
      .filter((element) => {
        const style = getComputedStyle(element);
        return style.display !== "none"
          && style.visibility !== "hidden"
          && element.getClientRects().length > 0
          && Number.parseFloat(style.fontSize) < minimum;
      })
      .map((element) => `${element.tagName.toLowerCase()}.${element.className}`);
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      tooSmall,
    };
  }, { selector: rootSelector, minimum: minimumFontSize });
}

async function installClsObserver(page: Page) {
  await page.addInitScript(() => {
    const state = { value: 0 };
    const observer = new PerformanceObserver((list) => {
      for (const rawEntry of list.getEntries()) {
        const entry = rawEntry as PerformanceEntry & { hadRecentInput: boolean; value: number };
        if (!entry.hadRecentInput) state.value += entry.value;
      }
    });
    observer.observe({ type: "layout-shift", buffered: true });
    Object.assign(window, { __syntheticClsState: state, __syntheticClsObserver: observer });
  });
}

async function currentCls(page: Page): Promise<number> {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  return page.evaluate(() => (window as typeof window & { __syntheticClsState: { value: number } }).__syntheticClsState.value);
}

test.describe("team analytics scopes", () => {
  test("renders permission-aware scopes, honest readiness, and an aggregate-only table", async ({ page }) => {
    await installClsObserver(page);
    await page.goto("/team");
    await expect(page.getByRole("heading", { name: "Team analytics" })).toBeVisible();
    const scopes = page.getByRole("group", { name: "Analytics scope" });
    await expect(scopes.getByRole("button", { name: /^Team/ })).toHaveAttribute("aria-pressed", "true");
    await expect(scopes.getByRole("button", { name: /^Organization/ })).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByRole("list", { name: "Scopes not available" })).toContainText("Organization");

    const readiness = page.getByRole("list", { name: "Capability readiness" });
    await expect(readiness.locator("[data-card='team_sync']")).toHaveAttribute("data-state", "unavailable");
    await expect(readiness.locator("[data-card='billing']")).toHaveAttribute("data-state", "unavailable");
    await expect(readiness.locator("[data-card='billing']")).toContainText("Nothing is metered or charged");
    await expect(readiness.locator("[data-card='local']")).toContainText("Fictional in-memory fixtures");

    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    await expect(table.getByRole("columnheader")).toHaveText(["Metric", "Value & uncertainty", "Cohort", "Missingness", "Comparability", "Freshness"]);
    const suppressed = table.getByRole("row", { name: /Constraint precision/ });
    await expect(suppressed).toHaveAttribute("data-status", "suppressed");
    await expect(suppressed.locator(".team-interval__point")).toHaveCount(0);
    await expect(suppressed.locator(".team-interval__state")).toHaveText("suppressed · small contributing cohort");
    await expect(page.locator("polygon, polyline")).toHaveCount(0);

    const memberSlot = page.getByLabel("Reserved member visibility region");
    await expect(memberSlot).toHaveAttribute("data-member-panel", "active");
    const teamSlotHeight = await memberSlot.evaluate((element) => element.getBoundingClientRect().height);
    await memberSlot.evaluate((element) => { element.setAttribute("data-e2e-stable-node", "true"); });
    await scopes.getByRole("button", { name: /^Me/ }).click();
    await expect(memberSlot).toHaveAttribute("data-member-panel", "reserved");
    await expect(memberSlot).toHaveAttribute("data-e2e-stable-node", "true");
    expect(await memberSlot.evaluate((element) => element.getBoundingClientRect().height)).toBe(teamSlotHeight);
    await scopes.getByRole("button", { name: /^Team/ }).click();
    await expect(memberSlot).toHaveAttribute("data-member-panel", "active");
    expect(await memberSlot.evaluate((element) => element.getBoundingClientRect().height)).toBe(teamSlotHeight);

    const currentTable = page.getByRole("table");
    const trigger = currentTable.getByRole("button", { name: /Task definition coverage/ });
    await trigger.focus();
    const card = page.locator(".metric-explainer-card, .metric-knowledge-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Meaning");
    await expect(card).toContainText("Next action");
    await expect(card).toContainText("Measured · typed evidence");
    expect((await layoutAudit(page, ".metric-explainer-card", 14)).tooSmall).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.locator(".metric-explainer-card, .metric-knowledge-card")).toHaveCount(0);

    await page.getByRole("button", { name: "Reveal individual members" }).click();
    await expect(page.getByText("Member 01")).toBeVisible();
    await expect(page.getByText("Member 05")).toHaveCount(0);
    await expect(page.getByText(/withheld consent and is not listed/)).toBeVisible();

    const layout = await layoutAudit(page, ".team-analytics", 14);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
    expect(await currentCls(page)).toBeLessThan(0.02);
  });

  test("keeps scope buttons focus-visible in forced-colors and reduced-motion modes", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await page.goto("/team");
    const organization = page.getByRole("group", { name: "Analytics scope" }).getByRole("button", { name: /^Organization/ });
    await organization.focus();
    await expect(organization).toBeFocused();
    const styles = await organization.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, transitionDuration: style.transitionDuration };
    });
    expect(styles.outlineStyle).not.toBe("none");
    expect(Number.parseFloat(styles.outlineWidth)).toBeGreaterThanOrEqual(3);
    expect(styles.transitionDuration).toMatch(/^(0s|0ms)$/);
  });
});

test.describe("task flow", () => {
  test("separates proposal, review, revision, and analysis facts", async ({ page }) => {
    await page.goto("/tasks/flow");
    await expect(page.getByRole("heading", { name: "Task flow" })).toBeVisible();
    const board = page.getByRole("group", { name: "Task flow board" });
    await expect(board.getByRole("region", { name: "Proposed groupings" }).getByRole("article")).toHaveCount(2);
    await expect(board.getByRole("region", { name: "In progress" }).getByRole("article")).toHaveCount(1);
    await expect(board.getByRole("region", { name: "Work state unknown" }).getByRole("article")).toHaveCount(0);
    await expect(board.getByRole("region", { name: "Backlog" }).getByRole("article")).toHaveCount(0);
    await expect(board.getByRole("region", { name: "Done" }).getByRole("article")).toHaveCount(0);
    await expect(board.getByRole("region", { name: "Accepted · merged · split" }).getByRole("article")).toHaveCount(1);
    await expect(board.getByRole("region", { name: "Rejected proposals" }).getByRole("article")).toHaveCount(0);
    await expect(board.getByRole("region", { name: "Decided · action unknown" }).getByRole("article")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Proposal & explicit review records" }).getByRole("button")).toHaveCount(3);
    await expect(page.getByRole("region", { name: "Confirmed revision records" }).getByRole("button")).toHaveCount(1);
    await expect(page.getByRole("region", { name: "Analysis events (not task lifecycle)" }).getByRole("button")).toHaveCount(2);
    await expect(page.getByRole("region", { name: "Task flow compact summary" })).toContainText("In progress1");
    await expect(page.getByRole("region", { name: "Task flow compact summary" })).toContainText("Explicit local receipts only");
    await expect(page.getByRole("region", { name: "Task flow compact summary" })).toContainText("0 team-sourced records · 0 remote-synced records");
    await page.getByRole("combobox", { name: "Kind" }).selectOption("confirmed");
    await expect(board.getByRole("region", { name: "Proposed groupings" }).getByRole("article")).toHaveCount(0);
    const layout = await layoutAudit(page, ".task-flow", 14);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
  });

  test("keeps the compact truth summary visible and the large board collapsed at 360px", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("/tasks/flow");
    const summary = page.getByRole("region", { name: "Task flow compact summary" });
    await expect(summary).toBeVisible();
    await expect(summary).toContainText("In progress1");
    await expect(summary).toContainText("analysis cannot move work columns");
    const boardDisclosure = page.locator("details.task-flow__board-disclosure");
    await expect(boardDisclosure).not.toHaveAttribute("open", "");
    const layout = await layoutAudit(page, ".task-flow", 14);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
  });

  test("keeps task chronology controls focus-visible in forced colors with no motion", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await page.goto("/tasks/flow");
    const marker = page.getByRole("region", { name: "Confirmed revision records" }).getByRole("button").first();
    await marker.focus();
    const styles = await marker.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, transitionDuration: style.transitionDuration };
    });
    expect(styles.outlineStyle).not.toBe("none");
    expect(Number.parseFloat(styles.outlineWidth)).toBeGreaterThanOrEqual(3);
    expect(styles.transitionDuration).toMatch(/^(0s|0ms)$/);
  });
});

for (const viewport of [
  { width: 360, height: 500 },
  { width: 420, height: 620 },
]) {
  test(`keeps the current V2 overlay readable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/overlay/model-ensemble");
    await expect(page.getByRole("heading", { name: "Live metric watch" })).toBeVisible();
    await expect(page.locator(".model-ensemble-overlay__connection")).toHaveText("No active watch");
    await expect(page.getByRole("region", { name: "Live watch scope" })).toBeVisible();
    const drawer = page.locator("details.team-context-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).not.toHaveAttribute("open", "");
    await expect(drawer.locator("summary")).toContainText("Team context");
    await expect(drawer.locator("summary")).toContainText("Synthetic platform guild");
    await drawer.locator("summary").click();
    const list = drawer.getByRole("list", { name: /Task framing/ });
    await expect(list).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(6);
    await expect(list.locator("li[data-status='suppressed'] .team-interval__point")).toHaveCount(0);
    await list.getByRole("button", { name: /^Task/ }).first().focus();
    const card = page.locator(".metric-explainer-card, .metric-knowledge-card");
    await expect(card).toBeVisible();
    await expect(card).toHaveClass(/metric-explainer-card--compact/);
    expect((await layoutAudit(page, ".metric-explainer-card", 12)).tooSmall).toEqual([]);
    await page.keyboard.press("Escape");

    const layout = await layoutAudit(page, ".model-ensemble-overlay", 12);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
  });
}

test("keeps global navigation text at 12px on a 360px viewport", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 720 });
  await page.goto("/team");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("navigation", { name: "Mobile primary" })).toBeVisible();
  expect((await layoutAudit(page, ".primary-nav--drawer", 12)).tooSmall).toEqual([]);
});
