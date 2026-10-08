import { expect, test } from "@playwright/test";

/**
 * Every metric card carries scope · contributors · model · evidence context in
 * both the desktop team dashboard and the 360x500 native overlay, reachable by
 * keyboard focus as well as pointer, and never rendered as a zero.
 */
test.describe("metric context facts", () => {
  test("team dashboard explainer cards state the Team scope and cohort contributors on focus", async ({ page }) => {
    await page.goto("/team");
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    const trigger = table.getByRole("button").first();
    await trigger.focus();
    const card = page.locator(".metric-explainer-card");
    await expect(card).toHaveCount(1);
    const context = card.getByRole("region", { name: "Context and evidence" });
    await expect(context).toHaveAttribute("data-scope", "team");
    await expect(context).toContainText("Team · Synthetic platform guild (fixture cohort)");
    await expect(context).toContainText(/members in cohort|no aggregate record|not observed/);
    await expect(context).toContainText(/Model/);
    await expect(context).not.toContainText(/\b0\/0\b/);
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
  });

  test("the 360x500 overlay team drawer explainer card carries the same context without shifting layout", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 500 });
    await page.goto("/overlay/model-ensemble");
    await expect(page.getByRole("heading", { name: "Live metric watch" })).toBeVisible();
    const drawer = page.locator("details.team-context-drawer");
    await drawer.locator("summary").click();
    const list = drawer.getByRole("list", { name: /Task framing/ });
    await expect(list).toBeVisible();
    const measure = () => list.evaluate((element) => ({ top: (element as HTMLElement).offsetTop, height: (element as HTMLElement).offsetHeight }));
    const before = await measure();
    await list.getByRole("button", { name: /^Task/ }).first().focus();
    const card = page.locator(".metric-explainer-card, .metric-knowledge-card");
    await expect(card).toBeVisible();
    const context = card.getByRole("region", { name: "Context and evidence" });
    await expect(context).toHaveAttribute("data-scope", "team");
    await expect(context).toContainText("Team · Synthetic platform guild (fixture cohort)");
    await expect(context).toContainText(/Contributors/);
    await expect(context).not.toContainText("0/0");
    const after = await measure();
    expect(after).toEqual(before);
    const box = await card.boundingBox();
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(360);
    // Pointer path reaches the same card.
    await page.keyboard.press("Escape");
    await expect(page.locator(".metric-explainer-card, .metric-knowledge-card")).toHaveCount(0);
    await list.getByRole("button", { name: /^Task/ }).first().hover();
    await expect(page.locator(".metric-explainer-card, .metric-knowledge-card").getByRole("region", { name: "Context and evidence" })).toBeVisible();
  });
});
