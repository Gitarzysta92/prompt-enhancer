import { expect, test, type Page } from "@playwright/test";

async function expectNoPageOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.content, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport);
}

async function installClsObserver(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state = { value: 0 };
    const observer = new PerformanceObserver((list) => {
      for (const rawEntry of list.getEntries()) {
        const entry = rawEntry as PerformanceEntry & { hadRecentInput: boolean; value: number };
        if (!entry.hadRecentInput) state.value += entry.value;
      }
    });
    observer.observe({ type: "layout-shift", buffered: true });
    Object.assign(window, { __syntheticClsState: state, __syntheticClsObserver: observer });
  });
}

async function currentCls(page: Page): Promise<number> {
  await page.evaluate(() => new Promise<void>((resolve) => (
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  )));
  return page.evaluate(() => (
    window as typeof window & { __syntheticClsState: { value: number } }
  ).__syntheticClsState.value);
}

async function resetSettledCls(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>((resolve) => (
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  )));
  await page.evaluate(() => {
    const target = window as typeof window & {
      __syntheticClsObserver: PerformanceObserver;
      __syntheticClsState: { value: number };
    };
    target.__syntheticClsObserver.takeRecords();
    target.__syntheticClsState.value = 0;
  });
}

async function clickUntilText(
  page: Page,
  selector: string,
  expectedText: string,
): Promise<number> {
  return page.locator(selector).evaluate((element, expected) => new Promise<number>((resolve, reject) => {
    const startedAt = performance.now();
    let timeout = 0;
    const observer = new MutationObserver(() => finish());
    const finish = () => {
      if (!document.body.innerText.includes(expected)) return;
      observer.disconnect();
      window.clearTimeout(timeout);
      requestAnimationFrame(() => resolve(performance.now() - startedAt));
    };
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    timeout = window.setTimeout(() => {
      observer.disconnect();
      reject(new Error(`Synthetic interaction did not render: ${expected}`));
    }, 1_000);
    (element as HTMLElement).click();
    finish();
  }), expectedText);
}

for (const width of [360, 1440]) {
  test(`maximum Agent catalogs and retained history stay bounded at ${width}px`, async ({ page }) => {
    const browserErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));
    await installClsObserver(page);
    await page.setViewportSize({ width, height: width === 360 ? 900 : 1_000 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-stress");

    const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
    const retained = page.getByRole("article", { name: "Maximum retained chat", exact: true });
    const activity = retained.getByRole("region", { name: "Retained agent activity", exact: true });
    const artifacts = retained.getByRole("region", { name: /Artifacts/u });
    await expect(activity.getByText("Showing activity 3,801–4,000 of 4,000 events.", { exact: true })).toBeVisible();
    await expect(rail.locator(".agent-rail__project")).toHaveCount(40);
    await expect(rail.locator(".agent-rail__sessions > li")).toHaveCount(40);
    await expect(artifacts.locator(".agent-artifacts__card")).toHaveCount(50);
    await expect(activity.locator(".agent__activity-event")).toHaveCount(200);
    expect(await activity.locator(":scope > *").count()).toBeLessThanOrEqual(252);
    await resetSettledCls(page);

    await rail.getByRole("button", { name: "Load more projects", exact: true }).click();
    await expect(rail.getByText("200 of 200 projects available", { exact: true })).toBeVisible();
    await expect(rail.locator(".agent-rail__project")).toHaveCount(40);

    for (let pageNumber = 2; pageNumber <= 20; pageNumber += 1) {
      await rail.getByRole("button", { name: "Load more chats", exact: true }).click();
      await expect(rail.getByText(`${pageNumber * 100} of 2000 chats available`, { exact: true })).toBeVisible();
    }
    await expect(rail.locator(".agent-rail__sessions > li")).toHaveCount(40);

    for (let pageNumber = 2; pageNumber <= 5; pageNumber += 1) {
      await artifacts.getByRole("button", { name: "Load more artifacts", exact: true }).click();
      await expect(artifacts.getByText(`${pageNumber * 100} of 500 active artifacts loaded`, { exact: true })).toBeVisible();
    }
    await expect(artifacts.locator(".agent-artifacts__card")).toHaveCount(50);

    const transcriptLatency = await clickUntilText(
      page,
      "nav[aria-label='Agent activity pages'] button",
      "Showing activity 3,601–3,800 of 4,000 events.",
    );
    const projectPageLatency = await clickUntilText(
      page,
      "nav[aria-label='Agent project pages'] button:last-child",
      "Showing 41–80 of 200",
    );
    const chatPageLatency = await clickUntilText(
      page,
      "nav[aria-label='Agent chat pages'] button:last-child",
      "Showing 41–80 of 2,000",
    );
    const artifactPageLatency = await clickUntilText(
      page,
      "nav[aria-label='Artifact pages'] button:last-child",
      "Showing 51–100 of 500",
    );
    expect(transcriptLatency, `transcript response ${transcriptLatency.toFixed(1)}ms`).toBeLessThan(200);
    expect(projectPageLatency, `project page response ${projectPageLatency.toFixed(1)}ms`).toBeLessThan(200);
    expect(chatPageLatency, `chat page response ${chatPageLatency.toFixed(1)}ms`).toBeLessThan(200);
    expect(artifactPageLatency, `artifact page response ${artifactPageLatency.toFixed(1)}ms`).toBeLessThan(200);
    await expect(activity.locator(".agent__activity-event")).toHaveCount(200);
    const mountedActivityNodes = await activity.locator(":scope > *").count();
    expect(mountedActivityNodes).toBeLessThanOrEqual(252);
    await expect(rail.locator(".agent-rail__project")).toHaveCount(40);

    const transcriptButton = activity.getByRole("button", { name: "Earlier 200", exact: true });
    const transcriptButtonBox = await transcriptButton.boundingBox();
    expect(transcriptButtonBox?.height ?? 0).toBeGreaterThanOrEqual(44);
    await expectNoPageOverflow(page);
    const cls = await currentCls(page);
    expect(cls).toBeLessThan(0.02);
    expect(browserErrors).toEqual([]);
    test.info().annotations.push({
      type: "sweep-01c.3 stress evidence",
      description: JSON.stringify({
        artifactsLoaded: 500,
        artifactsMounted: 50,
        artifactPageLatencyMs: Number(artifactPageLatency.toFixed(2)),
        chatsLoaded: 2_000,
        chatsMounted: 40,
        chatPageLatencyMs: Number(chatPageLatency.toFixed(2)),
        cls: Number(cls.toFixed(6)),
        historyLoaded: 4_000,
        historyMounted: 200,
        mountedActivityNodes,
        projectPageLatencyMs: Number(projectPageLatency.toFixed(2)),
        projectsLoaded: 200,
        projectsMounted: 40,
        transcriptLatencyMs: Number(transcriptLatency.toFixed(2)),
        viewportWidth: width,
      }),
    });
  });

  test(`maximum loaded MCP catalog stays paged and operable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-store&state=scale");

    await page.getByRole("button", { name: /Agent settings/ }).click();
    const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
    await settings.getByRole("tab", { name: "MCP Store", exact: true }).click();
    const store = settings.getByRole("region", { name: "MCP Store", exact: true });
    const cards = store.locator("article.agent-mcp-store__card");
    await expect(cards).toHaveCount(48);
    await expect(store.getByText("Showing 1–48 of 120", { exact: true })).toBeVisible();
    await expect(store.getByText("Synthetic scale server 000", { exact: true })).toBeVisible();
    await expect(store.getByText("Synthetic scale server 048", { exact: true })).toHaveCount(0);

    const pager = store.getByRole("navigation", { name: "Loaded MCP server pages", exact: true });
    await pager.getByRole("button", { name: "Later", exact: true }).click();
    await expect(cards).toHaveCount(48);
    await expect(store.getByText("Showing 49–96 of 120", { exact: true })).toBeVisible();
    await expect(store.getByText("Synthetic scale server 000", { exact: true })).toHaveCount(0);
    await expect(store.getByText("Synthetic scale server 048", { exact: true })).toBeVisible();
    await expectNoPageOverflow(page);
  });

  test(`maximum timeline bounds SVG nodes and reveals detail on zoom at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=scale-timeline");

    const timeline = page.getByRole("region", { name: "What happened, when", exact: true });
    await expect(timeline.locator(".session-timeline__turn")).toHaveCount(300);
    await expect(timeline.locator(".session-timeline__gap")).toHaveCount(300);
    await expect(timeline.locator(".session-timeline__tool")).toHaveCount(500);
    await expect(timeline.locator(".session-timeline__check")).toHaveCount(200);
    await expect(timeline.locator(".session-timeline__marker")).toHaveCount(200);
    await expect(timeline.locator("[data-bounded='true']")).toContainText("Drawing 1,500 of 8,000 timeline items");

    const zoomIn = timeline.getByRole("button", { name: "Zoom in", exact: true });
    for (let step = 0; step < 6; step += 1) await zoomIn.click();
    await expect(timeline.locator("[data-bounded='false']")).toContainText("Drawing all");
    await expectNoPageOverflow(page);
  });
}
