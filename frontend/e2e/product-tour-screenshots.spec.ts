import { test, expect } from "@playwright/test";

// Opt-in because PNGs are documentation artifacts, not routine test output:
//   PE_CAPTURE_PRODUCT_TOUR=1 npx playwright test product-tour-screenshots.spec.ts
const capture = process.env.PE_CAPTURE_PRODUCT_TOUR === "1";

test.describe("synthetic product tour screenshots", () => {
  test.skip(!capture, "Set PE_CAPTURE_PRODUCT_TOUR=1 to regenerate README imagery");
  test.use({ viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1 });

  const frames = [
    ["overview-models", "panel=models", "overview-models.png"],
    ["agent-chat", "panel=agent-shell", "agent-chat.png"],
    ["mcp-cards", "panel=agent-mcp-store", "mcp-cards.png"],
    ["live-mini-window", "panel=live", "live-mini-window.png"],
    ["session-radar", "panel=radar", "session-radar.png"],
    ["ensemble-overlay", "panel=ensemble", "ensemble-overlay.png"],
  ] as const;

  for (const [name, query, file] of frames) {
    test(name, async ({ page }) => {
      await page.goto(`/e2e/fixtures/product-tour.html?${query}`, { waitUntil: "networkidle" });
      await expect(page.locator("body")).toContainText("Synthetic workflow fixture");
      if (name === "mcp-cards") {
        await page.getByRole("button", { name: /Agent settings/ }).click();
        const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
        await settings.getByRole("tab", { name: "MCP Store", exact: true }).click();
        await expect(settings.getByText("Synthetic MCP Files")).toBeVisible();
      }
      if (name === "live-mini-window") {
        await expect(page.getByTestId("synthetic-demo-badge")).toBeVisible();
        await page.addStyleTag({ content: ".live-window { min-height: unset !important; }" });
        await page.getByTestId("live-tour").screenshot({ path: `../docs/images/${file}` });
        return;
      }
      if (name === "session-radar") {
        await expect(page.getByRole("heading", { name: "Session radar" })).toBeVisible();
        await expect(page.getByText("12 of 12 measurable", { exact: true })).toBeVisible();
        await page.getByTestId("radar-tour").screenshot({ path: `../docs/images/${file}` });
        return;
      }
      if (name === "ensemble-overlay") {
        await expect(page.getByRole("heading", { name: "Live metric watch" })).toBeVisible();
        await expect(page.getByText("Measured", { exact: true })).toBeVisible();
        await expect(page.getByText("1/20", { exact: true })).toBeVisible();
        await page.getByTestId("ensemble-tour").screenshot({ path: `../docs/images/${file}` });
        return;
      }
      await page.screenshot({ path: `../docs/images/${file}`, fullPage: true });
    });
  }
});
