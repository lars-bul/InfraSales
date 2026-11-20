import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  applyTheme,
  storedTheme,
  storeTheme,
  systemPrefersDark,
  ThemeContext,
  type ThemeState,
} from "#/lib/theme.ts";

// The chosen theme for the app, remembered on this device; "system" follows the system's setting
// as it changes. `main.tsx` applies the stored theme before the first render already: without an
// inline script (the CSP allows none) a brief flash remains possible.
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState(storedTheme);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") {
      return;
    }
    const system = systemPrefersDark();
    const follow = () => applyTheme("system");
    system.addEventListener("change", follow);
    return () => system.removeEventListener("change", follow);
  }, [theme]);

  const state = useMemo<ThemeState>(
    () => ({
      theme,
      setTheme: (next) => {
        storeTheme(next);
        setTheme(next);
      },
    }),
    [theme],
  );
  return <ThemeContext value={state}>{children}</ThemeContext>;
}
