import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { signedIn, vera } from "#/test/users.ts";

test("/projects is not built yet: its heading says what will come, the page that it is coming soon", async () => {
  stubApi({ "GET /api/auth/session": signedIn(vera) });
  const { container } = renderApp("/projects");

  expect(await screen.findByRole("heading", { level: 1, name: "Projects" })).toBeTruthy();
  expect(screen.getByText("Coming soon")).toBeTruthy();
  expect(screen.getByText("This page is still being built.")).toBeTruthy();
  const pages = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(pages.getByRole("link", { name: "Projects Soon" }).getAttribute("aria-current")).toBe(
    "page",
  );
  expect(await violations(container)).toEqual([]);
});

test("viewers opening the Settings land on the Dashboard", async () => {
  stubApi({ "GET /api/auth/session": signedIn(vera) });
  const { router } = renderApp("/settings");

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/");
  expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
});
