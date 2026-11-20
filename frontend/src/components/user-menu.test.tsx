import { screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { alice, signedIn, vera } from "#/test/users.ts";

function signedInAs(user: typeof alice | typeof vera) {
  stubApi({ "GET /api/auth/session": signedIn(user), "GET /api/config": { body: [weekly] } });
}

async function openUserMenu(name: string) {
  await userEvent.click(await screen.findByRole("button", { name }));
  return await screen.findByRole("dialog");
}

test("the user menu shows who is signed in, with which role", async () => {
  signedInAs(vera);
  renderApp("/jobs");

  const menu = await openUserMenu("User menu: vera (viewer)");

  expect(menu.getAttribute("aria-labelledby")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Signed in as vera (viewer)" })).toBeTruthy();
  expect(await violations(menu)).toEqual([]);
});

test("signing out is a native form post to the backend", async () => {
  signedInAs(alice);
  renderApp("/jobs");

  await openUserMenu("User menu: alice (admin)");

  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(signOut.getAttribute("type")).toBe("submit");
  const form = signOut.closest("form");
  expect(form?.getAttribute("action")).toBe("/api/auth/logout");
  expect(form?.getAttribute("method")).toBe("post");
});

test("the theme follows the system until another is chosen, and is remembered", async () => {
  signedInAs(alice);
  const first = renderApp("/jobs");
  await openUserMenu("User menu: alice (admin)");
  const theme = screen.getByRole("combobox", { name: "Theme" });
  expect(theme.textContent).toContain("System");
  expect(document.documentElement.classList.contains("dark")).toBe(false);

  await userEvent.click(theme);
  await userEvent.click(await screen.findByRole("option", { name: "Dark" }));

  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
  expect(localStorage.getItem("theme")).toBe("dark");
  expect(await violations(first.container)).toEqual([]);
  first.unmount();

  renderApp("/jobs"); // a reload
  await openUserMenu("User menu: alice (admin)");
  expect(screen.getByRole("combobox", { name: "Theme" }).textContent).toContain("Dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});
