import { useEffect, useState } from "react";
import { applyTheme, persistTheme, readStoredTheme, type ThemeName } from "../platform/theme";

/** Dark ⇄ light switch for the top bar; dark is the default. */
export function ThemeToggle({ storage = globalThis.localStorage }: { storage?: Pick<Storage, "getItem" | "setItem"> | null }) {
  const [theme, setTheme] = useState<ThemeName>(() => readStoredTheme(storage));

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const next: ThemeName = theme === "dark" ? "light" : "dark";
  return (
    <button
      aria-label={`Switch to ${next} mode`}
      aria-pressed={theme === "dark"}
      className="theme-toggle"
      onClick={() => {
        setTheme(next);
        persistTheme(next, storage);
      }}
      title={theme === "dark" ? "Dark mode on - switch to light" : "Light mode on - switch to dark"}
      type="button"
    >
      <span aria-hidden="true" className="theme-toggle__orb" />
      <span>{theme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
