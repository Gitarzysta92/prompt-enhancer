import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

async function fitsViewport(page: Page): Promise<void> {
  const width = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
  expect(width.content, "Populated workflow must not force page-wide horizontal scrolling").toBeLessThanOrEqual(width.viewport);
  const escaped = await page.evaluate(() => {
    const main = document.querySelector("main")!;
    const bounds = main.getBoundingClientRect();
    const style = getComputedStyle(main);
    const left = bounds.left + Number.parseFloat(style.paddingLeft);
    const right = bounds.right - Number.parseFloat(style.paddingRight);
    return Array.from(main.querySelectorAll("section, article, form, textarea, input, select, button, svg")).filter((element) => {
      if (element.getClientRects().length === 0) return false;
      // The review scrim intentionally covers the viewport rather than the
      // padded content box. Its drawer is checked like every other panel.
      if (element.classList.contains("agent__review-backdrop")) return false;
      // Wide history tables intentionally have their own horizontal scroller.
      for (let parent = element.parentElement; parent && parent !== main; parent = parent.parentElement) {
        if (["auto", "scroll"].includes(getComputedStyle(parent).overflowX) && parent.scrollWidth > parent.clientWidth) return false;
      }
      const rect = element.getBoundingClientRect();
      return rect.width > 1 && (rect.left < left - 1 || rect.right > right + 1);
    }).map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        element: `${element.tagName}.${element.className}`,
        left: Math.round(rect.left * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
        contentLeft: Math.round(left * 10) / 10,
        contentRight: Math.round(right * 10) / 10,
      };
    });
  });
  expect(escaped, "Visible panels and controls must stay inside the padded content area").toEqual([]);
}

test("short desktop keeps projects, Agent settings, and bounded runtime controls reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell");

  const projectRail = page.locator(".agent__side-scroll");
  const settings = page.getByRole("button", { name: /Agent settings/ });
  const runtime = page.getByRole("region", { name: "Shared local model runtime", exact: true });
  await expect(projectRail).toBeVisible();
  await expect(settings).toBeVisible();
  await expect(settings).toBeInViewport();
  await expect(runtime).toBeVisible();

  const runtimeSummary = runtime.getByLabel(/Model and context settings\./u);
  await expect(runtimeSummary).toBeInViewport();
  await runtimeSummary.click();
  const runtimePanel = runtime.getByRole("dialog", { name: "Choose model and runtime settings", exact: true });
  await expect(runtimePanel).toBeVisible();
  await runtimePanel.getByText("Context, compatibility & runtime evidence", { exact: true }).click();
  const details = runtimePanel.getByText("Runtime evidence & capabilities", { exact: true });
  await details.click();
  await expect(runtimePanel.getByText("Offload evidence", { exact: true })).toBeVisible();
  const layout = await page.evaluate(() => {
    const rail = document.querySelector<HTMLElement>(".agent__side-scroll")!;
    const settingsButton = document.querySelector<HTMLElement>(".agent__settings-trigger")!;
    const runtimeCard = document.querySelector<HTMLElement>(".agent-runtime__composer-panel")!;
    const railBox = rail.getBoundingClientRect();
    const settingsBox = settingsButton.getBoundingClientRect();
    const runtimeBox = runtimeCard.getBoundingClientRect();
    return {
      railHeight: railBox.height,
      settingsBelowRail: settingsBox.top >= railBox.bottom,
      runtimeTop: runtimeBox.top,
      runtimeBottom: runtimeBox.bottom,
      viewportHeight: window.innerHeight,
      runtimeHeight: runtimeBox.height,
      runtimeScrollable: runtimeCard.scrollHeight > runtimeCard.clientHeight,
    };
  });
  expect(layout.railHeight).toBeGreaterThanOrEqual(192);
  expect(layout.settingsBelowRail, JSON.stringify(layout)).toBe(true);
  expect(layout.runtimeTop, JSON.stringify(layout)).toBeGreaterThanOrEqual(8);
  expect(layout.runtimeBottom, JSON.stringify(layout)).toBeLessThanOrEqual(layout.viewportHeight - 8);
  expect(layout.runtimeHeight).toBeLessThanOrEqual(416);
  expect(layout.runtimeScrollable).toBe(true);

  await runtime.getByRole("button", { name: "Close model and context settings", exact: true }).click();
  await settings.click();
  await expect(page.getByRole("dialog", { name: "Agent settings", exact: true })).toBeVisible();
  await fitsViewport(page);
});

test("720px Agent workspace keeps the latest reply and compact composer in view", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell");

  const conversation = page.getByRole("region", { name: "Agent conversation", exact: true });
  const transcript = conversation.getByRole("log");
  const latestReply = conversation.getByText(
    "The fictional module is ready for review. Open Files & review to inspect its bounded workspace view.",
    { exact: true },
  );
  const composer = conversation.getByRole("form", { name: "Message composer", exact: true });
  const message = composer.getByRole("textbox", { name: "Message to the agent", exact: true });
  const send = composer.getByRole("button", { name: "Send", exact: true });

  await expect(transcript).toBeVisible();
  await expect(latestReply).toBeVisible();
  await expect(composer).toBeVisible();
  await expect(composer).toBeInViewport();
  await expect(send).toBeInViewport();
  await message.fill("Review the synthetic result without leaving this chat.");
  await expect(send).toBeEnabled();

  const layout = await conversation.evaluate((root) => {
    const log = root.querySelector<HTMLElement>("[role='log']")!;
    const latest = Array.from(root.querySelectorAll<HTMLElement>(".agent__turn--assistant")).at(-1)!;
    const compose = root.querySelector<HTMLElement>("form[aria-label='Message composer']")!;
    const stage = root.querySelector<HTMLElement>(".agent__conversation-stage")!;
    const logBox = log.getBoundingClientRect();
    const latestBox = latest.getBoundingClientRect();
    const composeBox = compose.getBoundingClientRect();
    return {
      composerBottom: composeBox.bottom,
      latestInsideTranscript: latestBox.top >= logBox.top - 1 && latestBox.bottom <= logBox.bottom + 1,
      stageOverflowY: getComputedStyle(stage).overflowY,
      transcriptOverflowY: getComputedStyle(log).overflowY,
      viewportHeight: window.innerHeight,
    };
  });
  expect(layout.composerBottom, JSON.stringify(layout)).toBeLessThanOrEqual(layout.viewportHeight);
  expect(layout.latestInsideTranscript, JSON.stringify(layout)).toBe(true);
  expect(layout.stageOverflowY).not.toMatch(/auto|scroll/u);
  expect(layout.transcriptOverflowY).toMatch(/auto|scroll/u);

  const nestedRailScrollers = await page.locator(".agent__side-scroll").evaluate((rail) => (
    Array.from(rail.querySelectorAll<HTMLElement>("*"))
      .filter((element) => /auto|scroll/u.test(getComputedStyle(element).overflowY))
      .filter((element) => element.scrollHeight > element.clientHeight + 1)
      .length
  ));
  expect(nestedRailScrollers).toBe(0);
  await expect(page.locator("[data-agent-runtime-announcer='true']")).toHaveCount(1);

  const detailToggle = conversation.getByText("Chat details", { exact: true });
  await detailToggle.click();
  const chatDetails = conversation.getByRole("group", { name: "Chat details", exact: true });
  await expect(chatDetails).toBeVisible();
  await chatDetails.getByRole("button", { name: "Close chat details", exact: true }).click();
  await expect(chatDetails).toBeHidden();
  await expect(detailToggle).toBeFocused();
  await fitsViewport(page);
});

for (const width of [360, 1440]) {
  test(`MCP Store exposes source, compatibility, sorting and managed lifecycle at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-store");

    await page.getByRole("button", { name: /Agent settings/ }).click();
    const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
    await settings.getByRole("tab", { name: "MCP Store", exact: true }).click();
    await expect(settings).toHaveAttribute("data-settings-tab", "store");

    const store = settings.getByRole("region", { name: "MCP Store", exact: true });
    const browse = store.getByRole("tab", { name: "Browse servers", exact: true });
    const managed = store.getByRole("tab", { name: "Managed servers", exact: true });
    await expect(browse).toHaveAttribute("aria-selected", "true");
    await expect(store.getByLabel("Search MCP servers", { exact: true })).toBeVisible();
    await expect(store.getByRole("button", { name: /^Review Synthetic MCP/u })).toHaveCount(4);
    await expect(store.getByText("Official Registry", { exact: true })).toHaveCount(4);
    const sort = store.getByRole("combobox", { name: "Sort loaded results", exact: true });
    await sort.selectOption("title");
    await expect(store.getByText("Sorted loaded results only", { exact: true })).toBeVisible();
    await expect(store.locator("article.agent-mcp-store__card").first()).toContainText("Synthetic MCP Browser");
    await fitsViewport(page);

    await store.getByRole("button", { name: "Review Synthetic MCP Files", exact: true }).click();
    await expect(store.getByRole("heading", { name: "Declared setup options", exact: true })).toBeVisible();
    await expect(store.getByText("Configuration required", { exact: true })).toBeVisible();
    await expect(store.getByText("This machine's runtime has not been probed", { exact: true })).toBeVisible();
    await expect(store.getByText("Protected lifecycle continues in a managed plan", { exact: true })).toBeVisible();
    await expect(store.getByText("Install unavailable", { exact: true })).toHaveCount(0);
    await fitsViewport(page);
    await store.getByRole("button", { name: "Back to catalog", exact: true }).click();

    await browse.focus();
    await page.keyboard.press("ArrowRight");
    await expect(managed).toBeFocused();
    await expect(managed).toHaveAttribute("aria-selected", "true");
    const managedRegion = store.getByRole("region", { name: "Managed MCP servers", exact: true });
    const managedPlan = managedRegion.getByRole("button", { name: "Open Synthetic MCP Files managed plan — Plan saved", exact: true });
    await expect(managedPlan).toContainText("Plan saved");
    await expect(managedPlan).toContainText("Compatibility not checked");
    await expect(store.getByLabel("Search MCP servers", { exact: true })).toHaveCount(0);
    await fitsViewport(page);

    await managedPlan.click();
    await expect(store.getByRole("heading", { name: "Synthetic MCP Files", exact: true })).toBeVisible();
    await expect(store.getByRole("heading", { name: "Compatibility check", exact: true })).toBeVisible();
    await expect(store.getByText("Prepared plan · revision 1", { exact: true })).toBeVisible();
    const lifecycleProof = store.getByRole("region", { name: "Trusted MCP lifecycle acceptance", exact: true });
    await expect(lifecycleProof).toBeVisible();
    await expect(lifecycleProof.getByRole("button", { name: "Begin trusted MCP proof", exact: true })).toBeDisabled();
    await expect(lifecycleProof).toContainText("Open one live Agent chat inside a saved project");
    await fitsViewport(page);
    await store.getByRole("button", { name: "Back to MCP Store", exact: true }).click();
    await browse.click();
    await expect(browse).toHaveAttribute("aria-selected", "true");
    await expect(store.getByLabel("Search MCP servers", { exact: true })).toBeVisible();
  });

  test(`MCP Store contains hostile presentation and cursor replay at ${width}px`, async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-store&state=hostile");

    await page.getByRole("button", { name: /Agent settings/ }).click();
    const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
    await settings.getByRole("tab", { name: "MCP Store", exact: true }).click();
    const store = settings.getByRole("region", { name: "MCP Store", exact: true });

    await expect(store.getByText("<img src=x onerror=synthetic>", { exact: true })).toBeVisible();
    await expect(store.getByText("<script>synthetic()</script>", { exact: true })).toBeVisible();
    await expect(store.locator("script")).toHaveCount(0);
    await expect(store.locator("img[src='x']")).toHaveCount(0);
    await expect(store.locator("img")).toHaveCount(0);
    expect(requests.some((url) => url.includes("tracking.example"))).toBe(false);

    await store.getByRole("button", { name: "Load more", exact: true }).click();
    await expect(store.getByText(/repeated an earlier page cursor/i)).toBeVisible();
    const restart = store.getByRole("button", { name: "Restart catalog", exact: true });
    await restart.focus();
    await expect(restart).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(store.getByRole("button", { name: "Load more", exact: true })).toBeVisible();
    await fitsViewport(page);
  });

  test(`active chat reconciles exact MCP project tools with the Store at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-project-tools");

    await page.getByRole("button", { name: "Project tools", exact: true }).click();
    const settings = page.getByRole("dialog", { name: "Agent settings", exact: true });
    const projectTools = settings.locator("details.agent-mcp-project-tools");
    await expect(projectTools).toContainText("1 ready");
    await projectTools.locator("summary").click();
    await expect(projectTools.getByText("Synthetic read", { exact: true })).toBeVisible();
    await expect(projectTools.getByText("mcp_99999999_synthetic_read", { exact: true })).toBeVisible();
    await expect(projectTools.getByText("Admitted plans", { exact: true })).toBeVisible();
    await expect(projectTools.getByText("Ready hosts", { exact: true })).toBeVisible();
    await expect(projectTools.getByText("Ready tools", { exact: true })).toBeVisible();
    await expect(projectTools.getByText("Stopped plans", { exact: true })).toBeVisible();
    await fitsViewport(page);

    await projectTools.getByRole("button", { name: "Manage in MCP Store", exact: true }).click();
    await expect(settings).toHaveAttribute("data-settings-tab", "store");
    const store = settings.getByRole("region", { name: "MCP Store", exact: true });
    await store.getByRole("tab", { name: "Managed servers", exact: true }).click();
    const managedRegion = store.getByRole("region", { name: "Managed MCP servers", exact: true });
    await managedRegion.getByRole("button", { name: /Open Synthetic Files managed plan/u }).click();
    const selector = store.getByRole("combobox", { name: "Agent project", exact: true });
    await expect(selector).toHaveValue("1".repeat(32));
    await expect(store.getByText("Editing the active chat project.", { exact: false })).toBeVisible();
    await expect(store.getByRole("button", { name: "Admission already current", exact: true })).toBeDisabled();
    await fitsViewport(page);
  });

  test(`managed MCP calls remain coalesced, keyboard-operable and truthful at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-call");

    const pendingCard = page.getByRole("article", {
      name: "MCP tool call: Read example from Synthetic Files. Waiting for approval",
      exact: true,
    });
    await expect(pendingCard).toHaveCount(1);
    await expect(pendingCard).toContainText("fresh native approval for this call only");
    await expect(page.getByText("mcp_99999999_synthetic_read", { exact: true })).toHaveCount(0);

    const approval = page.getByRole("alertdialog", { name: "Approval needed", exact: true });
    await expect(approval).toBeFocused();
    await expect(approval).toContainText("one external project-tool invocation");
    await expect(approval.getByLabel("Redacted MCP call preview", { exact: true })).toContainText("Arguments: [redacted]");
    await page.keyboard.press("Tab");
    await expect(approval.getByRole("button", { name: "Approve one call", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(approval.getByRole("button", { name: "Deny call", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");

    const deniedCard = page.getByRole("article", {
      name: "MCP tool call: Read example from Synthetic Files. Not approved",
      exact: true,
    });
    await expect(deniedCard).toHaveCount(1);
    await expect(deniedCard).toContainText("Not invoked");
    await expect(deniedCard).toContainText("No invocation effect");
    await expect(approval).toHaveCount(0);
    await fitsViewport(page);

    await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-mcp-call&state=completed");
    const completedCard = page.getByRole("article", {
      name: "MCP tool call: Read example from Synthetic Files. Completed",
      exact: true,
    });
    await expect(completedCard).toHaveCount(1);
    await expect(completedCard).toContainText("Approved once");
    await expect(completedCard).toContainText("External effect not verified");
    await expect(completedCard).toContainText("Cleanup verified");
    await completedCard.getByText("Call details", { exact: true }).click();
    await expect(completedCard).toContainText("Synthetic bounded result; no external MCP server was contacted.");
    await expect(completedCard.getByRole("button", { name: "Copy Read example result", exact: true })).toBeVisible();
    await expect(page.getByText("mcp_99999999_synthetic_read", { exact: true })).toHaveCount(0);
    await fitsViewport(page);
  });
}

test("medium desktop keeps chat in place while Files and Changes use an overlay sheet", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 820 });
  await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell");

  const conversation = page.getByRole("region", { name: "Agent conversation", exact: true });
  const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
  await composer.fill("Synthetic draft remains in the chat while review is open.");
  const before = await conversation.boundingBox();
  const beforeHeight = await page.evaluate(() => document.documentElement.scrollHeight);

  await page.getByRole("button", { name: "Files & review", exact: true }).click();
  const drawer = page.getByRole("complementary", { name: "Files and review drawer", exact: true });
  await expect(drawer).toBeVisible();
  await expect(page.getByRole("tab", { name: "Files", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Files and reviewed changes", exact: true })).toBeVisible();
  await expect(drawer).toHaveCSS("position", "fixed");

  const after = await conversation.boundingBox();
  const afterHeight = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(after?.x).toBe(before?.x);
  expect(after?.y).toBe(before?.y);
  expect(after?.height).toBe(before?.height);
  expect(afterHeight).toBe(beforeHeight);

  const filesTab = page.getByRole("tab", { name: "Files", exact: true });
  await filesTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Changes", exact: true })).toBeFocused();
  await expect(page.getByRole("region", { name: "Reviewed session change set", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
  await expect(drawer).toHaveCount(0);
  await expect(composer).toHaveValue("Synthetic draft remains in the chat while review is open.");
  await expect(composer).toBeFocused();
  await fitsViewport(page);
});

for (const width of [360, 1440]) {
  test.describe(`populated workflows at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("workspace inspection distinguishes incomplete, timeout, recovery and replaced-root states", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=editor-inspection");
      await expect(page.getByText(/No entries could be shown/u)).toBeVisible();
      await expect(page.getByText("This folder is empty.", { exact: true })).toHaveCount(0);
      await expect(page.getByText(/bounded folder view is incomplete/u)).toBeVisible();
      await page.getByRole("button", { name: "Refresh folder", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText("Folder inspection reached its time limit");
      await page.getByRole("button", { name: "Retry folder", exact: true }).click();
      await page.getByRole("button", { name: "example.ts", exact: true }).click();
      const editor = page.getByRole("textbox", { name: "Workspace file editor", exact: true });
      await expect(editor).toHaveValue("export const value = 1;\n");
      await editor.fill("Keep this fictional draft for review.");
      await page.getByRole("button", { name: "Refresh folder", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText("workspace folder was moved or replaced");
      await expect(editor).toHaveValue("Keep this fictional draft for review.");
      await expect(editor).toBeEnabled();
      await expect(editor).toHaveAttribute("readonly", "");
      await expect(page.getByRole("button", { name: "Review diff", exact: true })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Retry folder", exact: true })).toBeDisabled();
      await editor.click();
      await editor.press("ControlOrMeta+A");
      expect(await editor.evaluate((element: HTMLTextAreaElement) => element.selectionEnd - element.selectionStart)).toBe("Keep this fictional draft for review.".length);
      await expect(page.getByText("EXAMPLE_PRIVATE_WORKSPACE_CANARY", { exact: false })).toHaveCount(0);
      await fitsViewport(page);
    });

    for (const windowMode of [false, true]) {
      test(`uncertain command cleanup retains drafts and blocks Agent work in ${windowMode ? "separate" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-command-cleanup${windowMode ? "&window=1" : ""}`);
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await expect(composer).toBeEnabled();
        await composer.fill("Fictional unsent draft that must survive command cleanup.");
        await page.getByRole("button", { name: "Start fictional command", exact: true }).click();
        await page.getByRole("button", { name: "Stop response", exact: true }).click();
        await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
        await expect(page.getByLabel("Agent activity status")).toContainText("Stopping response");
        await page.getByRole("button", { name: "Report example cleanup failure", exact: true }).click();
        await expect(page.getByLabel("Agent activity status")).toContainText("Command cleanup unconfirmed");
        await expect(composer).toHaveValue("Fictional unsent draft that must survive command cleanup.");
        await expect(composer).toHaveAttribute("readonly", "");
        await composer.focus();
        await composer.press("ControlOrMeta+a");
        expect(await composer.evaluate((node: HTMLTextAreaElement) => node.selectionEnd - node.selectionStart)).toBe("Fictional unsent draft that must survive command cleanup.".length);
        await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Retry closing", exact: true })).toHaveCount(0);
        await expect(page.locator('.agent-turn-details[data-termination="failed"]')).toBeVisible();
        await expect(page.getByLabel("Turn 1 details", { exact: true })).toContainText("Incomplete");
        await page.getByLabel("Turn 1 details", { exact: true }).click();
        await expect(page.getByText(/1 command attempt: file effects are not inventoried/)).toBeVisible();
        await fitsViewport(page);
        await page.getByRole("button", { name: "Publish older ready snapshot", exact: true }).click();
        await expect(page.getByText("Older fictional ready snapshot delivered.", { exact: true })).toBeVisible();
        await expect(page.getByLabel("Agent activity status")).toContainText("Command cleanup unconfirmed");
        await expect(page.getByLabel("Agent activity status")).not.toContainText("Ready");
        await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
        await expect(page.getByRole("button", { name: "Stop model", exact: true })).toBeEnabled();
        if (!windowMode) {
          await page.getByRole("button", { name: "New chat", exact: true }).click();
          await expect(page.getByRole("button", { name: "Agent paused for cleanup", exact: true })).toBeDisabled();
          await page.getByRole("button", { name: "Close new chat setup", exact: true }).click();
        }
        await fitsViewport(page);
      });

      test(`uncertain model cleanup pauses automatic updates and leaves Stop usable in ${windowMode ? "separate" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=model-job-status${windowMode ? "&window=1" : ""}`);
        await expect(page.getByText(/Model process cleanup was not confirmed/)).toBeVisible();
        await expect(page.getByText(/restart the app before retrying/)).toBeVisible();
        await expect(page.getByText(/automatic retry \d\d:/i)).toHaveCount(0);
        await expect(page.getByText(/retaining the last valid/i)).toHaveCount(0);
        await expect(page.getByText(/Start one explicit run/)).toHaveCount(0);
        await fitsViewport(page);
        if (windowMode) {
          await page.getByRole("button", { name: "Change", exact: true }).click();
          await page.getByRole("button", { name: "Stop this watch", exact: true }).click();
          await expect(page.getByText("No active watch · model cleanup still unconfirmed", { exact: true })).toBeVisible();
        } else {
          await page.getByRole("button", { name: "Retry analysis", exact: true }).click();
          await expect(page.getByRole("alert")).toContainText("Model process cleanup was not confirmed");
          await page.getByRole("button", { name: "Stop continuous updates", exact: true }).click();
          await expect(page.getByRole("button", { name: "Watch this session", exact: true })).toBeVisible();
        }
        await expect(page.getByText(/Model process cleanup was not confirmed/).first()).toBeVisible();
        await expect(page.getByText(/Start one explicit run/)).toHaveCount(0);
        await fitsViewport(page);
      });
    }

    test("calibration evidence stays readable and changes case identity with the selected window", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=calibration-case");
      await expect(page.getByText(/Case dddddddddddd/)).toBeVisible();
      await expect(page.getByText(/Reviewed-case receipt available/)).toBeVisible();
      await fitsViewport(page);
      await page.getByRole("combobox", { name: "Evidence window" }).selectOption("6000");
      await expect(page.getByText(/Case eeeeeeeeeeee/)).toBeVisible();
      await expect(page.getByText(/Some records or characters are omitted/)).toBeVisible();
      await page.getByRole("button", { name: "Refresh case", exact: true }).click();
      await expect(page.getByText(/Reviewed-case receipt available/)).toBeVisible();
      await fitsViewport(page);
    });

    test("structured model judgments keep historical labels and recover from invalid completions", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=judge-completion");
      await expect(page.getByText("Historical protocol · excluded from agreement", { exact: true })).toHaveCount(3);
      await page.getByRole("button", { name: "Judge again", exact: true }).click();
      await expect(page.getByText(/incomplete or invalid reply.*Existing judgments were kept/)).toBeVisible();
      await expect(page.getByText("high", { exact: true })).toHaveCount(3);
      await fitsViewport(page);
      await page.getByRole("button", { name: "Judge again", exact: true }).click();
      await expect(page.getByText("Judged by example-small-cpu.", { exact: true })).toBeVisible();
      await expect(page.getByText("Historical protocol · excluded from agreement", { exact: true })).toHaveCount(0);
      await expect(page.getByText("judge-v4-complete-json-anchor-15k", { exact: true })).toHaveCount(3);
      await page.getByRole("button", { name: "Explain this session", exact: true }).click();
      await expect(page.getByText("The example request names its target.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Explain this session", exact: true }).click();
      await expect(page.getByText(/incomplete or invalid explanation/)).toBeVisible();
      await expect(page.getByText("The example request names its target.", { exact: true })).toBeVisible();
      await fitsViewport(page);
    });

    test("model chat can send, show reasoning, stop the model and retain the conversation", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=models");
      await expect(page.getByText(/Executable compatibility: supported · live text request verified/)).toBeVisible();
      await expect(page.getByText(/Architecture example-transformer · tokenizer example-bpe · context counter/)).toBeVisible();
      await expect(page.getByRole("heading", { name: "Chat", exact: true })).toBeVisible();
      await page.getByLabel("Message", { exact: true }).fill("Give a synthetic example reply.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByText("Synthetic reply: the example is ready to review.", { exact: true })).toBeVisible();
      await page.getByText("Thinking", { exact: true }).click();
      await expect(page.getByText("Synthetic reasoning: check the example acceptance condition.", { exact: true })).toBeVisible();
      await fitsViewport(page);
      await page.getByRole("button", { name: "Deactivate", exact: true }).click();
      await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
      await expect(page.getByText("Synthetic reply: the example is ready to review.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "New conversation", exact: true }).click();
      await expect(page.getByText("Synthetic reply: the example is ready to review.", { exact: true })).toHaveCount(0);
    });

    test("agent activates the selected model, opens a focused composer, replies and stops the model", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent");
      await page.getByLabel("Workspace folder", { exact: true }).fill("D:/example/project");
      await page.getByLabel("Agent model", { exact: true }).selectOption("example-small-cpu");
      await page.getByText("Model parameters", { exact: true }).click();
      await page.getByRole("checkbox", { name: /Thinking mode/ }).check();
      await page.getByRole("button", { name: "Start model & open read-only chat", exact: true }).click();
      const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
      await expect(composer).toBeFocused();
      await expect(composer).toBeInViewport();
      await composer.fill("Reply about the fictional example only.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByText("Synthetic agent reply: no real files were read or changed.", { exact: true })).toBeVisible();
      await page.getByText("Model reasoning", { exact: true }).click();
      await expect(page.getByText("Synthetic reasoning: inspect the fictional request.", { exact: true })).toBeVisible();
      await fitsViewport(page);
      await page.getByRole("button", { name: "Stop model", exact: true }).click();
      await expect(composer).toBeDisabled();
      await expect(page.getByText("Synthetic agent reply: no real files were read or changed.", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Start session model", exact: true })).toBeEnabled();
    });

    for (const windowMode of [false, true]) {
      test(`agent shell browses durable chats while keeping files and setup subordinate to conversation (${windowMode ? "dedicated" : "main"})`, async ({ page }) => {
      await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-shell${windowMode ? "&window=1" : ""}`);
      const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
      await expect(rail).toContainText("Example coding project");
      await expect(rail).toContainText("Synthetic coding chat");
      await expect(rail).toContainText("Metadata only · history unavailable");

      const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
      await expect(composer).toBeVisible();
      await composer.fill("Synthetic draft retained while reviewing a file.");
      const runtime = page.getByRole("region", { name: "Shared local model runtime", exact: true });
      await expect(runtime.getByText("Ready", { exact: true })).toBeVisible();
      await runtime.getByLabel(/Model and context settings\./u).click();
      const runtimeDialog = runtime.getByRole("dialog", { name: "Choose model and runtime settings", exact: true });
      await expect(runtimeDialog).toBeVisible();
      await runtimeDialog.getByText("Context, compatibility & runtime evidence", { exact: true }).click();
      await expect(runtimeDialog.locator(".agent-runtime__context strong")).toHaveText(
        "612 input / 4,096 · 3,484 available · turn 2",
      );
      const runtimeModel = runtimeDialog.getByRole("combobox", { name: "Model", exact: true });
      await expect(runtimeModel).toBeVisible();
      await expect(runtimeModel).toBeEnabled();
      await runtimeModel.selectOption("example-medium-split");
      await runtimeDialog.getByRole("button", { name: "Switch model", exact: true }).click();
      await expect(runtimeDialog.getByRole("status")).toContainText("This chat is bound to it.");
      await runtimeDialog.getByRole("button", { name: "Close model and context settings", exact: true }).click();
      await expect(composer).toHaveValue("Synthetic draft retained while reviewing a file.");
      await page.getByRole("button", { name: "Files & review", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Files and reviewed changes", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "example.ts", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "Workspace file editor", exact: true })).toHaveValue("Current fictional file content\n");
      await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
      await expect(composer).toHaveValue("Synthetic draft retained while reviewing a file.");

      await page.getByRole("button", { name: "Collapse projects and chats", exact: true }).click();
      await expect(page.getByRole("navigation", { name: "Agent projects and chats (collapsed)", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Expand projects and chats", exact: true }).click();
      await page.getByRole("button", { name: /^Restarted example chat/u }).click();
      const unavailableChat = page.getByRole("article", { name: "Restarted example chat", exact: true });
      await expect(unavailableChat).toContainText("Metadata only · history unavailable");
      await expect(unavailableChat).toContainText("nothing has been reconstructed");
      await expect(composer).toHaveCount(0);

      await page.getByRole("button", { name: /^Synthetic coding chat/u }).click();
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "New chat", exact: true }).click();
      await expect(page.getByRole("heading", { name: "New session", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Close new chat setup", exact: true }).click();
      await expect(page.getByRole("button", { name: "New chat", exact: true })).toBeFocused();
      await fitsViewport(page);
      });
    }

    test("durable controller ownership and handoff remain truthful and usable", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-controller-ownership");
      await page.getByRole("button", { name: /Agent settings/ }).click();
      await page.getByRole("tab", { name: "Connections", exact: true }).click();
      const controller = page.getByRole("region", { name: "Controller API", exact: true });
      const owner = page.getByLabel("External control for Synthetic coding chat", { exact: true });
      const incoming = page.getByLabel("Incoming control handoff for Synthetic coding chat", { exact: true });

      await expect(controller).toContainText("2 active");
      await expect(controller).toContainText("Nineteen project-scoped tools cover the bound project");
      await expect(owner).toContainText("Waiting for native approval");
      await expect(owner).toContainText("Observed cursor7 / 8");
      await expect(owner).toContainText("continue with agent_wait");
      await expect(owner).toContainText("Handoff offered to Synthetic Claude recipient");
      await expect(owner).toContainText("native approval never transfers");
      await expect(owner.getByRole("button", { name: "Release settled control", exact: true })).toBeDisabled();
      await expect(incoming).toContainText("Synthetic Codex orchestrator offered revision 4");
      await expect(incoming).toContainText("Accept it from this exact external client with agent_control");
      await expect(incoming).toContainText("No pending native approval or protected authority transfers");
      await fitsViewport(page);
    });

    test("Agent controller health is private, keyboard reachable and subordinate to chat", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell");
      await expect(page.locator("html")).toHaveAttribute("data-agent-hardening-requests", "0");
      await expect(page.locator("html")).toHaveAttribute("data-agent-acceptance-requests", "0");
      const conversation = page.getByRole("region", { name: "Agent conversation", exact: true });
      const skip = page.getByRole("link", { name: "Skip projects and settings; go to conversation", exact: true });
      await skip.focus();
      await page.keyboard.press("Enter");
      await expect(conversation).toBeFocused();
      const connections = page.getByRole("button", { name: /Agent settings/ });
      await connections.focus();
      await page.keyboard.press("Enter");
      const readiness = page.getByRole("region", { name: "Agent capability readiness", exact: true });
      await expect(page.getByRole("tab", { name: "Readiness", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(readiness).toBeVisible();
      await expect(readiness).toContainText("Loopback integrated");
      await expect(readiness.getByRole("list", { name: "Requested Agent capabilities", exact: true }).getByRole("listitem")).toHaveCount(15);
      await expect(readiness).toContainText("Contract tests, this running loopback app, and owner-only checks are reported separately");
      await page.getByRole("tab", { name: "Connections", exact: true }).click();
      const controller = page.getByRole("region", { name: "Controller API", exact: true });
      await controller.scrollIntoViewIfNeeded();

      await expect(controller).toBeVisible();
      await expect(controller.getByText("Ready", { exact: true })).toBeVisible();
      const controllerFacts = controller.locator(".agent-controller__facts");
      await expect(controllerFacts.getByText("Agent routes", { exact: true }).locator("..")).toContainText("72");
      await expect(controllerFacts.getByText("Runtime routes", { exact: true }).locator("..")).toContainText("5");
      await expect(controllerFacts.getByText("Native review gates", { exact: true }).locator("..")).toContainText("12");
      await expect(controller).toContainText("GET /v1/agent/orchestration");
      await expect(controller).toContainText("still requires you in the native app");
      await expect(page.getByRole("tab", { name: "Connections", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("region", { name: "Team folders", exact: true })).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Guarded native Agent acceptance", exact: true })).toHaveCount(0);
      await expect(controller).toContainText("Direct app connections");
      await expect(controller).toContainText("1 active");
      await expect(controller).toContainText("Synthetic Codex orchestrator");
      await expect(controller).toContainText("Last MCP request");
      await expect(controller.locator(".agent-mcp-connections__tool-activity")).toContainText("agent_open");
      await expect(controller.locator(".agent-mcp-connections__tool-activity")).toContainText("succeeded");
      await expect(controller.locator(".agent-mcp-connections__tool-activity")).toContainText("external MCP client");
      await expect(controller).toContainText("No exact inactive-credential rejection recorded");
      await expect(controller).toContainText("starts no terminal, subprocess, model, or agent");
      await expect(controller).toContainText("Nineteen project-scoped tools cover the bound project");
      await expect(controller).toContainText("Project scope Example coding project");
      await expect(controller).toContainText("Native approvals never inherited");
      await expect(controller).toContainText("Live-close retains the durable chat");
      await expect(controller).toContainText("POST /mcp/agent");
      const setupPreview = controller.getByRole("region", { name: "Exact client setup", exact: true });
      await expect(setupPreview).toBeVisible();
      await expect(setupPreview).toContainText("Disconnected · no credential");
      await expect(setupPreview).toContainText("http://127.0.0.1:4173/mcp/agent");
      await expect(setupPreview).toContainText("No process or terminal");
      await expect(setupPreview).not.toContainText("pemcp1.");
      await expect(setupPreview).not.toContainText("pemcp2.");
      await expect(setupPreview.getByRole("button", { name: "Copy preview install command", exact: true })).toBeVisible();
      await setupPreview.getByRole("button", { name: "Claude Code", exact: true }).click();
      await expect(setupPreview).toContainText("claude mcp add --transport http");
      const previewConfig = setupPreview.locator("details.agent-mcp-connections__preview-config > summary");
      await previewConfig.focus();
      await page.keyboard.press("Enter");
      await expect(setupPreview).toContainText("Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}");
      await setupPreview.getByRole("button", { name: "Codex", exact: true }).click();
      const delegationQuickstart = controller.locator("details.agent-mcp-connections__quickstart > summary");
      await delegationQuickstart.focus();
      await page.keyboard.press("Enter");
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText(
        "agent_discover → agent_open → agent_context",
      );
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText("Delegate with agent_turn");
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText("agent_propose_transaction");
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText("agent_propose_lifecycle");
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText(
        "verified file move advances a matching card under the same identity",
      );
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText(
        "Directory moves do not yet advance artifact cards",
      );
      await expect(controller.locator(".agent-mcp-connections__quickstart")).toContainText(
        "last-request timestamp proves",
      );
      await expect(controller.getByRole("button", { name: "Copy orchestration starter", exact: true })).toBeVisible();
      await controller.getByRole("button", { name: "Begin external lifecycle proof", exact: true }).click();
      const externalProof = controller.getByRole("region", { name: /External controller lifecycle/u });
      await expect(externalProof).toBeVisible();
      await expect(externalProof).toContainText("Release acceptance · page-owned, never automatic");
      await expect(externalProof).toContainText("call only agent_discover");
      await expect(externalProof).toContainText("local self-test does not count");
      await expect(externalProof).toContainText("Reconnect without resubmission");
      await expect(externalProof).toContainText("Revision-bound two-party handoff");
      await expect(externalProof.getByRole("listitem")).toHaveCount(10);
      await fitsViewport(page);
      const connectedTools = controller.locator("details.agent-mcp-connections__capabilities > summary");
      await connectedTools.focus();
      await page.keyboard.press("Enter");
      await expect(controller.locator(".agent-mcp-connections__capabilities")).toContainText("agent_export");
      await expect(controller.locator(".agent-mcp-connections__capabilities")).toContainText("agent_close");
      await expect(controller.locator(".agent-mcp-connections__capabilities")).toContainText("agent_stop");
      await expect(controller.locator(".agent-mcp-connections__capabilities")).toContainText("agent_control");
      await expect(controller).toContainText("prompt-enhancer agent-mcp-config");
      await expect(controller).toContainText("prompt-enhancer agent-mcp-config --transport stdio");
      await expect(controller).toContainText("prompt-enhancer agent-mcp-config --transport stdio --with-model-lifecycle");
      const advanced = controller.locator("details.agent-controller__advanced > summary");
      await expect(advanced).toHaveAccessibleName("Advanced: templates, stdio fallback, and scripts");
      await advanced.focus();
      await page.keyboard.press("Enter");
      await expect(controller).toContainText("prompt-enhancer agent-controller-config");
      await expect(controller).toContainText("prompt-enhancer agent-controller discover");
      await expect(controller).toContainText("prompt-enhancer agent-controller invoke");
      await expect(controller).toContainText("prompt-enhancer agent-controller open");
      await expect(controller).toContainText("prompt-enhancer agent-controller runtime");
      await expect(controller).toContainText("prompt-enhancer agent-controller turn");
      await expect(controller).toContainText("prompt-enhancer agent-controller wait");
      await expect(controller).toContainText("prompt-enhancer agent-controller close");
      await expect(controller).toContainText("local-agent-orchestration.v22");
      await expect(controller).toContainText("task authorization and a completed redaction preview");
      await expect(controller).toContainText("never retried after ambiguity");
      await expect(controller).toContainText("runtime and live-close mutate at most once");
      await expect(controller).toContainText("close retains the durable chat");
      await expect(controller).toContainText("starts no bridge process");
      await expect(controller).toContainText("Private connection values appear only");
      await expect(page.locator("html")).toHaveAttribute("data-agent-hardening-requests", "0");
      const health = controller.getByRole("region", { name: "Projects & chats health", exact: true });
      await expect(health).toHaveAttribute("aria-busy", "false");
      await expect(health.getByText("Project and chat health has not been checked.", { exact: true })).toBeAttached();
      const runHealth = health.locator(":scope > .agent-controller__health-check");
      await expect(runHealth).toHaveAccessibleName("Run health check");
      await runHealth.focus();
      await page.keyboard.press("Enter");
      await expect(page.locator("html")).toHaveAttribute("data-agent-hardening-requests", "1");
      await expect(health.getByText("Review needed", { exact: true })).toBeVisible();
      await expect(health).toContainText("Saved histories");
      await expect(health).toContainText("Interrupted");
      await expect(health.getByRole("region", { name: "Next safe actions", exact: true })).toContainText(
        "Interrupted chats can be resumed read-only.",
      );
      await expect(health.getByRole("status")).toContainText(
        "Project and chat health check complete: Review needed. 2 safe actions reported.",
      );
      await page.getByRole("tab", { name: "Owner checks", exact: true }).click();
      const ownerAcceptance = page.getByRole("region", { name: "Guarded native Agent acceptance", exact: true });
      await expect(ownerAcceptance).toBeVisible();
      await expect(ownerAcceptance.getByRole("button", { name: "Native confirmation required", exact: true })).toBeDisabled();
      await expect(page.locator("html")).toHaveAttribute("data-agent-acceptance-requests", "0");
      await page.getByRole("tab", { name: "Team folders", exact: true }).click();
      await expect(page.getByRole("region", { name: "Team folders", exact: true })).toBeVisible();
      await page.getByRole("tab", { name: "Connections", exact: true }).click();
      await expect(controller).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeVisible();
      await fitsViewport(page);

      if (width === 360) {
        await page.setViewportSize({ width: 320, height: 900 });
        await health.scrollIntoViewIfNeeded();
        await fitsViewport(page);
        await controller.getByRole("button", { name: "Restart lifecycle proof", exact: true }).click();
        const narrowExternalProof = controller.getByRole("region", { name: /External controller lifecycle/u });
        await expect(narrowExternalProof).toBeVisible();
        await fitsViewport(page);
        const touchTargets = [
          ["Agent settings", connections],
          ["Connections tab", page.getByRole("tab", { name: "Connections", exact: true })],
          ["Copy orchestration starter", controller.getByRole("button", { name: "Copy orchestration starter", exact: true })],
          ["Copy preview install command", setupPreview.getByRole("button", { name: "Copy preview install command", exact: true })],
          ["Refresh connection status", controller.getByRole("button", { name: "Refresh connection status", exact: true })],
          ["Refresh proof evidence", narrowExternalProof.getByRole("button", { name: "Refresh proof evidence", exact: true })],
          ["Clear page-only receipt", narrowExternalProof.getByRole("button", { name: "Clear page-only receipt", exact: true })],
          ["Run health check", runHealth],
          ["Files & review", page.getByRole("button", { name: "Files & review", exact: true })],
          ["Send", page.getByRole("button", { name: "Send", exact: true })],
        ] as const;
        for (const [name, target] of touchTargets) {
          expect(
            await target.evaluate((element) => element.getBoundingClientRect().height),
            `${name} must remain at least 44px tall`,
          ).toBeGreaterThanOrEqual(44);
        }
        const settingsTabHeights = await page.getByRole("tab").evaluateAll(
          (elements) => elements.map((element) => element.getBoundingClientRect().height),
        );
        expect(settingsTabHeights).toHaveLength(5);
        for (const height of settingsTabHeights) expect(height).toBeGreaterThanOrEqual(44);
        await page.getByRole("tab", { name: "Readiness", exact: true }).click();
        await expect(readiness).toBeVisible();
        await fitsViewport(page);
        await expect(readiness.getByRole("button", { name: "Open connections", exact: true })).toBeVisible();
        await expect(readiness.getByRole("button", { name: "Open owner checks", exact: true })).toBeVisible();
        await page.getByRole("tab", { name: "Connections", exact: true }).click();
        await expect(controller).toBeVisible();
      }

      await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
      await runHealth.focus();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      const focusRing = await runHealth.evaluate((element) => {
        const style = getComputedStyle(element);
        return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
      });
      expect(focusRing.style).not.toBe("none");
      expect(focusRing.width).toBeGreaterThanOrEqual(2);
    });

    test("verified Agent composer stages documents and media, then sends by identity without text", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell&multimodal=1");
      const attachments = page.getByRole("region", { name: "Message attachments", exact: true });
      const attach = attachments.getByRole("button", { name: "Attach", exact: true });
      await expect(attach).toBeEnabled();
      await expect(attachments.getByRole("button", { name: "Add image", exact: true })).toHaveCount(0);
      await attach.click();
      await expect(attachments.getByRole("button", { name: "Add image", exact: true })).toBeEnabled();
      await expect(attachments.getByRole("button", { name: "Add audio", exact: true })).toBeEnabled();
      await expect(attachments.getByRole("button", { name: "Add document", exact: true })).toBeEnabled();
      await expect(attachments).toContainText("Audio input is experimental in llama.cpp");
      for (const control of [
        attach,
        attachments.getByRole("button", { name: "Refresh staged", exact: true }),
        attachments.getByRole("button", { name: "Add image", exact: true }),
        attachments.getByRole("button", { name: "Add audio", exact: true }),
        attachments.getByRole("button", { name: "Add document", exact: true }),
      ]) {
        expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }

      await page.getByLabel("Choose WAV audio", { exact: true }).setInputFiles({
        name: "synthetic-audio.wav",
        mimeType: "audio/wav",
        buffer: Buffer.from("RIFFsynthetic-WAVEfmt synthetic-data", "utf8"),
      });
      await expect(attachments).toContainText("synthetic-audio.wav");
      await attachments.getByRole("button", { name: "Remove synthetic-audio.wav", exact: true }).click();
      await expect(attachments).not.toContainText("synthetic-audio.wav");

      await page.getByLabel("Choose documents", { exact: true }).setInputFiles({
        name: "synthetic.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.7 synthetic", "utf8"),
      });
      await expect(attachments.getByRole("alert")).toContainText("PDF input is intentionally unavailable");
      await page.getByLabel("Choose documents", { exact: true }).setInputFiles({
        name: "synthetic-notes.md",
        mimeType: "text/markdown",
        buffer: Buffer.from("# Synthetic notes\n\nLocal projection only.", "utf8"),
      });
      await expect(attachments).toContainText("synthetic-notes.md");
      const documentPreview = attachments.getByText("Extracted preview", { exact: true });
      await expect(documentPreview).toBeVisible();
      await documentPreview.click();
      await expect(attachments).toContainText("Local projection only.");
      await attachments.getByRole("button", { name: "Remove synthetic-notes.md", exact: true }).click();
      await expect(attachments).not.toContainText("synthetic-notes.md");

      await page.getByLabel("Choose images", { exact: true }).setInputFiles({
        name: "synthetic-pixel.png",
        mimeType: "image/png",
        buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"),
      });
      await expect(attachments).toContainText("synthetic-pixel.png");
      await expect(page.getByRole("img", { name: "Preview synthetic-pixel.png", exact: true })).toBeVisible();

      const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
      await expect(composer).toHaveValue("");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByRole("list", { name: "Message attachments", exact: true })).toContainText("synthetic-pixel.png");
      await expect(attachments).toContainText("0/4");
      await expect(composer).toHaveValue("");
      await fitsViewport(page);
    });

    test("saved Agent history reopens after restart and resumes with protected actions off", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-history");
      const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
      await expect(rail).toContainText("Saved restart chat");
      await expect(rail).toContainText("1 turn · saved locally");
      const railBounds = await rail.boundingBox();
      await page.getByRole("button", { name: "New chat", exact: true }).click();
      const setup = page.getByRole("dialog", { name: "New session", exact: true });
      const setupPosition = await setup.evaluate((element) => getComputedStyle(element).position);
      expect(railBounds, "The projects and chats rail must have a rendered box").not.toBeNull();
      expect(setupPosition, "New chat setup must be an overlay that cannot stretch the project rail").toBe("fixed");
      await page.getByRole("button", { name: "Close new chat setup", exact: true }).click();
      await page.getByRole("button", { name: /^Saved restart chat/u }).click();
      await expect(setup).toHaveCount(0);
      const railBoundsAfterClose = await rail.boundingBox();
      expect(railBoundsAfterClose?.height).toBeCloseTo(railBounds!.height, 0);

      const retained = page.getByRole("article", { name: "Saved restart chat", exact: true });
      await expect(retained).toContainText("Saved locally · 1 turn");
      await expect(retained).toContainText("Explain the retained synthetic module.");
      await expect(retained).toContainText("The retained synthetic module is ready to reopen after restart.");
      await expect(retained).toContainText("Approval IDs, approval decisions, raw tool arguments/output");
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toHaveCount(0);

      const artifacts = retained.getByRole("region", { name: /Artifacts/u });
      await expect(artifacts).toContainText("reviewed-example.md");
      await expect(artifacts).toContainText("Reviewed write · event 2");
      expect(
        await artifacts.evaluate((node) => node.parentElement?.lastElementChild === node),
        "Verified outputs should follow the retained transcript instead of appearing above it",
      ).toBe(true);
      const producingTurn = retained.getByLabel("Turn 1 details", { exact: true }).locator("..");
      await expect(producingTurn).not.toHaveAttribute("open", "");
      await artifacts.getByRole("button", {
        name: "Go to producing turn for reviewed-example.md",
        exact: true,
      }).click();
      await expect(producingTurn).toHaveAttribute("open", "");
      await expect(producingTurn).toBeFocused();
      const viewArtifact = artifacts.getByRole("button", { name: "Preview reviewed-example.md", exact: true });
      await viewArtifact.click();
      const artifactViewer = page.getByRole("dialog", { name: "reviewed-example.md", exact: true });
      await expect(artifactViewer.getByRole("heading", { name: "Reviewed synthetic artifact", exact: true })).toBeVisible();
      await expect(artifactViewer).toContainText("No real workspace content.");
      const version = artifactViewer.getByLabel("Artifact version", { exact: true });
      await expect(version).toHaveValue("4".repeat(32));
      await expect(artifactViewer).toContainText("v2 of 2");
      await artifactViewer.getByRole("button", { name: "Compare versions", exact: true }).click();
      const comparison = artifactViewer.getByRole("region", {
        name: "Artifact version metadata comparison",
        exact: true,
      });
      await expect(comparison).toContainText("v1 → v2");
      await expect(comparison).toContainText("Digest changed");
      await expect(comparison).toContainText("Metadata comparison only");
      await expect(artifactViewer.getByLabel("Comparison artifact version", { exact: true }))
        .toHaveValue("7".repeat(32));
      await artifactViewer.getByRole("button", { name: "Source", exact: true }).click();
      await expect(artifactViewer.getByLabel("Markdown source", { exact: true })).toContainText("# Reviewed synthetic artifact");
      await artifactViewer.getByRole("button", { name: "Preview", exact: true }).click();
      await version.selectOption("7".repeat(32));
      await expect(artifactViewer.getByLabel("Comparison artifact version", { exact: true }))
        .toHaveValue("4".repeat(32));
      await expect(artifactViewer.getByRole("alert")).toContainText("current workspace bytes do not match recorded v1");
      await expect(artifactViewer.getByRole("button", { name: "Download v1", exact: true })).toBeDisabled();
      await expect(artifactViewer.getByRole("button", { name: "Open current file", exact: true })).toHaveCount(0);
      await version.selectOption("4".repeat(32));
      await expect(artifactViewer.getByRole("heading", { name: "Reviewed synthetic artifact", exact: true })).toBeVisible();
      await expect(artifactViewer.getByRole("button", { name: "Download v2", exact: true })).toBeEnabled();
      await page.keyboard.press("Escape");
      await expect(artifactViewer).toHaveCount(0);
      await expect(viewArtifact).toBeFocused();

      await page.getByRole("button", { name: "Resume chat", exact: true }).click();
      const recovery = page.getByRole("heading", { name: "Revalidate this workspace before changing it", exact: true });
      await expect(recovery).toBeVisible();
      await expect(page.getByText("Recovered · protected actions off", { exact: true })).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeVisible();
      await page.getByRole("checkbox", { name: "File writes", exact: true }).check();
      await page.getByRole("button", { name: "Confirm and revalidate", exact: true }).click();
      await expect(recovery).toHaveCount(0);
      await page.getByText("Chat details", { exact: true }).click();
      await expect(page.getByText(/saved locally · recovered · writes · no commands · no web/u)).toBeVisible();
      await fitsViewport(page);
    });

    test("generated output review is revision-bound, touchable, responsive, and produces an artifact card", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=artifact-capture");
      const workspace = page.getByRole("region", { name: "Files and reviewed changes", exact: true });
      const generatedFile = workspace.getByRole("button", {
        name: /synthetic-generated\.pdf — add as generated output/u,
      });
      await expect(generatedFile).toBeVisible();
      await generatedFile.click();

      const reviewDialog = page.getByRole("dialog", { name: "Add generated output", exact: true });
      await expect(reviewDialog).toBeVisible();
      await expect(reviewDialog.getByLabel("Workspace-relative file path", { exact: true }))
        .toHaveValue("reports/synthetic-generated.pdf");
      const dialogBounds = await reviewDialog.boundingBox();
      expect(dialogBounds).not.toBeNull();
      expect(dialogBounds!.x).toBeGreaterThanOrEqual(0);
      expect(dialogBounds!.x + dialogBounds!.width).toBeLessThanOrEqual(width + 1);

      const reviewOutput = reviewDialog.getByRole("button", { name: "Review output", exact: true });
      expect((await reviewOutput.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await reviewOutput.click();
      const exactReview = reviewDialog.getByRole("region", { name: "Generated output review", exact: true });
      await expect(exactReview).toContainText("Local PDF viewer");
      await expect(exactReview).toContainText("No file bytes are included in this review");
      await expect(exactReview).toContainText("1".repeat(12));

      const addOutput = reviewDialog.getByRole("button", { name: "Add verified output", exact: true });
      expect((await addOutput.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await addOutput.click();
      await expect(reviewDialog).toHaveCount(0);

      const artifacts = page.getByRole("region", { name: /Artifacts · 1/u });
      await expect(artifacts).toContainText("Synthetic generated report");
      await expect(artifacts).toContainText("Native capture");
      for (const control of [
        artifacts.getByRole("button", { name: "Refresh", exact: true }),
        artifacts.getByRole("button", { name: "Preview Synthetic generated report", exact: true }),
      ]) {
        expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }
      await expect(page.getByText(/is now available as a verified chat artifact/u)).toBeVisible();
      await fitsViewport(page);
    });

    test("artifact lifecycle is browseable, reversible, revisioned, and touchable", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=artifact-lifecycle");
      const artifacts = page.getByRole("region", { name: "Artifacts · 1", exact: true });
      await expect(artifacts.getByRole("tab", { name: "Active 1", exact: true })).toHaveAttribute("aria-selected", "true");
      for (const control of [
        artifacts.getByRole("tab", { name: "Active 1", exact: true }),
        artifacts.getByRole("tab", { name: "Archived 0", exact: true }),
        artifacts.getByRole("button", { name: "Manage Synthetic lifecycle note", exact: true }),
      ]) {
        expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }

      await artifacts.getByRole("button", { name: "Manage Synthetic lifecycle note", exact: true }).click();
      let dialog = page.getByRole("dialog", { name: "Manage Synthetic lifecycle note", exact: true });
      const displayName = dialog.getByLabel("Display name", { exact: true });
      await expect(displayName).toBeFocused();
      await displayName.fill("Reviewed lifecycle note");
      await dialog.getByRole("button", { name: "Save display name", exact: true }).click();
      await expect(page.getByText(/workspace path and version lineage were not changed/u)).toBeVisible();
      await expect(artifacts.getByText("Reviewed lifecycle note", { exact: true })).toBeVisible();

      await artifacts.getByRole("button", { name: "Manage Reviewed lifecycle note", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Manage Reviewed lifecycle note", exact: true });
      await expect(dialog).toContainText("Revision 2 · 1 immutable version");
      await dialog.getByRole("button", { name: "Archive record", exact: true }).click();
      await expect(page.getByText(/Moved to Archived.*workspace file.*kept/u)).toBeVisible();
      await expect(artifacts.getByRole("tab", { name: "Active 0", exact: true })).toBeVisible();
      await expect(artifacts.getByRole("tab", { name: "Archived 1", exact: true })).toBeVisible();

      await artifacts.getByRole("tab", { name: "Archived 1", exact: true }).click();
      await artifacts.getByRole("button", { name: "Manage Reviewed lifecycle note", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Manage Reviewed lifecycle note", exact: true });
      await expect(dialog.getByText(/separate native confirmation/u)).toBeVisible();
      const remove = dialog.getByRole("button", { name: "Move record to Removed", exact: true });
      expect((await remove.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      await remove.click();
      await expect(page.getByText(/record is recoverable and no workspace file was deleted/u)).toBeVisible();
      await expect(artifacts.getByRole("tab", { name: "Removed 1", exact: true })).toBeVisible();

      await artifacts.getByRole("tab", { name: "Removed 1", exact: true }).click();
      await expect(artifacts.getByRole("button", { name: "Preview Reviewed lifecycle note", exact: true })).toHaveCount(0);
      await artifacts.getByRole("button", { name: "Manage Reviewed lifecycle note", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Manage Reviewed lifecycle note", exact: true });
      await dialog.getByRole("button", { name: "Recover to Archived", exact: true }).click();
      await expect(page.getByText(/Recovered to Archived/u)).toBeVisible();

      await artifacts.getByRole("tab", { name: "Archived 1", exact: true }).click();
      await artifacts.getByRole("button", { name: "Manage Reviewed lifecycle note", exact: true }).click();
      dialog = page.getByRole("dialog", { name: "Manage Reviewed lifecycle note", exact: true });
      await dialog.getByRole("button", { name: "Restore to Active", exact: true }).click();
      await expect(page.getByText("Restored to Active.", { exact: true })).toBeVisible();
      await expect(artifacts.getByRole("tab", { name: "Active 1", exact: true })).toBeVisible();
      await fitsViewport(page);
    });

    test("artifact image, PDF and Office viewers stay inert, bounded, and release local URLs", async ({ page }) => {
      const externalRequests: string[] = [];
      page.on("request", (request) => {
        const target = new URL(request.url());
        if (["blob:", "data:"].includes(target.protocol)) return;
        if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(target.hostname)) {
          externalRequests.push(request.url());
        }
      });
      await page.addInitScript(() => {
        const trackedWindow = window as Window & {
          __syntheticCreatedArtifactUrls: string[];
          __syntheticRevokedArtifactUrls: string[];
        };
        trackedWindow.__syntheticCreatedArtifactUrls = [];
        trackedWindow.__syntheticRevokedArtifactUrls = [];
        const create = URL.createObjectURL.bind(URL);
        const revoke = URL.revokeObjectURL.bind(URL);
        URL.createObjectURL = (object: Blob | MediaSource) => {
          const url = create(object);
          trackedWindow.__syntheticCreatedArtifactUrls.push(url);
          return url;
        };
        URL.revokeObjectURL = (url: string) => {
          trackedWindow.__syntheticRevokedArtifactUrls.push(url);
          revoke(url);
        };
      });
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=artifact-viewers");
      const imageView = page.getByRole("button", { name: "Preview synthetic-preview.png", exact: true });
      const pdfView = page.getByRole("button", { name: "Preview synthetic-report.pdf", exact: true });
      const documentView = page.getByRole("button", { name: "Preview synthetic-budget.xlsx", exact: true });
      await expect(imageView).toBeVisible();
      await expect(pdfView).toBeVisible();
      await expect(documentView).toBeVisible();

      await imageView.click();
      const imageDialog = page.getByRole("dialog", { name: "synthetic-preview.png", exact: true });
      const imageRegion = imageDialog.getByRole("region", { name: "Image preview of synthetic-preview.png v1", exact: true });
      await expect(imageRegion).toHaveAttribute("data-state", "ready");
      for (const control of [
        imageDialog.getByRole("button", { name: "Close artifact viewer", exact: true }),
        imageDialog.getByRole("button", { name: "Zoom in image", exact: true }),
      ]) {
        expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }
      await imageDialog.getByRole("button", { name: "Zoom in image", exact: true }).click();
      await expect(imageDialog.getByRole("button", { name: "Fit image to viewer", exact: true })).toContainText("125%");
      const imageBounds = await imageDialog.boundingBox();
      expect(imageBounds).not.toBeNull();
      expect(imageBounds!.x).toBeGreaterThanOrEqual(0);
      expect(imageBounds!.x + imageBounds!.width).toBeLessThanOrEqual(width + 1);
      await page.keyboard.press("Escape");
      await expect(imageDialog).toHaveCount(0);
      await expect(imageView).toBeFocused();
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticRevokedArtifactUrls: string[] }
      ).__syntheticRevokedArtifactUrls.length)).toBe(1);
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticCreatedArtifactUrls: string[] }
      ).__syntheticCreatedArtifactUrls.length)).toBe(1);

      await pdfView.click();
      const pdfDialog = page.getByRole("dialog", { name: "synthetic-report.pdf", exact: true });
      const pdfRegion = pdfDialog.getByRole("region", { name: "PDF preview of synthetic-report.pdf v1", exact: true });
      await expect(pdfRegion).toHaveAttribute("data-state", "ready");
      await expect(pdfDialog.locator("iframe")).toHaveCount(0);
      await expect(pdfDialog.getByRole("img", { name: "Rendered PDF page 1 of 1", exact: true })).toBeVisible();
      await expect(pdfDialog.getByText(/Links, forms, scripts, audio, and annotations are not interactive/u)).toBeVisible();
      await pdfDialog.getByRole("button", { name: "Zoom in PDF", exact: true }).click();
      await expect(pdfDialog.getByRole("button", { name: "Fit PDF page to viewer", exact: true })).toContainText("125%");
      await page.keyboard.press("Escape");
      await expect(pdfDialog).toHaveCount(0);
      await expect(pdfView).toBeFocused();
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticRevokedArtifactUrls: string[] }
      ).__syntheticRevokedArtifactUrls.length)).toBe(1);
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticCreatedArtifactUrls: string[] }
      ).__syntheticCreatedArtifactUrls.length)).toBe(1);

      await documentView.click();
      const documentDialog = page.getByRole("dialog", { name: "synthetic-budget.xlsx", exact: true });
      const documentRegion = documentDialog.getByRole("region", {
        name: "Excel workbook preview of synthetic-budget.xlsx v1",
        exact: true,
      });
      await expect(documentRegion).toBeVisible();
      await expect(documentDialog.getByText("Metric", { exact: true })).toBeVisible();
      await documentDialog.getByRole("button", { name: /Budget/u }).click();
      await expect(documentDialog.getByRole("table", { name: "Budget table projection", exact: true }))
        .toContainText("Fictional total");
      await expect(documentDialog.getByText(/Not rendered: external links, macros/u)).toBeVisible();
      await expect(documentDialog.getByText(/bounded preview is truncated/u)).toBeVisible();
      await expect(documentDialog.locator("iframe, script, a[href]")).toHaveCount(0);
      const [lineageDownload] = await Promise.all([
        page.waitForEvent("download"),
        documentDialog.getByRole("button", { name: "Export lineage v1", exact: true }).click(),
      ]);
      expect(lineageDownload.suggestedFilename()).toBe("agent-artifact-eeeeeeee-v1-lineage.json");
      const lineagePath = await lineageDownload.path();
      expect(lineagePath).not.toBeNull();
      const lineage = JSON.parse(await readFile(lineagePath!, "utf8")) as Record<string, unknown>;
      expect(lineage).toMatchObject({
        contract_version: "agent-artifact-export.v1",
        content_included: false,
        absolute_path_included: false,
        sensitivity: "sensitive_local_metadata",
      });
      expect(JSON.stringify(lineage)).not.toMatch(/[A-Za-z]:\\/u);
      await expect(documentDialog.getByText(
        /no artifact bytes or absolute workspace path/u,
      )).toBeVisible();
      const documentBounds = await documentDialog.boundingBox();
      expect(documentBounds).not.toBeNull();
      expect(documentBounds!.x).toBeGreaterThanOrEqual(0);
      expect(documentBounds!.x + documentBounds!.width).toBeLessThanOrEqual(width + 1);
      await page.keyboard.press("Escape");
      await expect(documentDialog).toHaveCount(0);
      await expect(documentView).toBeFocused();
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticCreatedArtifactUrls: string[] }
      ).__syntheticCreatedArtifactUrls.length)).toBe(2);
      await expect.poll(() => page.evaluate(() => (
        window as Window & { __syntheticRevokedArtifactUrls: string[] }
      ).__syntheticRevokedArtifactUrls.length)).toBe(2);
      expect(externalRequests).toEqual([]);
      await fitsViewport(page);
    });

    test("saved Agent history branches at a settled turn without restoring authority", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-history");
      const rail = page.getByRole("navigation", { name: "Agent projects and chats", exact: true });
      await expect(page.getByRole("dialog", { name: "New session", exact: true })).toHaveCount(0);
      const source = page.getByRole("article", { name: "Saved restart chat", exact: true });
      await expect(source.getByLabel("Branch point", { exact: true })).toHaveValue("latest");
      const fork = source.getByRole("button", { name: "Fork chat", exact: true });
      await expect(fork).toBeEnabled();
      await fork.click();

      const branch = page.getByRole("article", {
        name: "Saved restart chat (branch)",
        exact: true,
      });
      await expect(branch).toContainText("Branch · 1 copied turn");
      await expect(branch).toContainText("The retained synthetic module is ready to reopen after restart.");
      await expect(branch).toContainText("Protected authority is never copied.");
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toHaveCount(0);
      await expect(rail).toContainText("Saved restart chat (branch)");
      await expect(rail).toContainText("2 chats");
      await fitsViewport(page);
    });

    test("model chat marks token-limited output incomplete and preserves a draft through retry", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=models-completion");
      const composer = page.getByRole("textbox", { name: "Message", exact: true });
      await composer.fill("Give a bounded synthetic reply.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText("response token limit");
      await expect(page.locator('[data-response-status="incomplete"]')).toContainText("Synthetic unfinished reply.");
      await composer.fill("Fictional next draft.");
      await fitsViewport(page);
      await page.getByRole("button", { name: "Retry last message", exact: true }).click();
      await expect(page.locator('[data-response-status="complete"]')).toContainText("Synthetic reply: the example is ready to review.");
      await expect(composer).toHaveValue("Fictional next draft.");
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Retry last message", exact: true })).toHaveCount(0);
      await fitsViewport(page);
    });

    for (const windowMode of [false, true]) {
      test(`pre-response Stop waits truthfully then recovers in ${windowMode ? "dedicated" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-stopping${windowMode ? "&window=1" : ""}`);
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await composer.fill("Fictional request with delayed response headers.");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        await page.getByRole("button", { name: "Stop response", exact: true }).click();
        await expect(page.getByRole("button", { name: "Stopping…", exact: true })).toBeDisabled();
        await expect(page.getByLabel("Agent activity status")).toContainText("Stopping response");
        await expect(page.getByLabel("Agent activity status")).toContainText("model stays loaded");
        await expect(page.getByText(/running · stopping current response/)).toBeVisible();
        await expect(composer).toBeEnabled();
        await expect(composer).toHaveAttribute("placeholder", "Keep writing the next message while this response stops…");
        await composer.fill("Fictional next request drafted while stopping.");
        await fitsViewport(page);
        await page.getByRole("button", { name: "Finish cancelled example request", exact: true }).click();
        await expect(composer).toBeEnabled();
        await expect(composer).toHaveValue("Fictional next request drafted while stopping.");
        await expect(page.getByLabel("Turn 2 details", { exact: true })).toContainText("Stopped");
        await expect(page.getByLabel("Turn 2 details", { exact: true })).toContainText("Usage not reported");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        await expect(page.getByText("Synthetic agent reply: no real files were read or changed.", { exact: true })).toBeVisible();
        await expect(composer).toBeEnabled();
        await fitsViewport(page);
      });

      test(`turn receipts expose reported usage and safe file links in ${windowMode ? "dedicated" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-turn${windowMode ? "&window=1" : ""}`);
        await page.getByRole("button", { name: "Files & review", exact: true }).click();
        await page.getByRole("tab", { name: "Changes", exact: true }).click();
        const changeSet = page.getByRole("region", { name: "Reviewed session change set", exact: true });
        await expect(changeSet).toContainText("Partial reviewed-path coverage");
        await expect(changeSet).toContainText("1 current change");
        await expect(changeSet).toContainText("1 path needs attention");
        await expect(changeSet).toContainText("approved command attempt may have uninventoried file effects");
        await expect(changeSet).toContainText("write publication remains unverified");
        const verifiedChange = changeSet.locator(".agent-change-set__files > li").filter({ hasText: "Modified" });
        await verifiedChange.getByRole("button", { name: "Review net diff", exact: true }).click();
        await expect(page.getByRole("region", { name: "Net diff for example.ts", exact: true })).toContainText("Current fictional file content");
        await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
        const effects = page.getByLabel("Session activity and write receipts", { exact: true });
        await expect(effects).toContainText("3 observed actions");
        await expect(effects).toContainText("2 reviewed writes");
        await expect(effects).toContainText("2 reviewed paths");
        await expect(effects).toContainText("1 unverified write");
        await effects.click();
        await expect(page.getByText("Complete retained session history", { exact: true }).last()).toBeVisible();
        await expect(page.getByText(/command attempt may have file effects that are not inventoried/u)).toBeVisible();
        await expect(page.locator(".agent-session-effects").getByText(/historical activity, not current file state/u)).toBeVisible();
        const details = page.getByLabel("Turn 1 details", { exact: true });
        await expect(details).toContainText("18 reported tokens");
        await details.click();
        await expect(page.getByText(/not verification that the task succeeded/)).toBeVisible();
        await expect(page.getByLabel("Turn telemetry")).toContainText("Input tokens11");
        await expect(page.getByText("1 command attempt: file effects are not inventoried.", { exact: true })).toBeVisible();
        await expect(page.locator(".agent-turn-details").getByText("Effect unverified", { exact: true })).toBeVisible();
        await page.getByText("Verified revision", { exact: true }).click();
        await fitsViewport(page);
        await page.getByRole("button", { name: "Open example.ts in workspace", exact: true }).click();
        const editor = page.getByRole("textbox", { name: "Workspace file editor", exact: true });
        await expect(editor).toHaveValue("Current fictional file content\n");
        await expect(editor).toBeFocused();
        await expect(editor).toBeInViewport();
        await fitsViewport(page);
        await editor.fill("Fictional unsaved draft");
        await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
        const discardDialog = page.getByRole("dialog", { name: "Discard workspace changes?", exact: true });
        await expect(discardDialog).toBeVisible();
        await discardDialog.getByRole("button", { name: "Keep current state", exact: true }).click();
        await expect(editor).toHaveValue("Fictional unsaved draft");
        await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
        await expect(discardDialog).toBeVisible();
        await discardDialog.getByRole("button", { name: "Discard and close", exact: true }).click();
        await expect(editor).toHaveCount(0);
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await expect(composer).toBeFocused();
        await page.getByRole("button", { name: "Open pending-example.ts in workspace", exact: true }).click();
        await expect(editor).toHaveValue("Current fictional file content\n");
        await expect(editor).toBeFocused();
        await expect(editor).toBeInViewport();
        await page.getByRole("button", { name: "Hide workspace", exact: true }).click();
        await expect(editor).toHaveCount(0);
        await expect(composer).toBeFocused();
      });

      test("agent incomplete output recovers in " + (windowMode ? "dedicated" : "main") + " view", async ({ page }) => {
        await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-completion" + (windowMode ? "&window=1" : ""));
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await composer.fill("Give a bounded synthetic reply.");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        await expect(page.getByRole("alert")).toContainText("response token limit");
        await expect(page.locator('[data-stream-status="failed"]')).toContainText("Synthetic unfinished Agent reply.");
        await expect(page.locator('[data-stream-status="failed"]')).toContainText("Interrupted");
        await expect(page.getByRole("region", { name: "Agent activity status", exact: true })).toContainText("Needs attention");
        await expect(composer).toBeEnabled();
        await fitsViewport(page);
        await composer.fill("Give a shorter synthetic reply.");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        await expect(page.getByText("Synthetic agent reply: no real files were read or changed.", { exact: true })).toBeVisible();
        await expect(page.getByRole("region", { name: "Agent activity status", exact: true })).toContainText("Ready");
        await expect(page.locator('[data-stream-status="failed"]')).toContainText("Interrupted");
        await fitsViewport(page);
      });

      test(`agent model commands survive delayed status in ${windowMode ? "dedicated" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-model-race${windowMode ? "&window=1" : ""}`);
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await expect(composer).toBeDisabled();
        await page.getByRole("button", { name: "Hold older model status", exact: true }).click();
        await page.getByRole("button", { name: "Start session model", exact: true }).click();
        await expect(composer).toBeEnabled();
        await page.getByRole("button", { name: "Release older model status", exact: true }).click();
        await expect(composer).toBeEnabled();
        await composer.fill("Fictional draft retained while stopping the model.");
        await page.getByRole("button", { name: "Hold older model status", exact: true }).click();
        await page.getByRole("button", { name: "Stop model", exact: true }).click();
        await expect(composer).toBeDisabled();
        await page.getByRole("button", { name: "Release older model status", exact: true }).click();
        await expect(composer).toBeDisabled();
        await expect(composer).toHaveValue("Fictional draft retained while stopping the model.");
        await expect(page.getByRole("region", { name: "Agent activity status", exact: true })).toContainText("Model stopped");
        await fitsViewport(page);
      });

      test(`closing agent recovery remains usable in ${windowMode ? "dedicated" : "main"} view`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=agent-closing${windowMode ? "&window=1" : ""}`);
        const composer = page.getByRole("textbox", { name: "Message to the agent", exact: true });
        await expect(composer).toBeDisabled();
        await expect(page.getByRole("region", { name: "Agent activity status", exact: true })).toContainText("Session closing");
        await expect(page.getByRole("button", { name: "Start session model", exact: true })).toBeDisabled();
        await fitsViewport(page);
        const retry = page.getByRole("button", { name: "Retry closing session", exact: true });
        await retry.click();
        await expect(page.getByRole("alert")).toHaveText("This session is closing and cannot accept new messages. Retry closing after its active action stops, or open a new session.");
        await expect(composer).toBeDisabled();
        await retry.click();
        await expect(composer).toHaveCount(0);
        await expect(retry).toHaveCount(0);
        await fitsViewport(page);
      });
    }

    test("prompt check shows metric states, model suggestions and bounded history without overflow", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=prompt-check");
      await page.getByLabel("Prompt to check").fill("Update example.ts with a synthetic acceptance test.");
      await page.getByRole("button", { name: "Check prompt", exact: true }).click();
      await expect(page.getByText(/Synthetic prompt check: verification needs a concrete pass condition\./)).toBeVisible();
      await expect(page.getByText("Update example.ts and run the focused test. Report the changed files and result.", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeEnabled();
      await expect(page.getByText("Outcome metrics require later verification evidence.", { exact: true })).toBeVisible();
      await fitsViewport(page);
    });

    test("team folders expose share, join, pull, push and leave acknowledgements", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=team-folders");
      await page.getByLabel("Folder to share (absolute path)", { exact: true }).fill("D:/example/team/docs");
      await page.getByLabel("Share name", { exact: true }).fill("Example shared docs");
      await page.getByRole("button", { name: "Share", exact: true }).click();
      await expect(page.getByText("synthetic-example-share-token", { exact: true })).toBeVisible();
      await page.getByLabel("Teammate URL").fill("http://127.0.0.1:8765");
      await page.getByLabel("Share id", { exact: true }).fill("example-share");
      await page.getByLabel("Share token", { exact: true }).fill("synthetic-example-share-token");
      await page.getByLabel("Local folder for your copy").fill("D:/example/team/docs-copy");
      await page.getByRole("button", { name: "Join", exact: true }).click();
      await expect(page.getByText(/Joined\. Press Pull/)).toBeVisible();
      await page.getByRole("button", { name: "Pull", exact: true }).click();
      await expect(page.getByText("Pulled 1 file (2 unchanged).", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Push", exact: true }).click();
      await expect(page.getByText(/Pushed 1 file, 1 kept as conflict copies/)).toBeVisible();
      await fitsViewport(page);
      await page.getByRole("button", { name: "Leave", exact: true }).click();
      await expect(page.getByText("Left the folder. Your local copy stays on disk.", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Stop sharing", exact: true }).click();
      await expect(page.getByText("Sharing stopped. The old token no longer works.", { exact: true })).toBeVisible();
      await expect(page.getByText("synthetic-example-share-token", { exact: true })).toHaveCount(0);
    });

    test("workspace content search is bounded, responsive and opens an editable match", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=editor");
      await page.getByText("Workspace tools & safety", { exact: true }).click();
      await expect(page.getByText("Complete application-readable inventory", { exact: true })).toBeVisible();
      await page.getByRole("searchbox", { name: "Search workspace contents", exact: true }).fill("value");
      await page.getByRole("textbox", { name: "Workspace search file pattern", exact: true }).fill("**/*.ts");
      await page.getByRole("button", { name: "Search", exact: true }).click();
      await expect(page.getByText("1 match", { exact: true })).toBeVisible();
      await expect(page.getByText("example.ts:1", { exact: true })).toBeVisible();
      await expect(page.getByText("1 entry scanned · 24 B inspected · 0 skipped entries", { exact: true })).toBeVisible();
      await fitsViewport(page);
      await page.getByRole("button", { name: "Open search result example.ts line 1", exact: true }).click();
      await expect(page.getByRole("textbox", { name: "Workspace file editor", exact: true })).toHaveValue(
        "export const value = 1;\n",
      );
      await page.getByRole("button", { name: "Clear", exact: true }).click();
      await expect(page.getByText("example.ts:1", { exact: true })).toHaveCount(0);
    });

    test("editor recovers its folder and retains an applied receipt across failed readback", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=editor");
      await page.getByRole("button", { name: "Retry folder", exact: true }).click();
      await page.getByRole("button", { name: "example.ts", exact: true }).click();
      const editor = page.getByLabel("Workspace file editor");
      await editor.fill("export const value = 2;\n");
      await page.getByRole("button", { name: "Review diff", exact: true }).click();
      await page.getByRole("button", { name: "Apply reviewed edit", exact: true }).click();
      await expect(page.getByText(/Applied the reviewed edit\./)).toBeVisible();
      await expect(page.getByRole("alert")).toContainText("edit was applied");
      await expect(editor).toHaveAttribute("readonly", "");
      await fitsViewport(page);
      await page.getByRole("button", { name: "Reload file", exact: true }).click();
      await expect(editor).not.toHaveAttribute("readonly", "");
      await expect(editor).toHaveValue("export const value = 2;\n");
      await expect(page.getByRole("button", { name: "Apply reviewed edit", exact: true })).toHaveCount(0);
      await expect(page.getByText(/Applied the reviewed edit\./)).toBeVisible();
    });

    test("editor stages, reviews and applies one mixed create/edit transaction", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=editor");
      await page.getByRole("button", { name: "Retry folder", exact: true }).click();
      await page.getByRole("button", { name: "example.ts", exact: true }).click();
      const editor = page.getByLabel("Workspace file editor");
      await editor.fill("export const value = 2;\n");
      await page.getByRole("button", { name: "Stage for multi-file edit", exact: true }).click();

      await page.getByRole("button", { name: "New file", exact: true }).click();
      await page.getByLabel("Workspace-relative new file path").fill("created.ts");
      await page.getByLabel("New file content").fill("export const created = true;\n");
      await page.getByRole("button", { name: "Stage new file in transaction", exact: true }).click();
      await expect(page.getByText("2/8 staged · 1 create · 1 edit", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit staged new file created.ts", exact: true })).toBeVisible();

      await page.getByRole("button", { name: "Review 2-file transaction", exact: true }).click();
      const review = page.getByRole("region", { name: "Multi-file transaction review", exact: true });
      await expect(review).toContainText("2 files · 1 create · 1 edit");
      await expect(review.locator("summary")).toHaveCount(2);
      await expect(review.getByText("create", { exact: true })).toBeVisible();
      await expect(review.getByText("edit", { exact: true })).toBeVisible();
      await fitsViewport(page);

      await review.getByRole("button", { name: "Apply 2-file transaction", exact: true }).click();
      await expect(page.getByText(/2 reviewed files as one transaction \(1 created, 1 edited\)/u)).toBeVisible();
      await expect(page.getByRole("button", { name: "Edit staged new file created.ts", exact: true })).toHaveCount(0);
    });

    for (const failure of [
      {
        panel: "editor-write-rolled-back",
        message: "The reviewed edit was not applied; the previous file was preserved.",
        retryAllowed: true,
      },
      {
        panel: "editor-write-cleanup",
        message: "The edit was not published, but private staging cleanup is unconfirmed.",
        retryAllowed: false,
      },
      {
        panel: "editor-write-unverified",
        message: "The write result is unverified.",
        retryAllowed: false,
      },
    ] as const) {
      test(`editor preserves its draft after ${failure.panel}`, async ({ page }) => {
        await page.goto(`/e2e/fixtures/workflow-panels.html?panel=${failure.panel}`);
        await page.getByRole("button", { name: "example.ts", exact: true }).click();
        const editor = page.getByRole("textbox", { name: "Workspace file editor", exact: true });
        await editor.fill("export const value = 2;\n");
        await page.getByRole("button", { name: "Review diff", exact: true }).click();
        await page.getByRole("button", { name: "Apply reviewed edit", exact: true }).click();
        await expect(page.getByRole("alert")).toContainText(failure.message);
        await expect(editor).toHaveValue("export const value = 2;\n");
        await expect(page.getByText("EXAMPLE_PRIVATE_WORKSPACE_CANARY", { exact: false })).toHaveCount(0);
        await expect(page.getByText(/Applied the reviewed edit\./u)).toHaveCount(0);
        if (failure.retryAllowed) {
          await expect(page.getByRole("button", { name: "Review diff", exact: true })).toBeEnabled();
          await expect(page.getByRole("button", { name: "Reload file", exact: true })).toHaveCount(0);
          await expect(editor).not.toHaveAttribute("readonly", "");
        } else {
          await expect(page.getByRole("button", { name: "Review diff", exact: true })).toBeDisabled();
          await expect(page.getByRole("button", { name: "Reload file", exact: true })).toBeEnabled();
          await expect(editor).toHaveAttribute("readonly", "");
        }
        await fitsViewport(page);
      });
    }

    test("live refresh preserves timeline zoom and filters within the small window", async ({ page }) => {
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=live");
      const chart = page.getByRole("group", { name: /use plus and minus to zoom/i });
      await chart.press("+");
      await page.getByRole("button", { name: "Write", exact: true }).click();
      await expect(page.getByRole("status")).toContainText("Showing 5m 0s of 10m 0s");
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await expect(page.getByRole("button", { name: "Write", exact: true })).toHaveAttribute("aria-pressed", "false");
      await expect(page.getByRole("status")).toContainText("Showing 5m 0s of 10m 0s");
      await fitsViewport(page);
    });
  });
}
