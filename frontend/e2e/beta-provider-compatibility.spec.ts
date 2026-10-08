import { expect, test, type Page } from "@playwright/test";

const FIXTURE = "/e2e/fixtures/provider-compatibility-gating.html";
const OPERATIONAL_BLOCKER = "This compatibility result covers operational events, not session-text analysis, so prompt-text analysis stays disabled.";
const diagnostics = new WeakMap<Page, { consoleErrors: number; pageErrors: number }>();

async function open(page: Page, mode: string) {
  await page.goto(`${FIXTURE}?mode=${mode}`);
}

async function openMethods(page: Page) {
  await page.getByText("Methods & details", { exact: true }).click();
}

async function expectNoAnalysisRequests(page: Page) {
  await expect(page.getByTestId("compatibility-read-count")).toHaveText("Compatibility reads: 0");
  await expect(page.getByTestId("preview-count")).toHaveText("Preview preparations: 0");
  await expect(page.getByTestId("approval-count")).toHaveText("Preview approvals: 0");
}

test.beforeEach(async ({ page }) => {
  const counts = { consoleErrors: 0, pageErrors: 0 };
  diagnostics.set(page, counts);
  page.on("console", (message) => {
    if (message.type() === "error") counts.consoleErrors += 1;
  });
  page.on("pageerror", () => { counts.pageErrors += 1; });
});

test.afterEach(async ({ page }) => {
  const counts = diagnostics.get(page)!;
  expect(counts.consoleErrors, "synthetic capability gate has no console errors").toBe(0);
  expect(counts.pageErrors, "synthetic capability gate has no page errors").toBe(0);
});

test.describe("provider compatibility capability gate", () => {
  for (const { mode, stateLabel } of [
    { mode: "operational-exact", stateLabel: "Exact match" },
    { mode: "operational-compatible", stateLabel: "Compatible" },
  ] as const) {
    test(`does not admit ${mode.replace("operational-", "")} operational events as text analysis`, async ({ page }) => {
      await open(page, mode);

      const analyze = page.getByRole("button", { name: "Analyze locally", exact: true });
      await expect(analyze).toBeDisabled();
      await expect(page.getByRole("status").filter({ hasText: OPERATIONAL_BLOCKER })).toBeVisible();
      const checkProvider = page.getByRole("button", { name: "Check provider", exact: true });
      const methods = page.locator("summary").filter({ hasText: "Methods & details" });
      await checkProvider.focus();
      await expect(checkProvider).toBeFocused();
      await checkProvider.press("Tab");
      await expect(analyze).not.toBeFocused();
      await methods.focus();
      await methods.press("Enter");
      await expect(
        page.getByRole("status").filter({
          hasText: `${stateLabel}. Operational events: supported.`,
        }),
      ).toBeVisible();
      await expect(page.getByText("Operational events: supported", { exact: true })).toBeVisible();
      await expect(page.getByText("Session text analysis: supported", { exact: true })).not.toBeVisible();
      await expectNoAnalysisRequests(page);
      await expect(page.getByTestId("compatibility-check-count")).toHaveText("Compatibility checks: 0");
      await expect(page.getByRole("dialog")).not.toBeVisible();
    });
  }

  test("opens a local review and prepares only after an explicit text-capable action", async ({ page }) => {
    await open(page, "text");

    const analyze = page.getByRole("button", { name: "Analyze locally", exact: true });
    await expect(analyze).toBeEnabled();
    await expectNoAnalysisRequests(page);
    await analyze.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Ready to analyze", exact: true })).toBeVisible();
    await expectNoAnalysisRequests(page);

    await dialog.getByRole("button", { name: "Prepare redacted preview", exact: true }).click();
    await expect(page.getByTestId("preview-count")).toHaveText("Preview preparations: 1");
    await expect(page.getByTestId("approval-count")).toHaveText("Preview approvals: 0");
    await expect(dialog.getByRole("alert")).toContainText("Preview-bound local analysis is not available");
  });

  test("keeps a deferred operational check closed until an explicit compatible text result arrives", async ({ page }) => {
    await open(page, "recovery");
    const analyze = page.getByRole("button", { name: "Analyze locally", exact: true });
    const check = page.locator(".provider-compatibility").getByRole("button", {
      name: /Check(?:ing…| compatibility)/u,
    });
    const checkProvider = page.getByRole("button", {
      name: /Check(?:ing provider…| provider)/u,
    });
    await expect(analyze).toBeDisabled();
    await expectNoAnalysisRequests(page);

    await openMethods(page);
    await check.click();
    await expect(check).toBeDisabled();
    await expect(checkProvider).toBeDisabled();
    await expect(analyze).toBeDisabled();
    await expect(page).toHaveURL(/mode=recovery/u);
    await expect(page.getByRole("button", { name: /^Goal cue coverage/u })).toBeVisible();
    await expect(page.getByTestId("compatibility-check-count")).toHaveText("Compatibility checks: 1");
    await expectNoAnalysisRequests(page);

    await page.getByRole("button", { name: "Resolve synthetic provider check", exact: true }).click();
    await expect(analyze).toBeEnabled();
    await expect(page.getByText("Session text analysis: supported", { exact: true })).toBeVisible();
    await expectNoAnalysisRequests(page);
  });

  test("keeps the closed operational gate keyboard reachable at a narrow width", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 900 });
    await open(page, "operational-exact");
    const analyze = page.getByRole("button", { name: "Analyze locally", exact: true });
    await expect(analyze).toBeDisabled();
    await expect(page.getByText(OPERATIONAL_BLOCKER, { exact: true })).toBeVisible();
    const checkProvider = page.getByRole("button", { name: "Check provider", exact: true });
    await checkProvider.focus();
    await expect(checkProvider).toBeFocused();
    await checkProvider.press("Tab");
    await expect(analyze).not.toBeFocused();
    await openMethods(page);
    await expect(page.getByText("Operational events: supported", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expectNoAnalysisRequests(page);
  });
});
