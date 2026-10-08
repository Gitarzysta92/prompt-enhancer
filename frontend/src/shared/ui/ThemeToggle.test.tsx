import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { THEME_STORAGE_KEY } from "../platform/theme";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("starts dark, flips to light on click, and remembers it", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
    render(<ThemeToggle storage={storage} />);
    const button = screen.getByRole("button", { name: "Switch to light mode" });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Switch to dark mode" })).toBeTruthy();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(store.get(THEME_STORAGE_KEY)).toBe("light");
  });
});
