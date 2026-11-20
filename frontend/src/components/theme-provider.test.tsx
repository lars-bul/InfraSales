import { act, renderHook } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { useTheme } from "#/lib/theme.ts";
import { ThemeProvider } from "./theme-provider.tsx";

const isDark = () => document.documentElement.classList.contains("dark");

// A system whose colour scheme the test changes, as a person changing their desktop's setting.
function system() {
  const listeners = new Set<() => void>();
  const media = {
    matches: false,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  };
  vi.spyOn(globalThis, "matchMedia").mockReturnValue(media as unknown as MediaQueryList);
  return {
    listeners,
    prefer(scheme: "dark" | "light") {
      media.matches = scheme === "dark";
      for (const listener of listeners) {
        listener();
      }
    },
  };
}

test("the system's theme is followed as it changes, until another is chosen", () => {
  const desktop = system();
  const { result } = renderHook(useTheme, { wrapper: ThemeProvider });
  expect(result.current.theme).toBe("system");
  expect(isDark()).toBe(false);

  act(() => desktop.prefer("dark"));
  expect(isDark()).toBe(true);

  act(() => result.current.setTheme("light"));

  expect(result.current.theme).toBe("light");
  expect(isDark()).toBe(false);
  expect(desktop.listeners.size).toBe(0);
  act(() => desktop.prefer("dark"));
  expect(isDark()).toBe(false);
  expect(localStorage.getItem("theme")).toBe("light");
});
