import { describe, expect, it } from "vitest";
import themeCss from "./theme.css?raw";

describe("theme first-paint contrast", () => {
  it("does not animate inherited text or every descendant during theme application", () => {
    expect(themeCss).not.toMatch(/main\s*\*/);
    expect(themeCss).not.toMatch(
      /body\s*,\s*\.sidebar\s*,\s*\.topbar\s*,\s*main[^{}]*\{[^}]*transition:\s*var\(--theme-transition\)/s,
    );
    expect(themeCss).toMatch(
      /body\s*,\s*\.sidebar\s*,\s*\.topbar\s*,\s*main\s*\{[^}]*transition:\s*background-color 220ms ease, border-color 220ms ease/s,
    );
    expect(themeCss).toMatch(
      /:root\[data-theme-applying\][^{]*\{\s*transition:\s*none\s*!important;/s,
    );
  });
});
