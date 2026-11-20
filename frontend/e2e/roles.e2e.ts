import { en } from "../src/i18n/locales/en.ts";
import { expect, test } from "./fixtures.ts";
import { pageHeading, sessionOf, userMenu } from "./users.ts";

const dashboardUrl = /\/$/u;
const auditUrl = /\/audit$/u;
const signInsUrl = /\/audit\?action=auth\.login$/u;
const signedIn = /signed in$/u;
const readTheLog = /read the audit log$/u;

test.describe("alice, an admin", () => {
  test.use({ storageState: sessionOf("alice") });

  test("sees the jobs and may open the audit log", async ({ page, scan }) => {
    await page.goto("/jobs");
    await expect(pageHeading(page, en.jobs.title)).toBeVisible();
    await expect(userMenu(page, "alice")).toBeVisible();
    await scan(); // the audit log opens in the app, without a full navigation

    await page
      .getByRole("navigation", { name: en.app.navigation })
      .getByRole("link", { name: en.audit.title })
      .click();

    await expect(page).toHaveURL(auditUrl);
    await expect(pageHeading(page, en.audit.title)).toBeVisible();
    // The test users' sign-ins are among the newest events, each one a sentence.
    await expect(page.getByRole("columnheader", { name: en.audit.activity })).toBeVisible();
    const signIn = page.getByRole("button", { name: signedIn }).first();
    await expect(signIn).toBeVisible();

    await signIn.click();
    await expect(signIn).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("definition").filter({ hasText: "auth.login" })).toBeVisible();
    await scan(); // the expanded details

    await page.getByRole("combobox", { name: en.audit.filters.type }).selectOption("auth.login");
    await expect(page).toHaveURL(signInsUrl);
    await expect(page.getByRole("button", { name: readTheLog })).toHaveCount(0);
    await expect(page.getByRole("button", { name: signedIn }).first()).toBeVisible();
  });
});

test.describe("vera, a viewer", () => {
  test.use({ storageState: sessionOf("vera") });

  test("sees the Dashboard and the jobs, without their runs, the Feeds, the audit log or the Settings", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
    await expect(userMenu(page, "vera")).toBeVisible();
    const pages = page.getByRole("navigation", { name: en.app.navigation });
    await expect(pages.getByRole("link", { name: en.jobs.title, exact: true })).toBeVisible();
    await expect(pages.getByRole("link", { name: en.jobs.pages.runs })).toHaveCount(0);
    await expect(pages.getByRole("link", { name: en.feeds.title })).toHaveCount(0);
    await expect(pages.getByRole("link", { name: en.audit.title })).toHaveCount(0);
    await expect(pages.getByRole("link", { name: en.settings.title })).toHaveCount(0);
  });

  for (const path of ["/runs", "/audit", "/feeds", "/settings"]) {
    test(`is sent from ${path} to the Dashboard`, async ({ page }) => {
      await page.goto(path);

      await expect(page).toHaveURL(dashboardUrl);
      await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
    });
  }
});
