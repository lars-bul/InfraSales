import { createContext, use } from "react";

const KEY = "theme"; // in localStorage: the one thing the app keeps there, a display preference
const PREFERS_DARK = "(prefers-color-scheme: dark)";
const DARK_CLASS = "dark"; // the stylesheet's `dark` variant

function isTheme(value: unknown): value is Theme {
  return THEMES.includes(value as Theme);
}

export const THEMES = ["light", "dark", "system"] as const;
export type Theme = (typeof THEMES)[number];

export interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

/** The chosen theme and its setter, from `ThemeProvider`. */
export const ThemeContext = createContext<ThemeState | null>(null);

/** The theme chosen earlier on this device; the system's by default, or if storage is blocked. */
export function storedTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** Remembers the theme on this device; where storage is blocked, it lasts until a reload. */
export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // storage blocked: nothing to remember it in
  }
}

/** The media query telling whether the system prefers dark. */
export function systemPrefersDark(): MediaQueryList {
  return matchMedia(PREFERS_DARK);
}

/** Dark or light on <html>, following the system for "system". */
export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && systemPrefersDark().matches);
  document.documentElement.classList.toggle(DARK_CLASS, dark);
}

export function useTheme(): ThemeState {
  const state = use(ThemeContext);
  if (!state) {
    throw new Error("useTheme needs a ThemeProvider");
  }
  return state;
}
