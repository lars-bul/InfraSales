import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// A file's first render loads its page's code, which takes over a second on a busy machine:
// `findBy…` waits up to 5 s for it (the default, 1 s, made those first tests flaky).
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup(); // unmount what each test rendered
  localStorage.clear(); // the theme chosen
  document.documentElement.classList.remove("dark");
});

// jsdom has no layout: the router's scroll reset after navigating has nothing to do.
globalThis.scrollTo = () => undefined;

// jsdom has no media queries: the system prefers light, the screen is wide (tests may stub it).
globalThis.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;
