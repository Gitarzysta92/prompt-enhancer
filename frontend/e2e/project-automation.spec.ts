import { expect, test } from "@playwright/test";

const SYNTHETIC_PROJECT_ID = "4".repeat(64);
const AUTOMATION_PATH = `/projects/${SYNTHETIC_PROJECT_ID}/automation`;

test("keeps project automation explicitly non-operational in the synthetic demo", async ({ page }) => {
  await page.goto(AUTOMATION_PATH);

  await expect(page.getByRole("heading", { name: "Project automation" })).toBeVisible();
  await expect(page.getByText(/Synthetic demo .* fictional fixtures only/)).toBeVisible();
  await expect(page.getByText("Automation is not running")).toBeVisible();
  await expect(page.getByText(/does not create standing consent, poll sessions, or invent grant and job history/)).toBeVisible();
  const settings = page.locator(".automation-settings");
  await expect(settings.getByRole("button")).toHaveCount(0);
  await expect(settings.getByRole("checkbox")).toHaveCount(0);
});

test("opens project automation from the project section navigation with a keyboard", async ({ page }) => {
  await page.goto(`/projects/${SYNTHETIC_PROJECT_ID}/overview`);

  const automationLink = page
    .locator('nav[data-project-section-nav="full"]')
    .getByRole("link", { name: "Automation" });
  await automationLink.focus();
  await expect(automationLink).toBeFocused();
  await automationLink.press("Enter");

  await expect(page).toHaveURL(new RegExp(`${AUTOMATION_PATH}$`));
  await expect(page.getByText("Automation is not running")).toBeVisible();
});

for (const width of [360, 900]) {
  test(`keeps the synthetic automation boundary within a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(AUTOMATION_PATH);
    await expect(page.getByText("Automation is not running")).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }));
    expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  });
}
