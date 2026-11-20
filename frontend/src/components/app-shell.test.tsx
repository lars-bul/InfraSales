import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunHistoryEntry } from "#/client/types.gen.ts";
import { violations } from "#/test/axe.ts";
import { weekly } from "#/test/entries.ts";
import { stubApi } from "#/test/fetch.ts";
import { renderApp } from "#/test/render.tsx";
import { entryAs } from "#/test/runs.ts";
import { summaries } from "#/test/summaries.ts";
import { alice, signedIn, vera } from "#/test/users.ts";

function signedInAs(user: typeof alice | typeof vera, runs: RunHistoryEntry[] = []) {
  stubApi({
    "GET /api/auth/session": signedIn(user),
    "GET /api/config": { body: [weekly] },
    "GET /api/audit-events": { body: [] },
    "GET /api/jobs/runs": { body: runs },
    "GET /api/jobs/scrape/runs/active": { body: null },
    ...summaries,
  });
}

const pages = () => screen.getByRole("navigation", { name: "Pages" });

// Each group in the sidebar: its label, and the names of its links.
const groups = () =>
  within(pages())
    .getAllByRole("list")
    .filter((list) => list.hasAttribute("aria-labelledby"))
    .map((list) => [
      list.getAttribute("aria-labelledby") &&
        document.getElementById(list.getAttribute("aria-labelledby") as string)?.textContent,
      within(list)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ]);

test("admins find the jobs and the audit log in the sidebar, the page's heading on top", async () => {
  signedInAs(alice);
  const { container, router } = renderApp("/jobs");

  expect(await screen.findByRole("heading", { level: 1, name: "Jobs" })).toBeTruthy();
  const jobs = within(pages()).getByRole("link", { name: "Jobs" });
  expect(jobs.getAttribute("aria-current")).toBe("page");
  expect(await violations(container)).toEqual([]);

  await userEvent.click(within(pages()).getByRole("link", { name: "Audit log" }));

  expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/audit");
  expect(
    within(pages()).getByRole("link", { name: "Audit log" }).getAttribute("aria-current"),
  ).toBe("page");
  expect(jobs.getAttribute("aria-current")).toBeNull();
});

test("the sidebar names InfraSales, next to its icon (no other logo)", async () => {
  signedInAs(vera);
  const { container } = renderApp("/jobs");
  await screen.findByRole("heading", { level: 1, name: "Jobs" });
  const sidebar = container.querySelector("[data-slot=sidebar]") as HTMLElement;

  const name = within(sidebar).getByText("InfraSales");
  const icons = within(sidebar).getAllByRole("presentation"); // decorative: the name says it

  expect(icons.map((icon) => icon.getAttribute("src"))).toEqual(["/favicon.svg"]);
  expect(name.contains(icons[0] as HTMLElement)).toBe(true);
  expect(await violations(container)).toEqual([]);
});

test("admins find every job's runs in the sidebar too; Jobs stays marked on a job's page", async () => {
  signedInAs(alice, [entryAs("succeeded")]);
  const { router } = renderApp("/jobs");
  await screen.findByRole("heading", { level: 1, name: "Jobs" });
  const link = (name: string) => within(pages()).getByRole("link", { name });

  await userEvent.click(link("Job runs"));

  expect(router.state.location.pathname).toBe("/runs");
  expect(link("Job runs").getAttribute("aria-current")).toBe("page");
  expect(link("Jobs").getAttribute("aria-current")).toBeNull();

  // The run's job, linked from the runs (not the Jobs table, leaving as the runs load).
  const runs = await screen.findByRole("table", { name: "The 1 most recent runs, newest first" });
  await userEvent.click(within(runs).getByRole("link", { name: "Source Collection" }));

  expect(await screen.findByRole("heading", { level: 1, name: "Source Collection" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/jobs/scrape");
  expect(link("Jobs").hasAttribute("data-active")).toBe(true); // highlighted, not the page itself
  expect(link("Job runs").getAttribute("aria-current")).toBeNull();
});

test("viewers find the Dashboard, the forecast, the projects and the jobs, no admin pages", async () => {
  signedInAs(vera);
  renderApp("/jobs");

  expect(await screen.findByRole("heading", { level: 1, name: "Jobs" })).toBeTruthy();
  expect(
    within(pages())
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(["Dashboard", "Opportunities", "Forecast", "Projects Soon", "Jobs"]);
  expect(groups()).toEqual([
    ["Projects", ["Opportunities", "Forecast", "Projects Soon"]],
    ["Operations", ["Jobs"]],
  ]); // Collection and General hold admin pages only
});

test("admins find the pages in groups, in the order InfraSales works", async () => {
  signedInAs(alice);
  const { container } = renderApp("/jobs");
  await screen.findByRole("heading", { level: 1, name: "Jobs" });

  expect(groups()).toEqual([
    ["Projects", ["Opportunities", "Forecast", "Projects Soon"]],
    ["Collection", ["Feeds", "Sources"]],
    ["Operations", ["Jobs", "Job runs"]],
    ["General", ["Audit log", "Settings"]],
  ]);
  expect(await violations(container)).toEqual([]);
});

test("the Dashboard is the start page, on its own above the groups", async () => {
  signedInAs(vera);
  const { container } = renderApp("/");

  expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeTruthy();
  const dashboard = within(pages()).getByRole("link", { name: "Dashboard" });
  expect(dashboard.getAttribute("aria-current")).toBe("page");
  expect(dashboard.closest("ul")?.hasAttribute("aria-labelledby")).toBe(false); // in no group
  expect(
    within(pages()).getByRole("link", { name: "Jobs" }).getAttribute("aria-current"),
  ).toBeNull();
  expect(await violations(container)).toEqual([]);
});

test("the sidebar collapses and opens again, by its button or by keyboard (Ctrl+B)", async () => {
  signedInAs(alice);
  const { container } = renderApp("/jobs");
  const toggle = await screen.findByRole("button", { name: "Toggle sidebar" });
  const sidebar = () => container.querySelector("[data-slot=sidebar]")?.getAttribute("data-state");
  expect(sidebar()).toBe("expanded");

  await userEvent.click(toggle);
  expect(sidebar()).toBe("collapsed");

  await userEvent.keyboard("{Control>}b{/Control}");
  expect(sidebar()).toBe("expanded");
});

test("collapsed, the sidebar keeps its icons and names each page in a tooltip", async () => {
  signedInAs(alice);
  const { container } = renderApp("/jobs");
  await userEvent.click(await screen.findByRole("button", { name: "Toggle sidebar" }));
  const sidebar = container.querySelector("[data-slot=sidebar]") as HTMLElement;
  expect(sidebar.getAttribute("data-collapsible")).toBe("icon"); // not off the canvas

  expect(
    within(pages())
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual([
    "Dashboard",
    "Opportunities",
    "Forecast",
    "Projects Soon",
    "Feeds",
    "Sources",
    "Jobs",
    "Job runs",
    "Audit log",
    "Settings",
  ]);
  expect(within(sidebar).getByRole("button", { name: "User menu: alice (admin)" })).toBeTruthy();

  await userEvent.hover(within(pages()).getByRole("link", { name: "Audit log" }));
  expect(
    await screen.findByText("Audit log", { selector: "[data-slot=tooltip-content]" }),
  ).toBeTruthy();
  expect(await violations(container)).toEqual([]);
});

test("on small screens the sidebar is a menu the top bar's button opens", async () => {
  vi.stubGlobal("innerWidth", 500);
  signedInAs(alice);
  renderApp("/jobs");
  await screen.findByRole("heading", { level: 1, name: "Jobs" });
  expect(screen.queryByRole("navigation", { name: "Pages" })).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));

  const menu = await screen.findByRole("dialog", { name: "Menu" });
  expect(within(menu).getByRole("link", { name: "Audit log" })).toBeTruthy();
  expect(within(menu).getByRole("button", { name: "User menu: alice (admin)" })).toBeTruthy();
  expect(await violations(menu)).toEqual([]);

  await userEvent.click(within(menu).getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());

  await userEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));
  await userEvent.click(
    within(await screen.findByRole("dialog", { name: "Menu" })).getByRole("link", {
      name: "Audit log",
    }),
  ); // opening a page closes the menu

  expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());
});
