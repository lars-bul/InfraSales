import { expect, test } from "vitest";

// Every module has a test next to it: `features/runs/run-now.tsx` → `features/runs/run-now.test.tsx`
// (mirrors tests/test_layout.py). The generated API client (`client/`) is tested through the
// modules that configure and use it; the routes (`routes/` and its generated tree) through the app
// at their URLs (`renderApp`), the generated shadcn/ui components (`components/ui/`,
// `hooks/use-mobile.ts`) through the app shell.
const modules = Object.keys(
  import.meta.glob([
    "./**/*.{ts,tsx}",
    "!./**/*.test.{ts,tsx}",
    "!./**/*.d.ts",
    "!./test/**",
    "!./client/**",
    "!./routes/**",
    "!./routeTree.gen.ts",
    "!./components/ui/**",
    "!./hooks/use-mobile.ts",
  ]),
);
const extension = /\.tsx?$/;
const tests = new Set(Object.keys(import.meta.glob("./**/*.test.{ts,tsx}")));

test("every module has a test module next to it", () => {
  const missing = modules.filter(
    (module) =>
      ![".test.ts", ".test.tsx"].some((suffix) => tests.has(module.replace(extension, suffix))),
  );

  expect(missing).toEqual([]);
});

// The top level holds the app's entry points only: the page's entry, the app and its router.
// Screens live in `features/<feature>/`, shared parts in `components/`, `lib/`, `hooks/`, `i18n/`.
const ENTRY_POINTS = ["./app.tsx", "./create-app.ts", "./main.tsx", "./router.tsx"];

test("the top level holds the entry points only", () => {
  const topLevel = modules.filter((module) => !module.slice("./".length).includes("/"));

  expect(new Set(topLevel)).toEqual(new Set(ENTRY_POINTS));
});
