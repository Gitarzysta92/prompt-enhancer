import { expect, test } from "@playwright/test";

test("renders one keyboard skip link", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("a.skip-link")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
    "href",
    "#main-content",
  );
});

test("reviews synthetic discovery and inspects generic metrics", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Discovery inbox" })).toBeVisible();
  await expect(page.getByText("Synthetic demo · Fixture ready")).toBeVisible();
  await expect(page.getByRole("button", { name: /Candidate aaaaaa/ })).toBeVisible();
  await expect(page.getByLabel("2 candidates need review")).toBeVisible();

  await page.getByRole("combobox", { name: "Task category" }).selectOption("feature_implementation");
  await page.getByRole("button", { name: "Accept as one task" }).click();
  await expect(page.getByLabel("1 candidate needs review")).toBeVisible();
  await page.getByRole("button", { name: "Analyze task" }).click();
  await expect(page.getByRole("heading", { name: "Feature Implementation" })).toBeVisible();
  const sessionCount = page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Session count" }),
  });
  await expect(sessionCount).toBeVisible();
  await expect(sessionCount.locator(".metric-card__value")).toHaveText("3");
  await expect(page.getByRole("heading", { name: "Verification pass rate" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Input tokens" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Analysis provenance" })).toBeVisible();
});

for (const width of [900, 600]) {
  test(`keeps the discovery workspace within a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Discovery inbox" })).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }));
    expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  });
}
