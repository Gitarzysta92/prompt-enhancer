import { expect, test } from "@playwright/test";

for (const viewport of [
  { width: 360, height: 500 },
  { width: 420, height: 620 },
]) {
  test(`keeps live-metric status and controls readable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/overlay/model-ensemble");

    await expect(page.getByRole("heading", { name: "Live metric watch" })).toBeVisible();
    await expect(page.locator(".model-ensemble-overlay__connection")).toHaveText("No active watch");
    await expect(page.getByText(/Reconnecting · last receipt retained/i)).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Live watch scope" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Open selected session in dashboard/i })).toBeVisible();

    const layout = await page.evaluate(() => {
      const root = document.querySelector<HTMLElement>(".model-ensemble-overlay");
      if (root === null) throw new Error("synthetic overlay root missing");
      const textSelectors = "small,span,p,strong,button,select,dt,dd,b";
      const tooSmall = [...root.querySelectorAll<HTMLElement>(textSelectors)]
        .filter((element) => {
          const style = getComputedStyle(element);
          return style.display !== "none"
            && style.visibility !== "hidden"
            && element.getClientRects().length > 0
            && Number.parseFloat(style.fontSize) < 12;
        })
        .map((element) => `${element.tagName.toLowerCase()}.${element.className}`);
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        tooSmall,
      };
    });

    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
  });
}

test("keeps keyboard focus visible in forced-colors and reduced-motion modes", async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 620 });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/overlay/model-ensemble");

  const watchButton = page.getByRole("button", { name: "Watch selected session" });
  await expect(watchButton).toBeEnabled();
  await watchButton.focus();
  await expect(watchButton).toBeFocused();
  const styles = await watchButton.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      transitionDuration: style.transitionDuration,
    };
  });
  expect(styles.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(styles.outlineWidth)).toBeGreaterThanOrEqual(3);
  expect(styles.transitionDuration).toMatch(/^(0s|0ms)$/);
});
