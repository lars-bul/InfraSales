import { en } from "../src/i18n/locales/en.ts";
import { expect, test } from "./fixtures.ts";
import { pageHeading, signIn, userMenu } from "./users.ts";

const dashboardUrl = /\/$/u;
const signInUrl = /\/sign-in$/u;
const failedUrl = /\/sign-in\?signin=failed$/u;
const endedUrl = /\/sign-in\?ended=true$/u;

for (const path of ["/", "/jobs", "/audit", "/feeds"]) {
  test(`signed-out visitors of ${path} are sent to sign in`, async ({ page }) => {
    await page.goto(path);

    await expect(page).toHaveURL(signInUrl);
    await expect(page.getByRole("heading", { name: en.signIn.title })).toBeVisible();
  });
}

test("a wrong password is reported on the sign-in page", async ({ page, scan }) => {
  await page.goto("/");
  await signIn(page, scan, "alice", "not-the-password");

  await expect(page).toHaveURL(failedUrl);
  const { title, description } = en.signIn.callouts.failed;
  await expect(page.getByRole("alert")).toHaveText(`${title}${description}`); // scanned by the guard
});

test("signing in leads to the Dashboard, signing out from the user menu back to sign in", async ({
  page,
  scan,
}) => {
  await page.goto("/");
  await signIn(page, scan, "alice");

  await expect(page).toHaveURL(dashboardUrl);
  await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
  await scan();

  await userMenu(page, "alice").click();
  const menu = page.getByRole("dialog", {
    name: en.app.signedInAs.replace("{{name}}", "alice").replace("{{role}}", en.roles.admin),
  });
  await expect(menu).toBeVisible();
  await scan(); // the open menu, before signing out leaves the page
  await menu.getByRole("button", { name: en.app.signOut }).click();

  await expect(page).toHaveURL(signInUrl);
  await expect(page.getByRole("heading", { name: en.signIn.title })).toBeVisible();
  await scan();

  await page.goto("/"); // the session is gone, not only the page
  await expect(page).toHaveURL(signInUrl);
});

test("a request the page sends while signing out is refused quietly", async ({ page, scan }) => {
  await page.goto("/");
  await signIn(page, scan, "alice");
  await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
  await scan();
  // The server ends the session at once, but its answer arrives late, so the page stays a while.
  await page.route("**/api/auth/logout", async (route) => {
    const ended = page.waitForEvent("framenavigated", (frame) => endedUrl.test(frame.url()));
    const response = await route.fetch({ maxRedirects: 0 });
    await ended; // the page meanwhile saw its session end
    await route.fulfill({ response });
  });
  // Once the session has ended, the page moves to the audit log link, which preloads the audit
  // log: the server refuses that with a 401, as it would refuse a poll.
  await page.evaluate(() => {
    async function whenSignedOut() {
      const { user } = await (await fetch("/api/auth/session")).json();
      if (user === null) {
        document.querySelector<HTMLElement>("a[href='/audit']")?.focus();
      } else {
        setTimeout(whenSignedOut);
      }
    }
    document.addEventListener("submit", whenSignedOut);
  });

  await userMenu(page, "alice").click();
  await scan();
  await page.getByRole("button", { name: en.app.signOut }).click();

  await expect(page).toHaveURL(signInUrl);
  await expect(page.getByRole("heading", { name: en.signIn.title })).toBeVisible();
});
