import { expect, test } from "@playwright/test";

const FIRST_PROJECT_ID = `${"0".repeat(61)}3e8`;
const PAGE_TWO_SESSION_ID = `${"0".repeat(62)}15`;

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const dimensions = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.content, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport);
}

for (const width of [360, 1440]) {
  test(`bounded source maintenance stays usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/e2e/fixtures/source-maintenance.html");

    await page.getByText("Advanced source maintenance", { exact: true }).click();
    await expect(page.locator(".project-group__header")).toHaveCount(12);
    await expect(page.locator(".source-session-list li")).toHaveCount(0);
    await expect(page.locator("details.project-group__sessions").first().locator("summary")).toHaveCSS("min-height", "44px");
    await expect(page.getByRole("navigation", { name: "Projects in local source maintenance" }).getByRole("button", { name: "Later", exact: true })).toHaveCSS("min-height", "44px");
    await expectNoHorizontalOverflow(page);

    const firstProject = page.locator("details.project-group__sessions").first();
    const firstSummary = firstProject.locator("summary");
    await firstSummary.focus();
    await page.keyboard.press("Enter");
    await expect(firstProject.locator(".source-session-list li")).toHaveCount(20);
    await expect(firstProject.getByRole("button", { name: "Later", exact: true })).toHaveCSS("min-height", "44px");
    await expectNoHorizontalOverflow(page);

    await firstProject.getByRole("button", { name: "Later", exact: true }).click();
    await firstProject.getByRole("checkbox", { name: /Synthetic Session 0-20/ }).click();
    await firstProject.getByRole("button", { name: "Earlier", exact: true }).click();
    await expect(firstSummary).toContainText("1 selected on another page");

    const projectSearch = page.getByRole("searchbox", { name: "Search loaded projects" });
    await projectSearch.fill("Synthetic Project 20");
    await expect(page.getByText("Synthetic Project 20", { exact: true })).toBeVisible();
    await expect(page.getByText(/1 selected session outside the current project view/)).toBeVisible();
    await projectSearch.fill("");
    await page.getByRole("button", { name: "Import operational metrics", exact: true }).click();
    await expect(page.getByTestId("analyze-receipt")).toHaveText(
      JSON.stringify({ project_ids: [], session_ids: [PAGE_TWO_SESSION_ID], max_sessions: 10 }),
    );

    await page.getByRole("button", { name: "Clear selection", exact: true }).click();
    await page.locator(".project-group__header").first().getByRole("checkbox").click();
    await projectSearch.fill("Synthetic Project 20");
    await expect(page.getByText(/45 selected sessions outside the current project view/)).toBeVisible();
    await page.getByRole("button", { name: "Import operational metrics", exact: true }).click();
    await expect(page.getByTestId("analyze-receipt")).toHaveText(
      JSON.stringify({ project_ids: [FIRST_PROJECT_ID], session_ids: [], max_sessions: 10 }),
    );
    await expectNoHorizontalOverflow(page);
  });
}
