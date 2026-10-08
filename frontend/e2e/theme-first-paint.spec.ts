import { expect, test, type Page } from "@playwright/test";

type TargetId = "projects" | "chat" | "assistant";
type ThemeName = "dark" | "light";

type TargetSample = {
  background: string;
  color: string;
  contrast: number;
};

type Frame = {
  milliseconds: number;
  targets: Partial<Record<TargetId, TargetSample>>;
};

type SamplerWindow = Window & {
  __themeInitialComplete?: boolean;
  __themeInitialFrames?: Frame[];
  __captureThemeChange?: (theme: ThemeName) => Promise<Frame[]>;
};

const TARGETS: TargetId[] = ["projects", "chat", "assistant"];
const MINIMUM_CONTRAST = 4.5;

async function installContrastSampler(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const labels = {
      projects: "Projects",
      chat: "Synthetic coding chat",
      assistant: "The fictional module is ready for review.",
    } as const;
    type BrowserTargetId = keyof typeof labels;
    type BrowserFrame = {
      milliseconds: number;
      targets: Partial<Record<BrowserTargetId, TargetSample>>;
    };
    const state = window as SamplerWindow;

    const parseColor = (value: string): [number, number, number, number] | null => {
      const channels = value.match(/[\d.]+/g);
      if (!channels || channels.length < 3) return null;
      return [
        Number(channels[0]),
        Number(channels[1]),
        Number(channels[2]),
        channels[3] === undefined ? 1 : Number(channels[3]),
      ];
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
    const luminance = (color: [number, number, number, number]): number => {
      const channels = color.slice(0, 3).map(value => {
        const unit = value / 255;
        return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const contrast = (
      foreground: [number, number, number, number],
      background: [number, number, number, number],
    ): number => {
      const foregroundLuminance = luminance(foreground);
      const backgroundLuminance = luminance(background);
      return (
        (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
        / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
      );
    };
    const findTextElement = (text: string): HTMLElement | null => {
      const walker = document.createTreeWalker(
        document.body ?? document.documentElement,
        NodeFilter.SHOW_TEXT,
      );
      let node: Node | null;
      while ((node = walker.nextNode())) {
        if (node.nodeValue?.includes(text)) return node.parentElement;
      }
      return null;
    };
    const effectiveBackground = (element: HTMLElement): [number, number, number, number] => {
      const layers: [number, number, number, number][] = [];
      for (let current: HTMLElement | null = element; current; current = current.parentElement) {
        const layer = parseColor(getComputedStyle(current).backgroundColor);
        if (layer && layer[3] > 0) layers.push(layer);
      }
      const root = parseColor(getComputedStyle(document.documentElement).backgroundColor);
      let result: [number, number, number, number] = root ?? [255, 255, 255, 1];
      for (const layer of layers.reverse()) result = composite(layer, result);
      return result;
    };
    const sample = (started: number): BrowserFrame => {
      const targets: BrowserFrame["targets"] = {};
      for (const [id, label] of Object.entries(labels) as [BrowserTargetId, string][]) {
        const element = findTextElement(label);
        if (!element) continue;
        const colorText = getComputedStyle(element).color;
        const color = parseColor(colorText);
        if (!color) continue;
        const background = effectiveBackground(element);
        targets[id] = {
          background: `rgb(${background.slice(0, 3).map(value => Math.round(value)).join(", ")})`,
          color: colorText,
          contrast: Number(contrast(color, background).toFixed(3)),
        };
      }
      return { milliseconds: Number((performance.now() - started).toFixed(1)), targets };
    };

    const initialStarted = performance.now();
    const initialFrames: BrowserFrame[] = [];
    let allTargetsFirstSeen: number | null = null;
    state.__themeInitialFrames = initialFrames;
    state.__themeInitialComplete = false;
    const captureInitial = (): void => {
      const frame = sample(initialStarted);
      initialFrames.push(frame);
      if (Object.keys(frame.targets).length === Object.keys(labels).length) {
        allTargetsFirstSeen ??= performance.now();
      }
      const complete = allTargetsFirstSeen !== null && performance.now() - allTargetsFirstSeen >= 300;
      // Cold Vite/CI startup may delay the fixture; completion remains driven
      // by rendered targets plus 300 ms of observed frames, not a fixed wait.
      const timedOut = performance.now() - initialStarted >= 10_000;
      if (complete || timedOut) {
        state.__themeInitialComplete = true;
        return;
      }
      requestAnimationFrame(captureInitial);
    };
    requestAnimationFrame(captureInitial);

    state.__captureThemeChange = async (theme: ThemeName): Promise<BrowserFrame[]> => {
      const loadModule = new Function("specifier", "return import(specifier)") as (
        specifier: string,
      ) => Promise<{ applyTheme: (theme: ThemeName) => void }>;
      const { applyTheme } = await loadModule("/src/shared/platform/theme.ts");
      const started = performance.now();
      const frames = [sample(started)];
      applyTheme(theme);
      frames.push(sample(started));
      return await new Promise(resolve => {
        const capture = (): void => {
          frames.push(sample(started));
          if (performance.now() - started >= 300) {
            resolve(frames);
            return;
          }
          requestAnimationFrame(capture);
        };
        requestAnimationFrame(capture);
      });
    };
  });
}

function expectReadableFrames(frames: Frame[], label: string): void {
  expect(frames.length, `${label}: frames`).toBeGreaterThan(0);
  for (const target of TARGETS) {
    const samples = frames.flatMap(frame => frame.targets[target] ? [frame.targets[target]] : []);
    expect(samples.length, `${label}: ${target} samples`).toBeGreaterThan(0);
    for (const sample of samples) {
      expect(sample.color, `${label}: ${target} foreground`).toMatch(/^rgba?\(/);
      expect(sample.background, `${label}: ${target} background`).toMatch(/^rgb\(/);
      expect(sample.contrast, `${label}: ${target} contrast`).toBeGreaterThanOrEqual(MINIMUM_CONTRAST);
    }
  }
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test.describe(`theme contrast with reduced motion ${reducedMotion}`, () => {
    test.use({ reducedMotion });

    test("keeps Agent text readable on first paint and both theme changes", async ({ page }) => {
      await installContrastSampler(page);
      await page.goto("/e2e/fixtures/workflow-panels.html?panel=agent-shell");
      await expect(page.getByRole("textbox", { name: "Message to the agent", exact: true })).toBeEditable();
      await page.waitForFunction(() => (window as SamplerWindow).__themeInitialComplete === true);

      const initial = await page.evaluate(() => (
        (window as SamplerWindow).__themeInitialFrames ?? []
      ));
      expectReadableFrames(initial, `${reducedMotion} initial`);

      for (const theme of ["light", "dark"] as const) {
        const frames = await page.evaluate(async requestedTheme => {
          const capture = (window as SamplerWindow).__captureThemeChange;
          if (!capture) throw new Error("theme_sampler_unavailable");
          return await capture(requestedTheme);
        }, theme);
        expectReadableFrames(frames, `${reducedMotion} ${theme}`);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      }
    });
  });
}
