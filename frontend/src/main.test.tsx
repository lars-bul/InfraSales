import { screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { stubApi } from "#/test/fetch.ts";

beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = "";
});

test("the app mounts into #root in the user's language", async () => {
  stubApi({ "GET /api/auth/session": { body: { user: null, provider: "basic" } } });
  document.body.innerHTML = '<div id="root"></div>';

  await import("./main.tsx");

  expect(document.documentElement.lang).toBe("en");
  expect(await screen.findByRole("heading", { name: "InfraSales" })).toBeTruthy();
});

test("a page without #root fails loudly", async () => {
  await expect(import("./main.tsx")).rejects.toThrow("Missing #root element");
});
