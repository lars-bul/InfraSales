import { renderHook } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { applyTheme, storedTheme, storeTheme, useTheme } from "./theme.ts";

const isDark = () => document.documentElement.classList.contains("dark");

function systemPrefers(scheme: "dark" | "light") {
  vi.spyOn(globalThis, "matchMedia").mockImplementation(
    (query) => ({ matches: scheme === "dark", media: query }) as MediaQueryList,
  );
}

test("the system's theme is the default", () => {
  expect(storedTheme()).toBe("system");
});

test("a chosen theme is remembered; anything else stored counts as the system's", () => {
  storeTheme("dark");
  expect(storedTheme()).toBe("dark");

  localStorage.setItem("theme", "sepia");
  expect(storedTheme()).toBe("system");
});

test("blocked storage falls back to the system's theme and remembers nothing", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });

  expect(() => storeTheme("dark")).not.toThrow();
  expect(storedTheme()).toBe("system");
});

test.each([
  ["light", "dark", false],
  ["dark", "light", true],
  ["system", "dark", true],
  ["system", "light", false],
] as const)("the %s theme on a system preferring %s is dark: %s", (theme, scheme, dark) => {
  systemPrefers(scheme);

  applyTheme(theme);

  expect(isDark()).toBe(dark);
});

test("the theme is only known inside the theme provider", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined); // React reports the throw too

  expect(() => renderHook(() => useTheme())).toThrow("useTheme needs a ThemeProvider");
});
