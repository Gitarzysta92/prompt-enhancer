import { expect, test } from "@playwright/test";

const fixture = "/e2e/fixtures/application-updates.html";
const instanceId = "a".repeat(32);

async function noHorizontalOverflow(page: import("@playwright/test").Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

async function expectNoRemoteRequests(
  page: import("@playwright/test").Page,
  navigate: () => Promise<unknown>,
): Promise<void> {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await navigate();
  await expect.poll(() => requests.length).toBeGreaterThan(0);
  expect(requests.filter((url) => !/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?\//u.test(url))).toEqual([]);
}

test("default unconfigured status is local and performs no mutation", async ({ page }) => {
  await expectNoRemoteRequests(page, () => page.goto(`${fixture}?mode=unconfigured`));
  const updates = page.getByRole("region", { name: "Software updates", exact: true });
  const summary = updates.getByRole("button", { name: /updates not connected/i });
  await expect(summary).toBeEnabled();
  await summary.click();
  await expect(updates.locator(".application-update__details")).toBeVisible();
  await expect(page.getByTestId("fixture-source")).toContainText("no network");
  await expect(page.getByTestId("update-receipt")).toHaveText("Last synthetic mutation: none");
});

test("status retry stays local and succeeds only after the explicit retry", async ({ page }) => {
  await page.goto(`${fixture}?mode=status-retry`);
  const retry = page.getByRole("button", { name: /Retry update status/i });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(page.getByRole("button", { name: /software is current/i })).toBeVisible();
  await expect(page.getByTestId("status-reads")).toContainText("Local status reads: 2");
});

for (const width of [360, 1440]) {
  test(`check, stage, cancel, retry, and downloaded handoff remain bounded at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${fixture}?mode=flow`);
    const updates = page.getByRole("region", { name: "Software updates", exact: true });
    const summary = updates.getByRole("button", { name: /software is current/i });
    await summary.focus();
    await expect(summary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(updates.getByRole("button", { name: "Check for updates", exact: true })).toBeVisible();
    await updates.getByRole("button", { name: "Check for updates", exact: true }).click();
    await expect(updates.getByRole("button", { name: /version 2\.0\.0 available/i })).toBeVisible();

    await updates.getByRole("button", { name: "Download version 2.0.0", exact: true }).click();
    await expect(updates.getByRole("button", { name: /stopping download|downloading version 2\.0\.0/i })).toBeVisible();
    await expect(updates).toContainText("8.0 MiB of 25 MiB");
    await expect(page.getByTestId("update-receipt")).toContainText(JSON.stringify({
      action: "stage",
      request: { expected_revision: 2, expected_instance_id: instanceId },
    }));

    await updates.getByRole("button", { name: "Cancel download", exact: true }).click();
    await expect(updates.getByRole("button", { name: /stopping download|downloading version 2\.0\.0/i })).toBeVisible();
    await expect(page.getByTestId("synthetic-state")).toContainText("state=staging; can_cancel=false; can_retry=false");
    await expect(updates.getByRole("button", { name: /update (?:check|download) needs attention/i })).toBeVisible();
    await expect(page.getByTestId("synthetic-state")).toContainText("state=failed; can_cancel=false; can_retry=true");
    await updates.getByRole("button", { name: /(?:Check again|Retry (?:download|update))/i }).click();
    await expect(page.getByTestId("update-receipt")).toContainText(JSON.stringify({
      action: "retry",
      request: { expected_revision: 5, expected_instance_id: instanceId },
    }));
    await expect(updates).toContainText("20 MiB of 25 MiB");
    await expect(updates.getByRole("button", { name: /version 2\.0\.0 downloaded/i })).toBeVisible({ timeout: 4_000 });
    await expect(updates).toContainText("Publisher verification has not been run.");
    await expect(updates.locator(".application-update__actions").getByRole("button", { name: /apply|install/i })).toHaveCount(0);
    await updates.getByRole("button", { name: "Verify downloaded package", exact: true }).click();
    await expect(updates.getByRole("button", { name: /version 2\.0\.0 reviewed/i })).toBeVisible();
    await expect(updates).toContainText("Publisher verification passed");
    await expect(page.getByTestId("update-receipt")).toContainText(JSON.stringify({
      action: "verify",
      request: { expected_revision: 7, expected_instance_id: instanceId },
    }));
    await expect(updates.locator(".application-update__actions").getByRole("button", { name: /apply|install/i })).toHaveCount(0);

    const targets = await updates.locator("button").evaluateAll((buttons) => buttons.map((button) => ({
      height: button.getBoundingClientRect().height,
      width: button.getBoundingClientRect().width,
    })));
    expect(targets.every(({ height }) => height >= 44)).toBe(true);
    await noHorizontalOverflow(page);
  });
}

test("unmount aborts the pending local status read without rendering stale data", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${fixture}?mode=unmount`);
  await page.getByRole("button", { name: "Unmount update control", exact: true }).click();
  await expect(page.getByRole("region", { name: "Software updates", exact: true })).toHaveCount(0);
  await expect(page.getByTestId("status-aborted")).toHaveText("Status read aborted: true");
  expect(errors).toEqual([]);
});

test("rejected package review stays truthful in a short narrow drawer", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 360 });
  await page.goto(`${fixture}?mode=rejected`);
  const updates = page.getByRole("region", { name: "Software updates", exact: true });
  await updates.getByRole("button", { name: /version 2\.0\.0 needs review/i }).click();
  await expect(updates).toContainText("This package format is not supported here");
  await expect(updates).toContainText("Installation handoff is not connected");
  await expect(updates.locator(".application-update__actions").getByRole("button", { name: /apply|install/i })).toHaveCount(0);
  await noHorizontalOverflow(page);
});
