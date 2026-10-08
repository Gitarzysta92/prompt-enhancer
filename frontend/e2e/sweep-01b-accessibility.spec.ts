import { expect, test, type Page } from "@playwright/test";

type Theme = "dark" | "light";

type Viewport = {
  height: number;
  width: 320 | 360 | 768 | 1440;
};

const PROJECT_ID = "4".repeat(64);
const SESSION_ID = "5".repeat(64);
const TASK_ID = "d".repeat(64);
const UNKNOWN_CHECK_ID = "b".repeat(64);

const VIEWPORTS: readonly Viewport[] = [
  { width: 320, height: 720 },
  { width: 360, height: 800 },
  { width: 768, height: 900 },
  { width: 1440, height: 900 },
];

const THEMES: readonly Theme[] = ["dark", "light"];

// Every direct route family plus the parameterized child shapes that own a
// distinct page or window boundary. All identifiers are reserved fixtures.
const ROUTES = [
  "/",
  "/overview",
  "/projects",
  `/projects/${PROJECT_ID}/overview`,
  `/projects/${PROJECT_ID}/sessions`,
  `/projects/${PROJECT_ID}/automation`,
  `/projects/${PROJECT_ID}/metrics/readiness`,
  `/projects/${PROJECT_ID}/sessions/${SESSION_ID}/metrics/readiness`,
  "/sessions",
  "/agent",
  "/agent/window",
  "/models",
  "/prompt-checks",
  `/prompt-checks/${UNKNOWN_CHECK_ID}`,
  `/prompt-checks/for/${SESSION_ID}`,
  "/calibration",
  "/tasks/flow",
  `/tasks/${TASK_ID}/revisions/1`,
  "/local-sources",
  "/analysis-jobs",
  "/research/methods",
  "/team",
  "/social",
  `/live/projects/${PROJECT_ID}`,
  `/live/projects/${PROJECT_ID}/sessions/${SESSION_ID}`,
  "/not-found",
] as const;

type RouteAudit = {
  contrastFailures: string[];
  duplicateIds: string[];
  invalidReferences: string[];
  missingNames: string[];
  overflow: number;
  subCaptionText: string[];
  undersizedTargets: string[];
  visibleH1s: number;
};

async function selectTheme(page: Page, theme: Theme): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-theme", /^(?:dark|light)$/);
  const current = await page.locator("html").getAttribute("data-theme");
  if (current !== theme) {
    await page.getByRole("button", { name: `Switch to ${theme} mode` }).click();
  }
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function settleRoute(page: Page, path: string, theme: Theme): Promise<void> {
  await page.goto(path);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("#main-content h1:visible")).toHaveCount(1);
  await expect.poll(() => page.title()).not.toBe("Prompt Enhancer");
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async () => {
    const finiteAnimations = document.getAnimations().filter((animation) => (
      animation.playState === "running"
      && animation.effect?.getTiming().iterations !== Infinity
    ));
    await Promise.allSettled(finiteAnimations.map((animation) => animation.finished));
  });
}

async function auditRoute(page: Page): Promise<RouteAudit> {
  return page.evaluate(() => {
    const isVisible = (element: Element): element is HTMLElement => {
      if (!(element instanceof HTMLElement || element instanceof SVGElement)) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const visuallyClipped = rect.width <= 1
        && rect.height <= 1
        && (
          style.clip !== "auto"
          || style.clipPath !== "none"
          || style.overflow === "hidden"
        );
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number.parseFloat(style.opacity) > 0
        && rect.width > 0
        && rect.height > 0
        && !visuallyClipped
        && element.closest("[hidden], [inert], [aria-hidden='true']") === null;
    };

    const describe = (element: Element): string => {
      const classes = (element.getAttribute("class") ?? "")
        .split(/\s+/u)
        .filter(Boolean)
        .slice(0, 2)
        .join(".");
      const role = element.getAttribute("role");
      const self = `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ""}${role ? `[role=${role}]` : ""}`;
      const owner = element.parentElement?.closest<HTMLElement>("[class]");
      if (!owner) return self;
      const ownerClasses = (owner.getAttribute("class") ?? "")
        .split(/\s+/u)
        .filter(Boolean)
        .slice(0, 2)
        .join(".");
      return ownerClasses ? `${self}<${owner.tagName.toLowerCase()}.${ownerClasses}` : self;
    };

    const referencedText = (element: Element, attribute: "aria-labelledby" | "aria-describedby"): string => (
      (element.getAttribute(attribute) ?? "")
        .split(/\s+/u)
        .filter(Boolean)
        .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
        .filter(Boolean)
        .join(" ")
    );

    const accessibleName = (element: Element): string => {
      const aria = element.getAttribute("aria-label")?.trim();
      if (aria) return aria;
      const labelled = referencedText(element, "aria-labelledby");
      if (labelled) return labelled;
      if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) {
        const labels = [...element.labels ?? []].map((label) => label.textContent?.trim() ?? "").filter(Boolean);
        if (labels.length > 0) return labels.join(" ");
      }
      if (element instanceof HTMLImageElement) return element.alt.trim();
      return element.textContent?.trim() || element.getAttribute("title")?.trim() || "";
    };

    const parseColor = (value: string): [number, number, number, number] | null => {
      const match = value.match(/^rgba?\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/u);
      if (!match) return null;
      return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])];
    };

    const composite = (
      foreground: [number, number, number, number],
      background: [number, number, number, number],
    ): [number, number, number, number] => {
      const alpha = foreground[3] + background[3] * (1 - foreground[3]);
      if (alpha === 0) return [0, 0, 0, 0];
      return [
        (foreground[0] * foreground[3] + background[0] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[1] * foreground[3] + background[1] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[2] * foreground[3] + background[2] * background[3] * (1 - foreground[3])) / alpha,
        alpha,
      ];
    };

    const effectiveBackground = (element: Element): [number, number, number, number] | null => {
      const layers: [number, number, number, number][] = [];
      for (let current: Element | null = element; current !== null; current = current.parentElement) {
        const style = getComputedStyle(current);
        if (style.backgroundImage !== "none") return null;
        const color = parseColor(style.backgroundColor);
        if (color && color[3] > 0) layers.push(color);
        if (color?.[3] === 1) break;
      }
      let result: [number, number, number, number] = [255, 255, 255, 1];
      for (const layer of layers.reverse()) result = composite(layer, result);
      return result;
    };

    const luminance = (color: [number, number, number, number]): number => {
      const channels = color.slice(0, 3).map((channel) => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };

    const contrast = (
      foreground: [number, number, number, number],
      background: [number, number, number, number],
    ): number => {
      const resolvedForeground = composite(foreground, background);
      const light = Math.max(luminance(resolvedForeground), luminance(background));
      const dark = Math.min(luminance(resolvedForeground), luminance(background));
      return (light + 0.05) / (dark + 0.05);
    };

    const main = document.getElementById("main-content");
    const visibleElements = main
      ? [...main.querySelectorAll<HTMLElement>("*")].filter(isVisible)
      : [];
    const interactiveSelector = [
      "button",
      "a[href]",
      "select",
      "textarea",
      "summary",
      "input:not([type='hidden'])",
      "[role='button']",
      "[role='tab']",
      "[role='link']",
    ].join(",");
    const interactive = [...document.querySelectorAll<HTMLElement>(interactiveSelector)]
      .filter(isVisible);

    const missingNames = interactive
      .filter((element) => accessibleName(element) === "")
      .map(describe);

    const invalidReferences = [...document.querySelectorAll<HTMLElement>("[aria-labelledby], [aria-describedby]")]
      .filter(isVisible)
      .flatMap((element) => ["aria-labelledby", "aria-describedby"].flatMap((attribute) => {
        const ids = (element.getAttribute(attribute) ?? "").split(/\s+/u).filter(Boolean);
        return ids.some((id) => document.getElementById(id) === null)
          ? [`${describe(element)}:${attribute}`]
          : [];
      }));

    const ids = [...document.querySelectorAll<HTMLElement>("[id]")].map((element) => element.id).filter(Boolean);
    const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];

    const undersizedTargets = interactive.flatMap((element) => {
      if (element.matches("input[type='checkbox'], input[type='radio'], input[type='range']")) return [];
      const rect = element.getBoundingClientRect();
      return rect.width + 0.1 < 44 || rect.height + 0.1 < 44 ? [describe(element)] : [];
    });

    const subCaptionText = visibleElements.flatMap((element) => {
      const ownsText = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()));
      if (!ownsText || element.closest("pre, code") !== null) return [];
      const size = Number.parseFloat(getComputedStyle(element).fontSize);
      return size + 0.01 < 12 ? [`${describe(element)}:${size.toFixed(2)}`] : [];
    });

    const contrastFailures = visibleElements.flatMap((element) => {
      const ownsText = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()));
      if (!ownsText || element.matches(":disabled, [aria-disabled='true']") || element.closest("pre") !== null) return [];
      const style = getComputedStyle(element);
      if (Number.parseFloat(style.opacity) < 1) return [];
      const foreground = parseColor(style.color);
      const background = effectiveBackground(element);
      if (!foreground || !background) return [];
      const ratio = contrast(foreground, background);
      const size = Number.parseFloat(style.fontSize);
      const weight = Number.parseInt(style.fontWeight, 10) || 400;
      const threshold = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
      return ratio + 0.01 < threshold
        ? [`${describe(element)}:${ratio.toFixed(2)}:${style.color}/${background.slice(0, 3).map(Math.round).join(",")}`]
        : [];
    });

    return {
      contrastFailures: [...new Set(contrastFailures)],
      duplicateIds,
      invalidReferences: [...new Set(invalidReferences)],
      missingNames: [...new Set(missingNames)],
      overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      subCaptionText: [...new Set(subCaptionText)],
      undersizedTargets: [...new Set(undersizedTargets)],
      visibleH1s: main ? [...main.querySelectorAll("h1")].filter(isVisible).length : 0,
    };
  });
}

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test(`every route closes responsive semantics and contrast at ${viewport.width}px in ${theme}`, async ({ page }) => {
      test.setTimeout(120_000);
      await page.setViewportSize(viewport);
      await page.goto("/overview");
      await selectTheme(page, theme);

      const failures: Array<{ audit: RouteAudit; path: string }> = [];
      for (const path of ROUTES) {
        await settleRoute(page, path, theme);
        const audit = await auditRoute(page);
        if (
          audit.visibleH1s !== 1
          || audit.overflow !== 0
          || audit.missingNames.length > 0
          || audit.invalidReferences.length > 0
          || audit.duplicateIds.length > 0
          || audit.undersizedTargets.length > 0
          || audit.subCaptionText.length > 0
          || audit.contrastFailures.length > 0
        ) failures.push({ path, audit });
      }

      expect(failures).toEqual([]);
    });
  }
}

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test(`shell keyboard order and focus are visible at ${viewport.width}px in ${theme}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/overview");
      await selectTheme(page, theme);
      // Selecting a theme is itself a pointer focus event. Reload so this test
      // measures first-entry keyboard order rather than continuing after the
      // theme-toggle button in Chromium's sequential focus navigation origin.
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.locator("#main-content h1:visible")).toHaveCount(1);

      await page.keyboard.press("Tab");
      const skip = page.getByRole("link", { name: "Skip to main content" });
      await expect(skip).toBeFocused();
      await expect(skip).toBeVisible();
      await page.keyboard.press("Enter");
      await expect(page.locator("#main-content")).toBeFocused();

      const trigger = viewport.width < 900
        ? page.getByRole("button", { name: "Open navigation" })
        : page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Overview", exact: true });
      await trigger.focus();
      await expect(trigger).toBeFocused();
      const focus = await trigger.evaluate((element) => {
        const style = getComputedStyle(element);
        return {
          boxShadow: style.boxShadow,
          outlineStyle: style.outlineStyle,
          outlineWidth: Number.parseFloat(style.outlineWidth),
        };
      });
      expect(focus.outlineWidth > 0 || focus.boxShadow !== "none").toBe(true);
      expect(focus.outlineStyle === "none" && focus.boxShadow === "none").toBe(false);

      if (viewport.width < 900) {
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog", { name: "Navigate Prompt Enhancer" });
        await expect(dialog).toBeVisible();
        await page.keyboard.press("Shift+Tab");
        await expect(dialog.locator(":focus")).toHaveCount(1);
        expect(await dialog.locator(":focus").evaluate((element) => element.closest('[role="dialog"]') !== null)).toBe(true);
        await page.keyboard.press("Escape");
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
      }
    });
  }
}

for (const viewport of VIEWPORTS) {
  test(`forced colors and reduced motion remain operable at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ colorScheme: "dark", forcedColors: "active", reducedMotion: "reduce" });
    await page.goto("/overview");
    await expect(page.locator("#main-content h1:visible")).toHaveCount(1);

    const trigger = viewport.width < 900
      ? page.getByRole("button", { name: "Open navigation" })
      : page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "Overview", exact: true });
    await trigger.focus();
    const result = await page.evaluate(() => {
      const visible = [...document.querySelectorAll<HTMLElement>("*")].filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      const toMilliseconds = (value: string): number => {
        const parsed = Number.parseFloat(value);
        return value.trim().endsWith("ms") ? parsed : parsed * 1000;
      };
      const moving = visible.flatMap((element) => {
        const style = getComputedStyle(element);
        const durations = [...style.animationDuration.split(","), ...style.transitionDuration.split(",")]
          .map(toMilliseconds);
        return durations.some((duration) => duration > 0.011)
          ? [`${element.tagName.toLowerCase()}.${(element.getAttribute("class") ?? "").split(/\s+/u).slice(0, 2).join(".")}`]
          : [];
      });
      const active = document.activeElement instanceof HTMLElement ? getComputedStyle(document.activeElement) : null;
      return {
        focusVisible: active !== null && (Number.parseFloat(active.outlineWidth) > 0 || active.boxShadow !== "none"),
        moving: [...new Set(moving)],
        reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
        forced: matchMedia("(forced-colors: active)").matches,
      };
    });
    expect(result).toEqual({ focusVisible: true, forced: true, moving: [], reduced: true });
  });
}
