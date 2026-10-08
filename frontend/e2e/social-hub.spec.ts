import { expect, test, type Page } from "@playwright/test";

/** Visible text nodes below the requested floor and horizontal overflow, scoped to one root. */
async function layoutAudit(page: Page, rootSelector: string, minimumFontSize: number) {
  return page.evaluate(({ selector, minimum }) => {
    const root = document.querySelector<HTMLElement>(selector);
    if (root === null) throw new Error(`synthetic root ${selector} missing`);
    const textSelectors = "small,span,p,strong,button,input,dt,dd,b,li,legend,label,h1,h2,h3";
    const tooSmall = [...root.querySelectorAll<HTMLElement>(textSelectors)]
      .filter((element) => {
        const style = getComputedStyle(element);
        return style.display !== "none"
          && style.visibility !== "hidden"
          && element.getClientRects().length > 0
          && Number.parseFloat(style.fontSize) < minimum;
      })
      .map((element) => `${element.tagName.toLowerCase()}.${element.className}`);
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      tooSmall,
    };
  }, { selector: rootSelector, minimum: minimumFontSize });
}

async function installClsObserver(page: Page) {
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
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  return page.evaluate(() => (window as typeof window & { __syntheticClsState: { value: number } }).__syntheticClsState.value);
}

test.describe("social hub", () => {
  test("renders a fictional, local-only social workspace with friends, chats, requests, presence, and unread state", async ({ page }) => {
    await installClsObserver(page);
    await page.goto("/social");
    await expect(page.getByRole("heading", { name: "Social hub" })).toBeVisible();
    await expect(page.getByRole("note", { name: "Fictional synthetic demo" })).toContainText("nothing is delivered to another device, stored durably, synced, or encrypted");
    const summary = page.getByRole("group", { name: "Local social state summary" });
    await expect(summary).toContainText("3 friends");
    await expect(summary).toContainText("6 unread");
    await expect(summary).toContainText("Local state only · not delivered");
    await expect(summary).toContainText("Not end-to-end encrypted");
    await expect(summary).toContainText("Invite-only groups · nothing discoverable");
    const presence = page.getByRole("group", { name: /Your presence · opt-in, coarse, self-declared/ });
    await expect(presence).toContainText("never derived from analyzer activity");
    await expect(presence.getByRole("checkbox")).toBeChecked();

    const chats = page.getByRole("list", { name: "Conversations" });
    await expect(chats.getByRole("listitem")).toHaveCount(4);
    await expect(chats.getByRole("button", { name: /Alex Example/ })).toHaveAttribute("aria-current", "true");
    await chats.getByRole("button", { name: /#fixture-guild/ }).click();
    await expect(page.getByRole("region", { name: "#fixture-guild" })).toContainText("Your role · Owner");
    await expect(summary).toContainText("3 unread");

    // Keyboard: arrow keys move between rail tabs and reveal friends with visible presence text.
    const tabs = page.getByRole("tablist", { name: "Rail sections" });
    await tabs.getByRole("tab", { name: /Chats/ }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.getByRole("tab", { name: /Friends/ })).toHaveAttribute("aria-selected", "true");
    const friends = page.getByRole("list", { name: "Friends" });
    await expect(friends.getByRole("listitem")).toHaveCount(3);
    await expect(friends).toContainText("Casey Example");
    await expect(friends.locator(".status-pill", { hasText: "Offline" })).toBeVisible();
    // Presence is labelled as self-declared opt-in, separate from analyzer activity.
    await expect(page.getByText(/Presence · self-declared, coarse, opt-in · not analyzer activity/)).toBeVisible();
    await page.keyboard.press("ArrowRight");
    const incoming = page.getByRole("list", { name: "Incoming friend requests" });
    await expect(incoming).toContainText("Dana Example");
    await incoming.getByRole("button", { name: "Accept" }).click();
    await expect(summary).toContainText("4 friends");

    const layout = await layoutAudit(page, ".social-hub", 14);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
    expect(await currentCls(page)).toBeLessThan(0.02);
    await expect(page.locator("input[type='file']")).toHaveCount(0);
  });

  test("threads, reactions, search, and the composer stay local-only and keyboard operable", async ({ page }) => {
    await page.goto("/social");
    await page.getByRole("list", { name: "Conversations" }).getByRole("button", { name: /#fixture-guild/ }).click();
    const conversation = page.getByRole("region", { name: "#fixture-guild" });
    await conversation.getByRole("button", { name: /^thumbs up: 2/ }).click();
    await expect(conversation.getByRole("button", { name: /^thumbs up: 3 .* you reacted/ })).toHaveAttribute("aria-pressed", "true");
    await conversation.getByRole("button", { name: "2 replies" }).click();
    const thread = page.getByRole("region", { name: /Thread · 2 replies/ });
    await thread.getByLabel("Thread reply (local demo, not delivered)").fill("Fixture keyboard reply");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("region", { name: /Thread · 3 replies/ })).toContainText("Fixture keyboard reply");
    await expect(page.getByRole("status").filter({ hasText: /Nothing was delivered/ })).toHaveCount(1);
    await page.getByLabel("Search people, channels, and messages").fill("blake");
    const results = page.getByRole("region", { name: "Search results" });
    await expect(results.getByRole("list", { name: "Matching people" })).toContainText("Blake Example");
    await expect(results.getByRole("list", { name: "Matching conversations" })).toContainText("Blake Example");
  });

  test("direct file sharing needs consent, shows honest transfer states, and never exposes a path or bytes", async ({ page }) => {
    await page.goto("/social");
    const files = page.getByRole("region", { name: "Direct file sharing" });
    await expect(files).toContainText("No file is read from disk, no path is exposed, and no bytes exist");
    const notes = files.getByRole("article", { name: "synthetic-readiness-notes.md" });
    await expect(notes).toContainText("Awaiting recipient consent");
    await expect(notes.getByRole("progressbar")).toHaveAttribute("aria-valuetext", /amount unknown/);
    await notes.getByRole("button", { name: "Review and consent" }).click();
    const dialog = page.getByRole("dialog", { name: "Accept synthetic-readiness-notes.md?" });
    await expect(dialog).toContainText("never receives a copy");
    await expect(dialog.getByRole("button", { name: "Grant consent" })).toBeFocused();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Grant consent" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(notes).toContainText("Transferring directly");
    await notes.getByRole("button", { name: /Pause/ }).click();
    await expect(notes).toContainText("Paused");
    await notes.getByRole("button", { name: /Resume/ }).click();
    await expect(notes).toContainText("Complete · integrity verified", { timeout: 20_000 });
    await expect(notes.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");

    const mine = files.getByRole("article", { name: "synthetic-metric-summary.pdf" });
    await mine.getByRole("button", { name: "Revoke offer" }).click();
    const revoke = page.getByRole("dialog", { name: "Revoke synthetic-metric-summary.pdf?" });
    await page.keyboard.press("Escape");
    await expect(revoke).toHaveCount(0);
    await expect(mine.getByRole("button", { name: "Revoke offer" })).toBeFocused();
    await mine.getByRole("button", { name: "Revoke offer" }).click();
    await page.getByRole("dialog", { name: "Revoke synthetic-metric-summary.pdf?" }).getByRole("button", { name: "Revoke" }).click();
    await expect(mine).toContainText("Revoked by owner");
    await expect(page.locator("input[type='file']")).toHaveCount(0);
  });

  test("states encryption and metadata truths, shows no-direct-path for CGNAT, and queues sender-offline offers locally", async ({ page }) => {
    await page.goto("/social");
    await page.getByRole("button", { name: /What this demo can and cannot promise/ }).click();
    const facts = page.getByLabel("Social boundary facts");
    await expect(facts).toContainText("End-to-end encryption is not implemented in this demo");
    await expect(facts).toContainText("relationship (who talks to whom), timing, availability, and size-class metadata");
    await expect(facts).toContainText("no relay and no TURN");
    await expect(facts).toContainText("No export or delete-my-data control is offered");
    await expect(page.locator(".social-hub").getByRole("button", { name: /export|delete my data|browse|discover|join/i })).toHaveCount(0);

    await page.getByRole("list", { name: "Conversations" }).getByRole("button", { name: /Blake Example/ }).click();
    const files = page.getByRole("region", { name: "Direct file sharing" });
    const sketch = files.getByRole("article", { name: "synthetic-lane-sketch.svg" });
    await expect(sketch).toContainText("No direct path · symmetric NAT/CGNAT");
    await expect(sketch.getByRole("button", { name: /Resume \(no direct path\)/ })).toBeDisabled();

    // Offline sender: the metadata offer can still be created and is queued on this device.
    const presence = page.getByRole("group", { name: /Your presence/ });
    await presence.getByRole("combobox", { name: "Level" }).selectOption("offline");
    const form = files.getByRole("form", { name: "Offer a file (metadata only)" });
    await form.getByLabel("Display name").fill("synthetic-offline-notes.md");
    await form.getByRole("button", { name: /Queue offer for 1 recipient/ }).click();
    const queued = files.getByRole("article", { name: "synthetic-offline-notes.md" });
    await expect(queued).toContainText("Queued on your device · you are not currently shared as online");
    await presence.getByRole("combobox", { name: "Level" }).selectOption("online");
    await expect(queued).toContainText("Awaiting recipient consent");
    // Not-shared presence is its own state, never rendered as offline.
    await page.getByRole("list", { name: "Conversations" }).getByRole("button", { name: /#fixture-guild/ }).click();
    const finley = page.getByRole("list", { name: "Conversation members" }).getByRole("listitem").filter({ hasText: "Finley Example" });
    await expect(finley).toContainText("Presence not shared");
    await expect(finley).not.toContainText("Offline");
    await expect(page.locator("input[type='file']")).toHaveCount(0);
  });

  test("keeps controls focus-visible in forced-colors and reduced-motion modes and reads at 360px", async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await page.goto("/social");
    const tab = page.getByRole("tablist", { name: "Rail sections" }).getByRole("tab", { name: /Friends/ });
    await tab.focus();
    await expect(tab).toBeFocused();
    const styles = await tab.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, transitionDuration: style.transitionDuration };
    });
    expect(styles.outlineStyle).not.toBe("none");
    expect(Number.parseFloat(styles.outlineWidth)).toBeGreaterThanOrEqual(3);
    expect(styles.transitionDuration).toMatch(/^(0s|0ms)$/);

    await page.setViewportSize({ width: 360, height: 640 });
    await expect(page.getByRole("heading", { name: "Social hub" })).toBeVisible();
    const layout = await layoutAudit(page, ".social-hub", 12);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.tooSmall).toEqual([]);
  });
});
