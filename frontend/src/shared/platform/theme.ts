/**
 * Theme: dark is the default and the product's own look; light stays available.
 * The choice is kept in localStorage and stamped on <html data-theme> so every
 * stylesheet (including the generated palette) switches in one place.
 */

export type ThemeName = "dark" | "light";

export const THEME_STORAGE_KEY = "prompt-enhancer.theme";
export const DEFAULT_THEME: ThemeName = "dark";

function isThemeName(value: unknown): value is ThemeName {
  return value === "dark" || value === "light";
}

export function readStoredTheme(storage: Pick<Storage, "getItem"> | null | undefined): ThemeName {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY);
    return isThemeName(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme: ThemeName, root: HTMLElement | null | undefined = globalThis.document?.documentElement): void {
  if (!root) return;
  root.setAttribute("data-theme-applying", "");
  try {
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme;
    // Resolve the new palette while transitions are suppressed. Removing the
    // marker afterwards cannot interpolate old foregrounds over new surfaces.
    void root.offsetWidth;
  } finally {
    root.removeAttribute("data-theme-applying");
  }
}

export function persistTheme(theme: ThemeName, storage: Pick<Storage, "setItem"> | null | undefined): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Private mode or a full store: the choice simply does not survive a reload.
  }
}

/** Apply the stored (or default) theme before the first React render. */
export function bootstrapTheme(): ThemeName {
  const theme = readStoredTheme(globalThis.localStorage);
  applyTheme(theme);
  return theme;
}
