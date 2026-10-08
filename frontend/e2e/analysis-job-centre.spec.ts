import { expect, test } from "@playwright/test";

test("labels the synthetic Job Centre as fictional and never invents execution", async ({ page }) => {
  await page.goto("/analysis-jobs");

  await expect(page.getByRole("heading", { name: "Analysis jobs" })).toBeVisible();
  await expect(page.getByText(/synthetic demo .* fictional fixtures only/i)).toBeVisible();
  await expect(page.getByText("No jobs ran")).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.locator("button.analysis-job-card")).toHaveCount(0);
});

test("opens the Job Centre from the keyboard navigation", async ({ page }) => {
  await page.goto("/");
  const navigationButton = page.getByRole("button", { name: "Analysis jobs" });
  await navigationButton.focus();
  await expect(navigationButton).toBeFocused();
  await navigationButton.press("Enter");

  await expect(page).toHaveURL(/\/analysis-jobs$/);
  await expect(page.getByRole("heading", { name: "Analysis jobs" })).toBeVisible();
});

for (const width of [360, 600, 900]) {
  test(`keeps the Job Centre boundary within a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/analysis-jobs");
    await expect(page.getByText("No jobs ran")).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }));
    expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  });
}
