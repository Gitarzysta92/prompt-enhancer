import { expect, test, type Locator, type Page } from "@playwright/test";

type StandaloneRoute = {
  heading: string;
  navName: string;
  path: string;
  routeTitle: string;
  stateText?: string;
};

const ROUTES: readonly StandaloneRoute[] = [
  {
    heading: "Overview",
    navName: "Overview",
    path: "/overview",
    routeTitle: "Overview",
  },
  {
    heading: "Sessions",
    navName: "Sessions",
    path: "/sessions",
    routeTitle: "Sessions",
  },
  {
    heading: "Rate sessions",
    navName: "Calibration",
    path: "/calibration",
    routeTitle: "Calibration",
  },
  {
    heading: "Models",
    navName: "Models",
    path: "/models",
    routeTitle: "Models",
    stateText: "Local models are not available in this runtime.",
  },
  {
    heading: "Agent workspace",
    navName: "Agent",
    path: "/agent",
    routeTitle: "Agent",
    stateText: "The local agent is not available in this runtime.",
  },
  {
    heading: "Check a prompt",
    navName: "Prompt check",
    path: "/prompt-checks",
    routeTitle: "Prompt check",
    stateText: "Prompt checks are not available in this runtime.",
  },
];

// Local Sources is intentionally excluded: the synthetic runtime hides that
// navigation entry and exposes only a closed "disabled" boundary on direct GET.

test.use({ viewport: { width: 360, height: 800 } });

async function tabUntil(page: Page, target: Locator, maximumTabs: number): Promise<void> {
  for (let index = 0; index < maximumTabs; index += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => document.activeElement === element)) return;
  }
  throw new Error(`Target was not keyboard reachable within ${maximumTabs} Tab presses.`);
}

async function resetFocusToDocument(page: Page): Promise<void> {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await expect.poll(() => page.evaluate(() => document.activeElement === document.body)).toBe(true);
}

for (const route of ROUTES) {
  test(`${route.routeTitle} has a truthful standalone mobile boundary`, async ({ page }) => {
    await page.goto(route.path);

    const main = page.locator("#main-content");
    await expect(main).toBeVisible();
    await expect(page).toHaveTitle(`${route.routeTitle} · Prompt Enhancer`);
    await expect(page.locator(".topbar__trail strong")).toHaveText(route.routeTitle);
    await expect(page.locator('[aria-label*="Synthetic demo fixture ready"]:visible').first()).toBeVisible();
    const navigationDialog = await openMobileNavigation(page);
    await expect(navigationDialog.getByRole("button", { exact: true, name: route.navName })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await page.keyboard.press("Escape");
    await expect(navigationDialog).toHaveCount(0);

    await expect(main.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
    if (route.stateText) await expect(main.getByText(route.stateText, { exact: true })).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  });
}

test("mobile primary navigation remains keyboard-visible and usable", async ({ page }) => {
  await page.goto("/overview");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await resetFocusToDocument(page);
  await tabUntil(page, skipLink, 2);
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();

  const openNavigation = page.getByRole("button", { name: "Open navigation" });
  await tabUntil(page, openNavigation, 3);
  await expect(openNavigation).toBeFocused();
  await expect(openNavigation).toBeVisible();
  await page.keyboard.press("Enter");

  const navigationDialog = page.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
  await expect(navigationDialog).toBeVisible();
  const sessions = navigationDialog.getByRole("button", { exact: true, name: "Sessions" });
  await tabUntil(page, sessions, 5);
  await expect(sessions).toBeFocused();
  await expect(sessions).toBeVisible();
  await expect(sessions).toBeInViewport();
  const focusOutline = await sessions.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
  });
  expect(focusOutline.style).not.toBe("none");
  expect(focusOutline.width).toBeGreaterThan(0);

  await page.keyboard.press("Enter");
  await expect(navigationDialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/sessions$/);
  await expect(page.locator("#main-content").getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
  const reopened = await openMobileNavigation(page);
  await expect(reopened.getByRole("button", { exact: true, name: "Sessions" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.keyboard.press("Escape");
});

test("click and browser-history route changes update exact title and main focus", async ({ page }) => {
  await page.goto("/overview");
  const main = page.locator("#main-content");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page).toHaveTitle("Overview · Prompt Enhancer");
  await expect(main).not.toBeFocused();

  const navigationDialog = await openMobileNavigation(page);
  await navigationDialog.getByRole("button", { exact: true, name: "Sessions" }).click();
  await expect(page).toHaveURL(/\/sessions$/);
  await expect(page).toHaveTitle("Sessions · Prompt Enhancer");
  await expect(main.getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
  await expect(main).toBeFocused();

  const historyDialog = await openMobileNavigation(page);
  await expect(historyDialog.getByRole("button", { exact: true, name: "Sessions" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.goBack();

  await expect(historyDialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page).toHaveTitle("Overview · Prompt Enhancer");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(main).toBeFocused();
});

async function openMobileNavigation(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Open navigation" }).click();
  const dialog = page.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
  await expect(dialog).toBeVisible();
  return dialog;
}
