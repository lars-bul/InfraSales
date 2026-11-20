import { en } from "../src/i18n/locales/en.ts";
import { expect, test } from "./fixtures.ts";
import { pageHeading, sessionOf, userMenu } from "./users.ts";

const auditUrl = /\/audit$/u;
const dark = /\bdark\b/u;

test.use({ storageState: sessionOf("alice") });

test("the theme is chosen in the user menu, by keyboard, and remembered", async ({
  page,
  scan,
}) => {
  await page.goto("/jobs");
  await expect(pageHeading(page, en.jobs.title)).toBeVisible();
  const html = page.locator("html");
  const theme = page.getByRole("combobox", { name: en.app.theme });

  await userMenu(page, "alice").focus();
  await page.keyboard.press("Enter");
  await expect(theme).toContainText(en.themes.system); // the default
  await theme.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option", { name: en.themes.dark })).toBeVisible();
  await scan(); // the open Select: Base UI renders it without a <style> element (CSPProvider)
  await page.getByRole("option", { name: en.themes.dark }).press("Enter");

  await expect(html).toHaveClass(dark);
  await expect(theme).toContainText(en.themes.dark);
  await scan();

  await page.reload();
  await expect(pageHeading(page, en.jobs.title)).toBeVisible();
  await expect(html).toHaveClass(dark);
  await scan();
  await userMenu(page, "alice").click();
  await expect(theme).toContainText(en.themes.dark);
});

// Each project runs this in its colour scheme, so axe checks the main colour, the sidebar's name
// and icon, and the Job runs and the audit log as they stand (empty or not) in both.
test("the pages read in this colour scheme, InfraSales named in the sidebar", async ({
  page,
  scan,
}) => {
  await page.goto("/jobs");
  await expect(pageHeading(page, en.jobs.title)).toBeVisible();
  const sidebar = page.locator("[data-slot=sidebar-header]");
  await expect(sidebar.getByText(en.app.title)).toBeVisible();
  await expect(sidebar.locator('img[src="/favicon.svg"]')).toBeVisible(); // no other logo

  await scan();

  const pages = page.getByRole("navigation", { name: en.app.navigation });
  await pages.getByRole("link", { name: en.jobs.pages.runs }).click();
  await expect(pageHeading(page, en.jobs.title)).toBeVisible();
  await expect(
    page.getByRole("table").or(page.getByText(en.history.empty.title)).first(),
  ).toBeVisible();
  await scan();

  await page.getByRole("link", { name: en.audit.title }).click();
  await expect(pageHeading(page, en.audit.title)).toBeVisible();
  await expect(
    page.getByRole("table").or(page.getByText(en.audit.empty.title)).first(),
  ).toBeVisible();
});

test("collapsed, the sidebar keeps its icons, each page named in a tooltip", async ({
  page,
  scan,
}) => {
  await page.goto("/");
  await expect(pageHeading(page, en.dashboard.title)).toBeVisible();
  await page.getByRole("button", { name: en.ui.toggleSidebar }).click();
  const pages = page.getByRole("navigation", { name: en.app.navigation });

  const audit = pages.getByRole("link", { name: en.audit.title });
  await expect(audit).toBeVisible();
  await expect(audit).toHaveCSS("width", "32px"); // just the icon
  await expect(page.locator('[data-slot=sidebar-header] img[src="/favicon.svg"]')).toBeVisible();
  await expect(userMenu(page, "alice")).toBeVisible();

  await audit.hover();
  await expect(page.locator("[data-slot=tooltip-content]")).toHaveText(en.audit.title);
  await scan();

  await audit.click();
  await expect(pageHeading(page, en.audit.title)).toBeVisible();
});

test.describe("on a small screen", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the sidebar is a menu the top bar opens", async ({ page, scan }) => {
    await page.goto("/jobs");
    await expect(pageHeading(page, en.jobs.title)).toBeVisible();
    await expect(page.getByRole("navigation", { name: en.app.navigation })).toBeHidden();

    await page.getByRole("button", { name: en.ui.toggleSidebar }).click();
    const menu = page.getByRole("dialog", { name: en.ui.sidebar });
    await expect(menu).toBeVisible();
    await scan();
    await menu.getByRole("link", { name: en.audit.title }).click();

    await expect(page).toHaveURL(auditUrl);
    await expect(pageHeading(page, en.audit.title)).toBeVisible();
    await expect(menu).toBeHidden(); // opening a page closes the menu
  });
});
