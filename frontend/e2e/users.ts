import type { Page } from "@playwright/test";
import { en } from "../src/i18n/locales/en.ts";
import { expect } from "./fixtures.ts";
import { password } from "./profile.ts";

const roles = { alice: "admin", vera: "viewer" } as const;

// The test profile's sample users, and where their saved sessions live.
export type User = "alice" | "vera"; // admin, viewer

// The user menu's button in the sidebar, named after who is signed in.
export function userMenu(page: Page, user: User) {
  const name = en.app.userMenu.replace("{{name}}", user).replace("{{role}}", en.roles[roles[user]]);
  return page.getByRole("button", { name });
}

// The heading of the page shown in the app shell's top bar.
export function pageHeading(page: Page, title: string) {
  return page.getByRole("heading", { level: 1, name: title });
}

export function sessionOf(user: User): string {
  return `e2e/.auth/${user}.json`;
}

// Signs in through the real form, from wherever the app sent the browser to sign in. Checks the
// sign-in page with `scan` before the form post leaves it.
export async function signIn(
  page: Page,
  scan: () => Promise<void>,
  user: User,
  secret = password,
): Promise<void> {
  await expect(page.getByRole("heading", { name: en.signIn.title })).toBeVisible();
  await page.getByLabel(en.signIn.username).fill(user);
  await page.getByLabel(en.signIn.password).fill(secret);
  await scan();
  await page.getByRole("button", { name: en.signIn.submit }).click();
}
