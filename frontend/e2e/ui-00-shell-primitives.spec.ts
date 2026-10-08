import { expect, test, type Locator, type Page } from "@playwright/test";

type ViewportCase = {
  height: number;
  name: "desktop" | "mobile";
  width: number;
};

const VIEWPORTS: readonly ViewportCase[] = [
  { height: 800, name: "desktop", width: 1280 },
  { height: 800, name: "mobile", width: 360 },
];

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const widths = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
}

async function assertFocusVisible(locator: Locator): Promise<void> {
  await expect(locator).toBeFocused();
  const outline = await locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      style: style.outlineStyle,
      width: Number.parseFloat(style.outlineWidth),
    };
  });
  expect(outline.style).not.toBe("none");
  expect(outline.width).toBeGreaterThan(0);
}

async function assertSyntheticShell(page: Page): Promise<void> {
  await expect(page.locator('[aria-label*="Synthetic demo fixture ready"]:visible').first()).toBeVisible();
  await expect(page.locator(':text-is("Private by default"):visible').first()).toBeVisible();
}

async function openMobileNavigation(page: Page): Promise<Locator> {
  const open = page.getByRole("button", { name: "Open navigation" });
  await expect(open).toBeVisible();
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
  await expect(dialog).toBeVisible();
  return dialog;
}

for (const viewport of VIEWPORTS) {
  test(`${viewport.name} shell persists its theme without clipping or losing route truth`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/overview");

    await expect(page).toHaveTitle("Overview · Prompt Enhancer");
    await expect(page.locator("#main-content").getByRole("heading", {
      level: 1,
      name: "Overview",
    })).toBeVisible();
    await assertSyntheticShell(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
    await assertNoHorizontalOverflow(page);

    const skip = page.getByRole("link", { name: "Skip to main content" });
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Tab");
    await expect(skip).toBeVisible();
    await assertFocusVisible(skip);

    if (viewport.name === "desktop") {
      await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden();
      const navigation = page.getByRole("navigation", { name: "Primary" });
      await expect(navigation).toBeVisible();
      await expect(navigation.getByRole("button", { exact: true, name: "Overview" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    } else {
      const dialog = await openMobileNavigation(page);
      await expect(dialog.getByRole("button", { exact: true, name: "Overview" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    }

    const themeToggle = page.getByRole("button", { name: "Switch to light mode" });
    await expect(themeToggle).toBeVisible();
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
    await assertNoHorizontalOverflow(page);

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.getByRole("button", { name: "Switch to dark mode" })).toBeVisible();
    await assertSyntheticShell(page);
    await assertNoHorizontalOverflow(page);
  });
}

test("desktop navigation is grouped, vertical, scrollable, and keyboard reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/overview");
  await assertSyntheticShell(page);

  const navigation = page.getByRole("navigation", { name: "Primary" });
  const groups = navigation.getByRole("group");
  expect(await groups.count()).toBe(3);

  const buttons = navigation.getByRole("button");
  expect(await buttons.count()).toBe(9);
  const firstRect = await buttons.nth(0).boundingBox();
  const secondRect = await buttons.nth(1).boundingBox();
  expect(firstRect).not.toBeNull();
  expect(secondRect).not.toBeNull();
  expect(Math.abs(secondRect!.x - firstRect!.x)).toBeLessThanOrEqual(2);
  expect(secondRect!.y).toBeGreaterThan(firstRect!.y);

  const scroll = await navigation.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      clientHeight: element.clientHeight,
      overflowY: style.overflowY,
      scrollHeight: element.scrollHeight,
    };
  });
  expect(["auto", "scroll"]).toContain(scroll.overflowY);
  expect(scroll.scrollHeight).toBeGreaterThan(scroll.clientHeight);

  const last = buttons.last();
  await last.focus();
  await expect(last).toBeInViewport();
  await assertFocusVisible(last);
  expect(await navigation.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
});

test("desktop navigation reveals a deep current route on direct load", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/research/methods");
  await assertSyntheticShell(page);

  const navigation = page.getByRole("navigation", { name: "Primary" });
  const current = navigation.getByRole("button", { exact: true, name: "Methods & models" });
  await expect(current).toHaveAttribute("aria-current", "page");
  await expect(current).toBeInViewport();
  expect(await navigation.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
});

test("Labs disclosure follows the active route and preserves focus across responsive navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/overview");

  const desktopNavigation = page.getByRole("navigation", { name: "Primary" });
  const labs = desktopNavigation.locator("details").first();
  const labsSummary = labs.locator("summary");
  await expect(labsSummary).toBeVisible();
  await expect(labs).not.toHaveAttribute("open", "");
  await expect(labs.getByRole("button", { exact: true, name: "Methods & models" })).toBeHidden();

  await labsSummary.click();
  await expect(labs).toHaveAttribute("open", "");
  await labs.getByRole("button", { exact: true, name: "Methods & models" }).click();
  await expect(page).toHaveURL(/\/research\/methods$/);
  await expect(desktopNavigation.getByRole("button", { exact: true, name: "Methods & models" }))
    .toHaveAttribute("aria-current", "page");

  // The current Labs route stays usable when a user deliberately collapses the section.
  await labsSummary.click();
  await expect(labs).not.toHaveAttribute("open", "");
  await expect(labsSummary).toBeFocused();

  await page.setViewportSize({ width: 360, height: 640 });
  const dialog = await openMobileNavigation(page);
  const mobileLabs = dialog.locator("details").first();
  const mobileSummary = mobileLabs.locator("summary");
  await expect(mobileSummary).toBeFocused();
  await expect(mobileLabs.getByRole("button", { exact: true, name: "Methods & models" })).toBeHidden();

  await mobileSummary.click();
  await expect(mobileLabs.getByRole("button", { exact: true, name: "Methods & models" }))
    .toHaveAttribute("aria-current", "page");
  await page.setViewportSize({ width: 1280, height: 640 });
  await expect(dialog).toHaveCount(0);
  await expect(desktopNavigation.getByRole("button", { exact: true, name: "Methods & models" })).toBeFocused();
});

test("mobile navigation closes safely when the shell expands to desktop", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto("/overview");
  const dialog = await openMobileNavigation(page);

  await page.setViewportSize({ width: 1280, height: 640 });
  await expect(dialog).toHaveCount(0);
  const navigation = page.getByRole("navigation", { name: "Primary" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("button", { exact: true, name: "Overview" })).toBeFocused();
});

test("mobile navigation is a contained modal and reaches the current and next route", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto("/overview");
  await assertSyntheticShell(page);

  const dialog = await openMobileNavigation(page);
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(360);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(640);
  await expect(dialog.getByRole("button", { exact: true, name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await dialog.getByRole("button", { exact: true, name: "Sessions" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/sessions$/);
  await expect(page.locator("#main-content").getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
  await expect(page.locator("#main-content")).toBeFocused();
  await assertNoHorizontalOverflow(page);
});

test("shell focus survives forced colors and reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 720 });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/overview");

  const open = page.getByRole("button", { name: "Open navigation" });
  await open.focus();
  await assertFocusVisible(open);
  const transitionDurations = await open.evaluate((element) => getComputedStyle(element).transitionDuration);
  expect(transitionDurations.split(",").every((duration) => {
    const value = Number.parseFloat(duration);
    const milliseconds = duration.trim().endsWith("ms") ? value : value * 1_000;
    return milliseconds <= 0.011;
  })).toBe(true);
});

for (const viewport of VIEWPORTS) {
  test(`${viewport.name} primitive tour keeps truthful states accessible and unclipped`, async ({ page }) => {
    const forbiddenRequests: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (/^\/(?:auth|health|v1)(?:\/|$)/.test(path)) forbiddenRequests.push(path);
    });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/e2e/fixtures/ui-00.html");
    await expect(page.getByRole("heading", { level: 1, name: "UI-00 primitive state tour" })).toBeVisible();

    const loading = page.getByText("Loading bounded synthetic evidence…").locator("..");
    await expect(loading).toHaveAttribute("role", "status");
    await expect(loading).toHaveAttribute("aria-live", "polite");
    await expect(loading).toHaveAttribute("aria-atomic", "true");
    await expect(loading).not.toHaveAttribute("aria-busy");

    const error = page.getByRole("alert");
    await expect(error).toContainText("Synthetic error state");
    await expect(error).toContainText("without provider or session details");
    await page.getByRole("button", { name: "Retry synthetic operation" }).click();
    await expect(page.getByText("Synthetic retry requests: 1", { exact: true })).toBeVisible();

    const ordinaryEmpty = page.getByText("No synthetic observations", { exact: true }).locator("..");
    await expect(ordinaryEmpty).toHaveAttribute("data-tone", "empty");
    await expect(ordinaryEmpty).toHaveAttribute("role", "status");
    const closed = page.getByText("Synthetic capability unavailable", { exact: true }).locator("..");
    await expect(closed).toHaveAttribute("data-tone", "closed");
    await expect(closed).toContainText("no missing value is shown as zero");

    const unknownProgress = page.getByRole("progressbar", { name: "Unknown progress" });
    await expect(unknownProgress).not.toHaveAttribute("aria-valuenow");
    await expect(unknownProgress).toHaveAttribute("data-unknown", "true");
    await expect(unknownProgress).toHaveAttribute(
      "aria-valuetext",
      "Waiting for a fictional prerequisite · amount unknown",
    );
    await expect(page.getByRole("progressbar", { name: "Observed progress" })).toHaveAttribute(
      "aria-valuenow",
      "25",
    );
    const noEligibleCoverage = page.getByText("No eligible evidence", { exact: true }).locator("..");
    await expect(noEligibleCoverage.getByText("Not observed", { exact: true })).toBeVisible();
    await expect(noEligibleCoverage.locator(".coverage__track")).toHaveAttribute("data-unknown", "true");
    await expect(noEligibleCoverage.locator(".coverage__track")).toHaveAttribute("aria-hidden", "true");
    await expect(page.getByRole("meter", { name: "1 of 4 observations (25%)" })).toHaveAttribute(
      "aria-valuenow",
      "25",
    );

    const tablist = page.getByRole("tablist", { name: "Synthetic evidence states" });
    const ready = tablist.getByRole("tab", { name: /Ready/ });
    const unavailable = tablist.getByRole("tab", { name: /Unavailable/ });
    await ready.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(unavailable).toBeFocused();
    await expect(unavailable).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toHaveAccessibleName(/Unavailable/);
    await expect(page.getByRole("tabpanel")).toHaveText("Current synthetic state: blocked");
    await page.keyboard.press("Home");
    await expect(ready).toBeFocused();
    await page.keyboard.press("End");
    await expect(unavailable).toBeFocused();

    await assertNoHorizontalOverflow(page);
    expect(forbiddenRequests).toEqual([]);
  });
}

test("mobile dialog contains focus, inerts and locks the background, then restores both", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto("/e2e/fixtures/ui-00.html");
  const opener = page.getByRole("button", { name: "Open synthetic dialog" });
  await opener.click();

  const dialog = page.getByRole("dialog", { name: "Synthetic modal" });
  await expect(dialog).toBeVisible();
  const panelBounds = await dialog.boundingBox();
  expect(panelBounds).not.toBeNull();
  expect(panelBounds!.x).toBeGreaterThanOrEqual(0);
  expect(panelBounds!.y).toBeGreaterThanOrEqual(0);
  expect(panelBounds!.x + panelBounds!.width).toBeLessThanOrEqual(360);
  expect(panelBounds!.y + panelBounds!.height).toBeLessThanOrEqual(640);

  const background = page.getByTestId("fixture-background");
  expect(await background.evaluate((element) => element.closest("[inert]") !== null)).toBe(true);
  const scrollLocked = await page.evaluate(() => [document.documentElement, document.body].some((element) => {
    const overflow = getComputedStyle(element).overflowY;
    return overflow === "hidden" || overflow === "clip";
  }));
  expect(scrollLocked).toBe(true);

  const confirm = dialog.getByRole("button", { name: "Confirm synthetic action" });
  const close = dialog.getByRole("button", { name: "Close dialog" });
  await confirm.focus();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  expect(await background.evaluate((element) => element.closest("[inert]") !== null)).toBe(false);
  const unlocked = await page.evaluate(() => [document.documentElement, document.body].every((element) => {
    const overflow = getComputedStyle(element).overflowY;
    return overflow !== "hidden" && overflow !== "clip";
  }));
  expect(unlocked).toBe(true);
});
