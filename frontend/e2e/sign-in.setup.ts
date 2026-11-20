import { en } from "../src/i18n/locales/en.ts";
import { expect, test } from "./fixtures.ts";
import { pageHeading, sessionOf, signIn, type User } from "./users.ts";

// Once per role: sign in through the form and save the session for the specs.
for (const user of ["alice", "vera"] satisfies User[]) {
  test(`${user} signs in`, async ({ page, scan }) => {
    await page.goto("/sign-in");
    await signIn(page, scan, user);

    await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
    await page.context().storageState({ path: sessionOf(user) });
  });
}
