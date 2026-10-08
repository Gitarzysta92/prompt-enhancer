import { expect, test } from "@playwright/test";

test("shows the exact all-twenty metric operability gate", async ({ page }) => {
  await page.goto("/research/methods");

  await expect(page.getByRole("heading", {
    name: "What can produce measured evidence today",
  })).toBeVisible();
  const summary = page.getByLabel("Metric operability summary");
  await expect(summary.getByText("Measured paths shipped").locator("..")).toContainText("16");
  await expect(summary.getByText("Need project profile").locator("..")).toContainText("0");
  await expect(summary.getByText("Need source adapter").locator("..")).toContainText("4");
  await expect(summary.getByText("Model-authored metrics").locator("..")).toContainText("0");
  await expect(page.locator("[data-operability-state]")).toHaveCount(20);
  await expect(page.locator('[data-operability-state="available_when_evidence_exists"]')).toHaveCount(16);
  await expect(page.locator('[data-operability-state="task_profile_configuration_required"]')).toHaveCount(0);
  await expect(page.locator('[data-operability-state="provider_adapter_required"]')).toHaveCount(4);
  await expect(page.getByText("Models never author measured values")).toBeVisible();
});

test("keeps the operability map readable at 360px", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto("/research/methods");
  await expect(page.getByRole("heading", {
    name: "What can produce measured evidence today",
  })).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
});
